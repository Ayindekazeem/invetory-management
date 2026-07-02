from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
import datetime
from inventory.models import Drug, Batch, Supplier, StockTransaction, Alert
from inventory.utils import check_and_create_alerts

class Command(BaseCommand):
    help = 'Seeds the database with realistic initial supplier, drug, batch, and transaction records for demonstration.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting data seeding...")
        
        # 1. Create Users
        User = get_user_model()
        
        # Admin
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@rxstock.com',
                'first_name': 'Sarah',
                'last_name': 'Conner',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write("Created user: admin / admin123")
            
        # Pharmacist
        pharm_user, created = User.objects.get_or_create(
            username='pharmacist',
            defaults={
                'email': 'pharmacist@rxstock.com',
                'first_name': 'David',
                'last_name': 'Miller',
                'role': 'PHARMACIST',
                'is_staff': True
            }
        )
        if created:
            pharm_user.set_password('pharm123')
            pharm_user.save()
            self.stdout.write("Created user: pharmacist / pharm123")

        # Storekeeper
        store_user, created = User.objects.get_or_create(
            username='storekeeper',
            defaults={
                'email': 'store@rxstock.com',
                'first_name': 'James',
                'last_name': 'Wilson',
                'role': 'STOREKEEPER',
                'is_staff': True
            }
        )
        if created:
            store_user.set_password('store123')
            store_user.save()
            self.stdout.write("Created user: storekeeper / store123")

        # 2. Create Suppliers
        medix, _ = Supplier.objects.get_or_create(
            supplier_name="Medix Distributors",
            defaults={
                'contact_person': 'Dr. Robert Carter',
                'phone': '+234 803 123 4567',
                'email': 'orders@medix.com',
                'address': 'Plot 15, Industrial Estate, Ikeja, Lagos'
            }
        )
        apex, _ = Supplier.objects.get_or_create(
            supplier_name="Apex Pharmaceuticals",
            defaults={
                'contact_person': 'Mrs. Gladys Stone',
                'phone': '+234 812 987 6543',
                'email': 'info@apexpharma.com',
                'address': '44 Commercial Avenue, Yaba, Lagos'
            }
        )
        globe, _ = Supplier.objects.get_or_create(
            supplier_name="Globe Chemicals Ltd",
            defaults={
                'contact_person': 'Mr. Ken Okoye',
                'phone': '+234 705 555 4433',
                'email': 'sales@globechems.com',
                'address': '88 Wharf Road, Apapa, Lagos'
            }
        )
        self.stdout.write("Created suppliers.")

        # 3. Create Drugs
        paracetamol, _ = Drug.objects.get_or_create(
            drug_name="Paracetamol 500mg",
            defaults={
                'description': 'Standard analgesic and antipyretic for mild to moderate pain and fever relief.',
                'category': 'Tablet',
                'unit': 'Pack',
                'reorder_level': 20,
                'min_stock': 10,
                'max_stock': 200
            }
        )
        amoxicillin, _ = Drug.objects.get_or_create(
            drug_name="Amoxicillin 250mg",
            defaults={
                'description': 'Moderate-spectrum, bactericidal, beta-lactam antibiotic used to treat bacterial infections.',
                'category': 'Capsule',
                'unit': 'Box',
                'reorder_level': 15,
                'min_stock': 5,
                'max_stock': 100
            }
        )
        insulin, _ = Drug.objects.get_or_create(
            drug_name="Insulin Glargine",
            defaults={
                'description': 'Long-acting basal insulin analogue, given once daily for the management of type 1 and type 2 diabetes mellitus.',
                'category': 'Injection',
                'unit': 'Vial',
                'reorder_level': 8,
                'min_stock': 3,
                'max_stock': 50
            }
        )
        syrup, _ = Drug.objects.get_or_create(
            drug_name="Cough Syrup (Guaifenesin)",
            defaults={
                'description': 'Expectorant medication which helps loosen congestion in your chest and throat.',
                'category': 'Syrup',
                'unit': 'Bottle',
                'reorder_level': 10,
                'min_stock': 4,
                'max_stock': 80
            }
        )
        inhaler, _ = Drug.objects.get_or_create(
            drug_name="Salbutamol Inhaler 100mcg",
            defaults={
                'description': 'Beta-2 adrenergic receptor agonist used for the relief of bronchospasm in asthma and COPD.',
                'category': 'Inhaler',
                'unit': 'Box',
                'reorder_level': 12,
                'min_stock': 6,
                'max_stock': 60
            }
        )
        self.stdout.write("Created drugs catalog.")

        # 4. Create Batches & Stock-In Transactions
        today = datetime.date.today()
        
        # Clear existing batches to avoid duplicate seeding errors if run multiple times
        Batch.objects.all().delete()
        StockTransaction.objects.all().delete()
        Alert.objects.all().delete()

        # Batch definitions helper
        def create_batch_with_stock(drug, batch_no, mfg_days, exp_days, qty, supplier, ref):
            mfg_date = today - datetime.timedelta(days=mfg_days)
            exp_date = today + datetime.timedelta(days=exp_days)
            
            batch = Batch.objects.create(
                drug=drug,
                batch_number=batch_no,
                manufacturing_date=mfg_date,
                expiry_date=exp_date,
                quantity_received=qty,
                quantity_remaining=qty,
                supplier=supplier
            )
            
            StockTransaction.objects.create(
                batch=batch,
                transaction_type='IN',
                quantity=qty,
                user=admin_user,
                reference=ref
            )
            return batch

        # Paracetamol batches
        # Batch 1: Expired (Expired 15 days ago)
        create_batch_with_stock(paracetamol, 'PARA-EXP-01', 365, -15, 25, medix, "Delivery: Initial batch ingest")
        # Batch 2: Critical Expiry (Expires in 15 days)
        create_batch_with_stock(paracetamol, 'PARA-CRT-02', 180, 15, 50, medix, "Delivery: Stock replenishment")
        # Batch 3: Normal / Safe (Expires in 280 days)
        create_batch_with_stock(paracetamol, 'PARA-SAF-03', 30, 280, 120, apex, "Delivery: Monthly replenishment contract")

        # Amoxicillin batches
        # Batch 1: Planning Zone (Expires in 45 days)
        create_batch_with_stock(amoxicillin, 'AMX-PLN-01', 90, 45, 10, apex, "Emergency stock ingestion")
        # Batch 2: Safe (Expires in 360 days)
        create_batch_with_stock(amoxicillin, 'AMX-SAF-02', 10, 360, 40, globe, "Standard bulk delivery")

        # Insulin batches
        # Batch 1: Monitoring Zone (Expires in 120 days) - low qty, triggering Low Stock as well!
        create_batch_with_stock(insulin, 'INS-MON-01', 60, 120, 4, medix, "Cold chain special delivery")

        # Cough Syrup batches
        # Batch 1: Expired (Expired 50 days ago) - remaining qty is 0, so it shouldn't raise alerts
        b_s1 = create_batch_with_stock(syrup, 'SYR-DEP-01', 200, -50, 30, globe, "Bulk delivery")
        b_s1.quantity_remaining = 0
        b_s1.save()
        StockTransaction.objects.create(
            batch=b_s1,
            transaction_type='OUT',
            quantity=30,
            user=pharm_user,
            reference="FEFO Distribution to Ward B"
        )
        
        # Batch 2: Safe (Expires in 400 days)
        create_batch_with_stock(syrup, 'SYR-SAF-02', 15, 400, 75, medix, "Restock order #299")

        # Salbutamol Inhaler batches
        # Batch 1: Critical (Expires in 8 days)
        create_batch_with_stock(inhaler, 'INH-CRT-01', 180, 8, 3, apex, "Emergency replenishment")
        # Batch 2: Safe (Expires in 300 days)
        create_batch_with_stock(inhaler, 'INH-SAF-02', 30, 300, 20, apex, "Contract restock")

        self.stdout.write("Created batches and stock movement logs.")

        # 5. Run Alert Checks
        check_and_create_alerts()
        self.stdout.write("Alert definitions successfully checked and generated.")
        
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
