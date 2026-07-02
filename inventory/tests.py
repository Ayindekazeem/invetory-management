from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
import datetime

from .models import Drug, Batch, Supplier, StockTransaction, Alert
from .utils import check_and_create_alerts, process_fefo_stock_out

class InventorySystemTestCase(TestCase):
    def setUp(self):
        # Create user
        User = get_user_model()
        self.user = User.objects.create_user(
            username='testpharmacist',
            password='password123',
            role='PHARMACIST'
        )
        
        # Create Supplier
        self.supplier = Supplier.objects.create(
            supplier_name="Test Pharma Inc",
            phone="+123456789",
            email="test@test.com"
        )
        
        # Create Drug
        self.drug = Drug.objects.create(
            drug_name="Paracetamol 500mg",
            category="Tablet",
            unit="Pack",
            reorder_level=10,
            min_stock=5,
            max_stock=100
        )
        
        # Create Batches
        today = datetime.date.today()
        
        # Batch 1 (expires in 15 days - Critical)
        self.batch_critical = Batch.objects.create(
            drug=self.drug,
            batch_number="BATCH-CRT",
            manufacturing_date=today - datetime.timedelta(days=30),
            expiry_date=today + datetime.timedelta(days=15),
            quantity_received=20,
            quantity_remaining=20,
            supplier=self.supplier
        )
        
        # Batch 2 (expires in 100 days - Monitoring)
        self.batch_monitoring = Batch.objects.create(
            drug=self.drug,
            batch_number="BATCH-MON",
            manufacturing_date=today - datetime.timedelta(days=10),
            expiry_date=today + datetime.timedelta(days=100),
            quantity_received=50,
            quantity_remaining=50,
            supplier=self.supplier
        )

    def test_batch_expiry_status_zone(self):
        """Test that batch expiration status zones are correctly classified."""
        self.assertEqual(self.batch_critical.expiry_status_zone, 'CRITICAL')
        self.assertEqual(self.batch_monitoring.expiry_status_zone, 'MONITORING')
        
        # Create an expired batch
        expired_batch = Batch.objects.create(
            drug=self.drug,
            batch_number="BATCH-EXP",
            manufacturing_date=datetime.date.today() - datetime.timedelta(days=100),
            expiry_date=datetime.date.today() - datetime.timedelta(days=5),
            quantity_received=10,
            quantity_remaining=10
        )
        self.assertEqual(expired_batch.expiry_status_zone, 'EXPIRED')

    def test_drug_stock_properties(self):
        """Test total stock calculations and low stock logic."""
        # Total stock should sum both active batches (20 + 50 = 70)
        self.assertEqual(self.drug.total_stock, 70)
        self.assertFalse(self.drug.is_low_stock)
        
        # Reduce stock so it becomes low stock
        self.batch_critical.quantity_remaining = 2
        self.batch_critical.save()
        self.batch_monitoring.quantity_remaining = 5
        self.batch_monitoring.save()
        
        # Total stock = 7, reorder level = 10
        self.assertEqual(self.drug.total_stock, 7)
        self.assertTrue(self.drug.is_low_stock)

    def test_fefo_stock_out_distribution(self):
        """Verify that process_fefo_stock_out deducts from the soonest expiring batch first (FEFO)."""
        # Dispense 15 units. Since Batch 1 (expires in 15 days) has 20 units, it should cover it completely.
        process_fefo_stock_out(self.drug, 15, self.user, "Dispense test 1")
        
        # Reload from DB
        self.batch_critical.refresh_from_db()
        self.batch_monitoring.refresh_from_db()
        
        self.assertEqual(self.batch_critical.quantity_remaining, 5) # 20 - 15 = 5
        self.assertEqual(self.batch_monitoring.quantity_remaining, 50) # Unchanged
        
        # Dispense another 10 units. This exceeds Batch 1's remaining (5 units).
        # It should deplete Batch 1 completely (5 units) and deduct the rest (5 units) from Batch 2.
        process_fefo_stock_out(self.drug, 10, self.user, "Dispense test 2")
        
        self.batch_critical.refresh_from_db()
        self.batch_monitoring.refresh_from_db()
        
        self.assertEqual(self.batch_critical.quantity_remaining, 0)
        self.assertEqual(self.batch_monitoring.quantity_remaining, 45) # 50 - 5 = 45

    def test_fefo_stock_out_insufficient_stock(self):
        """Verify that process_fefo_stock_out raises ValidationError when trying to dispense more than available."""
        with self.assertRaises(ValidationError):
            process_fefo_stock_out(self.drug, 100, self.user, "Too much")

    def test_alerts_auto_generation(self):
        """Verify check_and_create_alerts correctly creates and resolves Alert instances."""
        Alert.objects.all().delete()
        check_and_create_alerts()
        
        # Since BATCH-CRT is expiring in 15 days, it should generate an Expiry warning alert.
        # Since total stock is 70 (reorder level is 10), no Low Stock alert should be generated.
        expiry_alerts = Alert.objects.filter(alert_type='EXPIRY', status='PENDING')
        reorder_alerts = Alert.objects.filter(alert_type='REORDER', status='PENDING')
        
        self.assertEqual(expiry_alerts.count(), 2)
        self.assertEqual(reorder_alerts.count(), 0)
        alert_messages = "".join(alert.message for alert in expiry_alerts)
        self.assertIn("BATCH-CRT", alert_messages)
        self.assertIn("BATCH-MON", alert_messages)
        
        # Deplete stock below reorder level (7 units total)
        self.batch_critical.quantity_remaining = 0
        self.batch_critical.save()
        self.batch_monitoring.quantity_remaining = 7
        self.batch_monitoring.save()
        
        check_and_create_alerts()
        
        # Now there should be a Low Stock alert as well
        self.assertEqual(Alert.objects.filter(alert_type='REORDER', status='PENDING').count(), 1)
        
        # Replenish stock
        self.batch_monitoring.quantity_remaining = 50
        self.batch_monitoring.save()
        
        check_and_create_alerts()
        
        # Low stock alert should now be RESOLVED
        self.assertEqual(Alert.objects.filter(alert_type='REORDER', status='PENDING').count(), 0)
        self.assertEqual(Alert.objects.filter(alert_type='REORDER', status='RESOLVED').count(), 1)

    def test_role_based_access_to_users_list(self):
        """Test that only ADMIN users can access the user list view."""
        response = self.client.get('/users/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/?next=/users/')

        # 2. Try accessing as PHARMACIST (should redirect to dashboard with access denied)
        self.client.force_login(self.user)
        response = self.client.get('/users/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/dashboard/')
        
        # Verify message was stored in session
        messages_list = list(response.wsgi_request._messages)
        self.assertEqual(len(messages_list), 1)
        self.assertIn("Access Denied", messages_list[0].message)
        
        self.client.logout()

        # 3. Try accessing as ADMIN
        User = get_user_model()
        admin_user = User.objects.create_user(
            username='admin_test_user',
            password='password123',
            role='ADMIN'
        )
        self.client.force_login(admin_user)
        response = self.client.get('/users/')
        self.assertEqual(response.status_code, 200)

