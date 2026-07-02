from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError
import datetime
from .models import Drug, Batch, StockTransaction, Alert

def check_and_create_alerts():
    """
    Checks all drugs and batches to generate appropriate expiry and reorder alerts.
    Can be run on dashboard load, transaction save, or via background cron.
    """
    today = datetime.date.today()
    
    # 1. Expiry Date Alerts
    # Find active batches (stock remaining > 0)
    active_batches = Batch.objects.filter(quantity_remaining__gt=0)
    
    for batch in active_batches:
        days_left = batch.days_until_expiry
        zone = batch.expiry_status_zone
        
        if zone in ['EXPIRED', 'CRITICAL', 'PLANNING', 'MONITORING']:
            # Create message based on zone
            if zone == 'EXPIRED':
                msg = f"CRITICAL: Batch {batch.batch_number} of {batch.drug.drug_name} EXPIRED on {batch.expiry_date}. Current stock: {batch.quantity_remaining}."
                alert_severity = "CRITICAL"
            elif zone == 'CRITICAL':
                msg = f"CRITICAL: Batch {batch.batch_number} of {batch.drug.drug_name} is expiring in {days_left} days ({batch.expiry_date})."
                alert_severity = "CRITICAL"
            elif zone == 'PLANNING':
                msg = f"Planning: Batch {batch.batch_number} of {batch.drug.drug_name} is expiring in {days_left} days ({batch.expiry_date}). Plan for usage or return."
                alert_severity = "WARNING"
            else:  # MONITORING
                msg = f"Monitoring: Batch {batch.batch_number} of {batch.drug.drug_name} expires on {batch.expiry_date} ({days_left} days remaining)."
                alert_severity = "INFO"
            
            # Check if there is already a PENDING alert for this batch
            existing_alert = Alert.objects.filter(batch=batch, alert_type='EXPIRY', status='PENDING').first()
            if existing_alert:
                # Update message if it changed
                if existing_alert.message != msg:
                    existing_alert.message = msg
                    existing_alert.alert_date = timezone.now()
                    existing_alert.save()
            else:
                Alert.objects.create(
                    drug=batch.drug,
                    batch=batch,
                    alert_type='EXPIRY',
                    message=msg,
                    status='PENDING'
                )
        else:
            # If batch is SAFE, resolve any pending expiry alerts for this batch
            Alert.objects.filter(batch=batch, alert_type='EXPIRY', status='PENDING').update(
                status='RESOLVED',
                message=f"RESOLVED: Batch {batch.batch_number} of {batch.drug.drug_name} has sufficient shelf life."
            )
            
    # Clean up empty batches: resolve their pending alerts
    empty_batches = Batch.objects.filter(quantity_remaining=0)
    for batch in empty_batches:
        Alert.objects.filter(batch=batch, alert_type='EXPIRY', status='PENDING').update(
            status='RESOLVED',
            message=f"RESOLVED: Batch {batch.batch_number} of {batch.drug.drug_name} has been fully distributed (0 remaining)."
        )

    # 2. Reorder Alerts
    drugs = Drug.objects.all()
    for drug in drugs:
        total_stock = drug.total_stock
        if drug.is_low_stock:
            # Low stock! Generate or verify alert
            suggested_order = drug.max_stock - total_stock
            if suggested_order < 0:
                suggested_order = 0
            
            msg = f"Low Stock: {drug.drug_name} has fallen below its reorder level of {drug.reorder_level}. Current stock: {total_stock} (Min: {drug.min_stock}). Suggested order quantity: {suggested_order}."
            
            existing_alert = Alert.objects.filter(drug=drug, alert_type='REORDER', status='PENDING').first()
            if existing_alert:
                if existing_alert.message != msg:
                    existing_alert.message = msg
                    existing_alert.alert_date = timezone.now()
                    existing_alert.save()
            else:
                Alert.objects.create(
                    drug=drug,
                    alert_type='REORDER',
                    message=msg,
                    status='PENDING'
                )
        else:
            # Stock level is normal. Resolve any pending reorder alerts
            Alert.objects.filter(drug=drug, alert_type='REORDER', status='PENDING').update(
                status='RESOLVED',
                message=f"RESOLVED: {drug.drug_name} stock level replenished to {total_stock} (Reorder level: {drug.reorder_level})."
            )


def process_fefo_stock_out(drug, quantity_to_deduct, user, reference=None):
    """
    Deducts stock from a drug's active batches using FEFO (First-Expired, First-Out) logic.
    Creates transaction logs for each batch deduction inside a transaction block.
    """
    if quantity_to_deduct <= 0:
        raise ValidationError("Deduction quantity must be greater than zero.")
        
    total_available = drug.total_stock
    if total_available < quantity_to_deduct:
        raise ValidationError(
            f"Insufficient stock for {drug.drug_name}. Requested: {quantity_to_deduct}, Available: {total_available}."
        )

    remaining_to_deduct = quantity_to_deduct

    # Use atomic transaction to guarantee all-or-nothing stock deductions
    with transaction.atomic():
        # Get active, non-expired batches first, then expired if absolutely necessary (but usually alert the user).
        # We sort by expiry_date ASC.
        batches = Batch.objects.filter(drug=drug, quantity_remaining__gt=0).order_by('expiry_date')
        
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
                    reference=reference or "FEFO Distribution (Partial Batch)"
                )
                
    # Run alert update to catch low stock or resolved expiry alerts
    check_and_create_alerts()
    return True
