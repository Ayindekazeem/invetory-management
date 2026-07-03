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

    def test_download_drug_template(self):
        """Test downloading the CSV drug upload template."""
        self.client.force_login(self.user)
        response = self.client.get('/drugs/template/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('drug_name,category,unit', response.content.decode('utf-8'))

    def test_bulk_upload_drugs_csv_valid(self):
        """Test bulk upload of valid CSV drug records."""
        self.client.force_login(self.user)
        
        csv_content = (
            "drug_name,category,unit,reorder_level,min_stock,max_stock,description\n"
            "Paracetamol 500mg,tablet,pack,100,50,1000,Pain relief\n"
            "Cough Syrup,syrup,bottle,30,10,200,Soothing formula\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile
        mock_file = SimpleUploadedFile("drugs.csv", csv_content.encode('utf-8'), content_type="text/csv")
        
        response = self.client.post('/drugs/bulk-upload/', {'file': mock_file}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Drug.objects.filter(drug_name="Paracetamol 500mg").count(), 1)
        self.assertEqual(Drug.objects.filter(drug_name="Cough Syrup").count(), 1)

    def test_bulk_upload_drugs_csv_invalid(self):
        """Test bulk upload of invalid CSV drug records fails validation."""
        self.client.force_login(self.user)
        
        # Invalid: category is invalid and min_stock is not an integer
        csv_content = (
            "drug_name,category,unit,reorder_level,min_stock,max_stock,description\n"
            "Invalid Drug,INVALID_CAT,Tablet,100,not-an-int,1000,Pain relief\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile
        mock_file = SimpleUploadedFile("drugs.csv", csv_content.encode('utf-8'), content_type="text/csv")
        
        response = self.client.post('/drugs/bulk-upload/', {'file': mock_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn('errors', response.context)
        self.assertTrue(len(response.context['errors']) > 0)
        self.assertEqual(Drug.objects.filter(drug_name="Invalid Drug").count(), 0)

    def test_reports_dashboard_expiry_filters(self):
        """Test that reports dashboard allows filtering upcoming expirations correctly."""
        self.client.force_login(self.user)
        
        # 1. Default (180 days) - both batches should be included
        response = self.client.get('/reports/')
        self.assertEqual(response.status_code, 200)
        expiring = list(response.context['expiring_batches'])
        self.assertIn(self.batch_critical, expiring)
        self.assertIn(self.batch_monitoring, expiring)

        # 2. Filter for next 30 days - only BATCH-CRT should be included
        response = self.client.get('/reports/', {'expiry_days': '30'})
        self.assertEqual(response.status_code, 200)
        expiring = list(response.context['expiring_batches'])
        self.assertIn(self.batch_critical, expiring)
        self.assertNotIn(self.batch_monitoring, expiring)

        # 3. Custom date range filter - e.g. from 50 days to 150 days out
        today = datetime.date.today()
        start_date = (today + datetime.timedelta(days=50)).strftime('%Y-%m-%d')
        end_date = (today + datetime.timedelta(days=150)).strftime('%Y-%m-%d')
        response = self.client.get('/reports/', {
            'expiry_days': 'custom',
            'expiry_start': start_date,
            'expiry_end': end_date
        })
        self.assertEqual(response.status_code, 200)
        expiring = list(response.context['expiring_batches'])
        self.assertNotIn(self.batch_critical, expiring)
        self.assertIn(self.batch_monitoring, expiring)

    def test_export_expiring_batches_csv_filters(self):
        """Test exporting the filtered expiring batches as CSV file."""
        self.client.force_login(self.user)
        
        # 1. Test Default (180 days) export
        response = self.client.get('/reports/export/expiring-batches/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode('utf-8')
        self.assertIn('BATCH-CRT', content)
        self.assertIn('BATCH-MON', content)

        # 2. Test 30 days export
        response = self.client.get('/reports/export/expiring-batches/', {'expiry_days': '30'})
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('BATCH-CRT', content)
        self.assertNotIn('BATCH-MON', content)

        # 3. Test Custom date range export
        today = datetime.date.today()
        start_date = (today + datetime.timedelta(days=50)).strftime('%Y-%m-%d')
        end_date = (today + datetime.timedelta(days=150)).strftime('%Y-%m-%d')
        response = self.client.get('/reports/export/expiring-batches/', {
            'expiry_days': 'custom',
            'expiry_start': start_date,
            'expiry_end': end_date
        })
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertNotIn('BATCH-CRT', content)
        self.assertIn('BATCH-MON', content)

    def test_bulk_stock_in_csv_valid(self):
        """Test valid bulk stock-in CSV creates batches, transactions, and redirects."""
        self.client.force_login(self.user)
        today = datetime.date.today()
        mfg = (today - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        exp = (today + datetime.timedelta(days=365)).strftime('%Y-%m-%d')

        csv_content = (
            "drug_name,batch_number,manufacturing_date,expiry_date,quantity_received,supplier_name,reference\n"
            f"Paracetamol 500mg,BULK-001,{mfg},{exp},200,Test Pharma Inc,INV-001\n"
            f"Paracetamol 500mg,BULK-002,{mfg},{exp},100,,\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile
        mock_file = SimpleUploadedFile("stock_in.csv", csv_content.encode('utf-8'), content_type="text/csv")

        response = self.client.post('/transactions/stock-in/bulk/', {'file': mock_file}, follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify two new batches were created
        self.assertTrue(self.drug.batches.filter(batch_number='BULK-001').exists())
        self.assertTrue(self.drug.batches.filter(batch_number='BULK-002').exists())

        # Verify stock transactions were created
        batch1 = self.drug.batches.get(batch_number='BULK-001')
        self.assertEqual(StockTransaction.objects.filter(batch=batch1, transaction_type='IN').count(), 1)

        # Verify quantity is correct
        self.assertEqual(batch1.quantity_remaining, 200)

    def test_bulk_stock_in_csv_invalid(self):
        """Test invalid bulk stock-in CSV shows errors and rolls back all changes."""
        self.client.force_login(self.user)
        today = datetime.date.today()
        mfg = (today - datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        exp = (today + datetime.timedelta(days=365)).strftime('%Y-%m-%d')

        csv_content = (
            "drug_name,batch_number,manufacturing_date,expiry_date,quantity_received\n"
            # Row 2: valid
            f"Paracetamol 500mg,INVALID-BATCH-A,{mfg},{exp},100\n"
            # Row 3: drug not in catalog
            f"NonExistentDrug XYZ,INVALID-BATCH-B,{mfg},{exp},50\n"
        )
        from django.core.files.uploadedfile import SimpleUploadedFile
        mock_file = SimpleUploadedFile("stock_in_bad.csv", csv_content.encode('utf-8'), content_type="text/csv")

        response = self.client.post('/transactions/stock-in/bulk/', {'file': mock_file})
        self.assertEqual(response.status_code, 200)
        self.assertIn('errors', response.context)
        self.assertTrue(len(response.context['errors']) > 0)

        # Verify no batches were created (rollback)
        self.assertFalse(self.drug.batches.filter(batch_number='INVALID-BATCH-A').exists())

    def test_bulk_stock_in_template_download(self):
        """Test that the stock-in CSV template is downloadable."""
        self.client.force_login(self.user)
        response = self.client.get('/transactions/stock-in/template/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode('utf-8')
        self.assertIn('drug_name', content)
        self.assertIn('batch_number', content)
        self.assertIn('manufacturing_date', content)
        self.assertIn('expiry_date', content)
        self.assertIn('quantity_received', content)





