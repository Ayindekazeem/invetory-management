from django.utils import timezone
from django.db import transaction, models
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.conf import settings
import datetime
import logging
from .models import Drug, Batch, StockTransaction, Alert, Location

logger = logging.getLogger(__name__)

def send_email_alert(recipient_email, subject, message):
    """Sends email alert using Django's core send_mail."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'alerts@rxstock.com'),
            recipient_list=[recipient_email],
            fail_silently=True
        )
        logger.info(f"Email alert sent to {recipient_email}")
    except Exception as e:
        logger.error(f"Failed to send email alert to {recipient_email}: {e}")

def send_sms_alert(recipient_phone, message):
    """Simulates sending SMS alert by logging it to the console and logger."""
    log_msg = f"[SMS ALERT] Sent to {recipient_phone}: {message}"
    print(log_msg)
    logger.info(log_msg)

def dispatch_alert_notifications(location, alert):
    """Dispatches alerts via Email and SMS to both the location and its staff."""
    subject = f"RxStock Alert: {alert.get_alert_type_display()} at {location.name}"
    message = alert.message
    
    # 1. Alert the location directly
    if location.email:
        send_email_alert(location.email, subject, message)
    if location.phone:
        send_sms_alert(location.phone, message)
        
    # 2. Alert the location's assigned users
    for user in location.users.all():
        if user.email:
            send_email_alert(user.email, subject, message)
        if user.phone:
            send_sms_alert(user.phone, message)


def check_and_create_alerts():
    """
    Checks all drugs and batches to generate appropriate expiry and reorder alerts.
    Can be run on dashboard load, transaction save, or via background cron.
    Calculates stock levels and expiry statuses independently per store location.
    """
    today = datetime.date.today()
    locations = Location.objects.all()
    
    for loc in locations:
        # 1. Expiry Date Alerts per location
        active_batches = Batch.objects.filter(location=loc, quantity_remaining__gt=0)
        
        for batch in active_batches:
            days_left = batch.days_until_expiry
            zone = batch.expiry_status_zone
            
            if zone in ['EXPIRED', 'CRITICAL', 'PLANNING', 'MONITORING']:
                # Create message based on zone
                if zone == 'EXPIRED':
                    msg = f"CRITICAL: Batch {batch.batch_number} of {batch.drug.drug_name} EXPIRED on {batch.expiry_date} at {loc.name}. Current stock: {batch.quantity_remaining}."
                elif zone == 'CRITICAL':
                    msg = f"CRITICAL: Batch {batch.batch_number} of {batch.drug.drug_name} is expiring in {days_left} days ({batch.expiry_date}) at {loc.name}."
                elif zone == 'PLANNING':
                    msg = f"Planning: Batch {batch.batch_number} of {batch.drug.drug_name} is expiring in {days_left} days ({batch.expiry_date}) at {loc.name}. Plan for usage or return."
                else:  # MONITORING
                    msg = f"Monitoring: Batch {batch.batch_number} of {batch.drug.drug_name} expires on {batch.expiry_date} at {loc.name} ({days_left} days remaining)."
                
                # Check if there is already a PENDING alert for this batch and location
                existing_alert = Alert.objects.filter(batch=batch, location=loc, alert_type='EXPIRY', status='PENDING').first()
                if existing_alert:
                    # Update message if it changed
                    if existing_alert.message != msg:
                        existing_alert.message = msg
                        existing_alert.alert_date = timezone.now()
                        existing_alert.save()
                else:
                    new_alert = Alert.objects.create(
                        drug=batch.drug,
                        batch=batch,
                        location=loc,
                        alert_type='EXPIRY',
                        message=msg,
                        status='PENDING'
                    )
                    dispatch_alert_notifications(loc, new_alert)
            else:
                # If batch is SAFE, resolve any pending expiry alerts for this batch/location
                Alert.objects.filter(batch=batch, location=loc, alert_type='EXPIRY', status='PENDING').update(
                    status='RESOLVED',
                    message=f"RESOLVED: Batch {batch.batch_number} of {batch.drug.drug_name} at {loc.name} has sufficient shelf life."
                )
                
        # Clean up empty batches: resolve their pending alerts
        empty_batches = Batch.objects.filter(location=loc, quantity_remaining=0)
        for batch in empty_batches:
            Alert.objects.filter(batch=batch, location=loc, alert_type='EXPIRY', status='PENDING').update(
                status='RESOLVED',
                message=f"RESOLVED: Batch {batch.batch_number} of {batch.drug.drug_name} at {loc.name} has been fully distributed (0 remaining)."
            )

        # 2. Reorder Alerts per location
        drugs = Drug.objects.all()
        for drug in drugs:
            # Calculate total stock of this drug AT THIS LOCATION
            total_stock = Batch.objects.filter(drug=drug, location=loc, quantity_remaining__gt=0).aggregate(
                models.Sum('quantity_remaining')
            )['quantity_remaining__sum'] or 0
            
            if total_stock <= drug.reorder_level:
                # Low stock! Generate or verify alert
                suggested_order = drug.max_stock - total_stock
                if suggested_order < 0:
                    suggested_order = 0
                
                msg = f"Low Stock: {drug.drug_name} has fallen below its reorder level of {drug.reorder_level} at {loc.name}. Current stock: {total_stock} (Min: {drug.min_stock}). Suggested order quantity: {suggested_order}."
                
                existing_alert = Alert.objects.filter(drug=drug, location=loc, alert_type='REORDER', status='PENDING').first()
                if existing_alert:
                    if existing_alert.message != msg:
                        existing_alert.message = msg
                        existing_alert.alert_date = timezone.now()
                        existing_alert.save()
                else:
                    new_alert = Alert.objects.create(
                        drug=drug,
                        location=loc,
                        alert_type='REORDER',
                        message=msg,
                        status='PENDING'
                    )
                    dispatch_alert_notifications(loc, new_alert)
            else:
                # Stock level is normal. Resolve any pending reorder alerts
                Alert.objects.filter(drug=drug, location=loc, alert_type='REORDER', status='PENDING').update(
                    status='RESOLVED',
                    message=f"RESOLVED: {drug.drug_name} stock level at {loc.name} replenished to {total_stock} (Reorder level: {drug.reorder_level})."
                )


def process_fefo_stock_out(drug, quantity_to_deduct, user, location, reference=None):
    """
    Deducts stock from a drug's active batches at a specific location using FEFO (First-Expired, First-Out) logic.
    Creates transaction logs for each batch deduction inside a transaction block.
    """
    if quantity_to_deduct <= 0:
        raise ValidationError("Deduction quantity must be greater than zero.")
        
    # Calculate stock at the specific location
    total_available = Batch.objects.filter(drug=drug, location=location, quantity_remaining__gt=0).aggregate(
        models.Sum('quantity_remaining')
    )['quantity_remaining__sum'] or 0
    
    if total_available < quantity_to_deduct:
        raise ValidationError(
            f"Insufficient stock for {drug.drug_name} at {location.name}. Requested: {quantity_to_deduct}, Available: {total_available}."
        )

    remaining_to_deduct = quantity_to_deduct

    # Use atomic transaction to guarantee all-or-nothing stock deductions
    with transaction.atomic():
        # Get active, non-expired batches first at this location, sorted by expiry_date ASC.
        batches = Batch.objects.filter(drug=drug, location=location, quantity_remaining__gt=0).order_by('expiry_date')
        
        for batch in batches:
            if remaining_to_deduct <= 0:
                break
                
            if batch.quantity_remaining >= remaining_to_deduct:
                # This batch has enough to cover the rest of the deduction
                batch.quantity_remaining -= remaining_to_deduct
                batch.save()
                
                # Record transaction
                StockTransaction.objects.create(
                    batch=batch,
                    transaction_type='OUT',
                    quantity=remaining_to_deduct,
                    user=user,
                    location=location,
                    reference=reference or "FEFO Distribution"
                )
                remaining_to_deduct = 0
            else:
                # Deduct all stock from this batch and continue to next batch
                deducted = batch.quantity_remaining
                remaining_to_deduct -= deducted
                
                batch.quantity_remaining = 0
                batch.save()
                
                # Record transaction
                StockTransaction.objects.create(
                    batch=batch,
                    transaction_type='OUT',
                    quantity=deducted,
                    user=user,
                    location=location,
                    reference=reference or "FEFO Distribution (Partial Batch)"
                )
                
    # Run alert update to catch low stock or resolved expiry alerts
    check_and_create_alerts()
    return True
