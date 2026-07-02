from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import datetime

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', 'Administrator'),
        ('PHARMACIST', 'Pharmacist'),
        ('STOREKEEPER', 'Storekeeper'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='ADMIN')
    phone = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Supplier(models.Model):
    supplier_name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.supplier_name


class Drug(models.Model):
    CATEGORY_CHOICES = (
        ('Tablet', 'Tablet'),
        ('Capsule', 'Capsule'),
        ('Syrup', 'Syrup'),
        ('Injection', 'Injection'),
        ('Suspension', 'Suspension'),
        ('Cream/Ointment', 'Cream/Ointment'),
        ('Inhaler', 'Inhaler'),
        ('Other', 'Other'),
    )
    UNIT_CHOICES = (
        ('Box', 'Box'),
        ('Bottle', 'Bottle'),
        ('Pack', 'Pack'),
        ('Ampoule', 'Ampoule'),
        ('Vial', 'Vial'),
        ('Tube', 'Tube'),
        ('Tablet', 'Tablet'),
        ('Capsule', 'Capsule'),
    )
    drug_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Tablet')
    unit = models.CharField(max_length=50, choices=UNIT_CHOICES, default='Box')
    reorder_level = models.IntegerField(default=10)
    min_stock = models.IntegerField(default=5)
    max_stock = models.IntegerField(default=100)

    @property
    def total_stock(self):
        # Calculate sum of quantity_remaining in active (non-expired) batches
        # We can sum all batches that have quantity remaining > 0
        total = self.batches.filter(quantity_remaining__gt=0).aggregate(
            models.Sum('quantity_remaining')
        )['quantity_remaining__sum']
        return total if total is not None else 0

    @property
    def is_low_stock(self):
        return self.total_stock <= self.reorder_level

    def __str__(self):
        return f"{self.drug_name} ({self.category})"


class Batch(models.Model):
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    manufacturing_date = models.DateField()
    expiry_date = models.DateField()
    quantity_received = models.IntegerField()
    quantity_remaining = models.IntegerField()
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='batches')

    class Meta:
        verbose_name_plural = "Batches"

    @property
    def is_expired(self):
        return self.expiry_date <= datetime.date.today()

    @property
    def days_until_expiry(self):
        delta = self.expiry_date - datetime.date.today()
        return delta.days

    @property
    def expiry_status_zone(self):
        days = self.days_until_expiry
        if days < 0:
            return 'EXPIRED'  # Dark Red
        elif days <= 30:
            return 'CRITICAL'  # Red alert: 0-30 days
        elif days <= 90:
            return 'PLANNING'  # Yellow alert: 31-90 days
        elif days <= 180:
            return 'MONITORING'  # Blue alert: 91-180 days
        else:
            return 'SAFE'      # Normal: > 180 days

    def __str__(self):
        return f"{self.drug.drug_name} - Batch {self.batch_number} (Rem: {self.quantity_remaining})"


class StockTransaction(models.Model):
    TRANSACTION_TYPES = (
        ('IN', 'Stock-In'),
        ('OUT', 'Stock-Out'),
    )
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=3, choices=TRANSACTION_TYPES)
    quantity = models.IntegerField()
    transaction_date = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='transactions')
    reference = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.get_transaction_type_display()} - {self.quantity} unit(s) of {self.batch.drug.drug_name} (Batch: {self.batch.batch_number})"


class Alert(models.Model):
    ALERT_TYPES = (
        ('EXPIRY', 'Expiry Date Alert'),
        ('REORDER', 'Low Stock Reorder Alert'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('RESOLVED', 'Resolved'),
    )
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, null=True, blank=True, related_name='alerts')
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, null=True, blank=True, related_name='alerts')
    alert_type = models.CharField(max_length=10, choices=ALERT_TYPES)
    alert_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    message = models.TextField()

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.status} ({self.alert_date.strftime('%Y-%m-%d')})"
