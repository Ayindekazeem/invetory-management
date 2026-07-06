from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
import datetime
from inventory.models import Drug, Batch, Supplier, StockTransaction, Alert, Location, StockTransfer
from inventory.utils import check_and_create_alerts

class Command(BaseCommand):
    help = 'Seeds the database with realistic initial multi-location, supplier, drug, batch, and transaction records for demonstration.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting data seeding...")

        # 0. Clear existing transactional / location data to avoid duplicate seeding errors
        StockTransfer.objects.all().delete()
        Batch.objects.all().delete()
        StockTransaction.objects.all().delete()
        Alert.objects.all().delete()
        Location.objects.all().delete()

        # 1. Create Locations
        central_store = Location.objects.create(
            name="Central Store",
            is_central=True,
            email="central@rxstock.com",
            phone="+2348011111111"
        )
        first_floor = Location.objects.create(
            name="First Floor Pharmacy",
            is_central=False,
            email="first_floor@rxstock.com",
            phone="+2348022222222"
        )
        second_floor = Location.objects.create(
            name="Second Floor Pharmacy",
            is_central=False,
            email="second_floor@rxstock.com",
            phone="+2348033333333"
        )
        third_floor = Location.objects.create(
            name="In-patient Third Floor Pharmacy",
            is_central=False,
            email="third_floor@rxstock.com",
            phone="+2348044444444"
        )
        fifth_floor = Location.objects.create(
            name="In-patient Fifth Floor Pharmacy",
            is_central=False,
            email="fifth_floor@rxstock.com",
            phone="+2348055555555"
        )
        sixth_floor = Location.objects.create(
            name="In-patient Sixth Floor Pharmacy",
            is_central=False,
            email="sixth_floor@rxstock.com",
            phone="+2348066666666"
        )
        self.stdout.write("Created locations.")
        
        # 2. Create/Update Users
        User = get_user_model()
        
        # Admin - no fixed location, can switch
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@rxstock.com',
                'first_name': 'Sarah',
                'last_name': 'Conner',
                'role': 'ADMIN',
                'is_staff': True,
                'is_superuser': True,
            }
        )
        if created:
            admin_user.set_password('admin123')
        admin_user.location = None
        admin_user.save()
        self.stdout.write("Configured user: admin / admin123")
            
        # Pharmacist - locked to First Floor Pharmacy
        pharm_user, created = User.objects.get_or_create(
            username='pharmacist',
            defaults={
                'email': 'pharmacist@rxstock.com',
                'first_name': 'David',
                'last_name': 'Miller',
                'role': 'PHARMACIST',
                'is_staff': True,
            }
        )
        if created:
            pharm_user.set_password('pharm123')
        pharm_user.location = first_floor
        pharm_user.save()
        self.stdout.write("Configured user: pharmacist / pharm123")

        # Storekeeper - locked to Central Store
        store_user, created = User.objects.get_or_create(
            username='storekeeper',
            defaults={
                'email': 'store@rxstock.com',
                'first_name': 'James',
                'last_name': 'Wilson',
                'role': 'STOREKEEPER',
                'is_staff': True,
            }
        )
        if created:
            store_user.set_password('store123')
        store_user.location = central_store
        store_user.save()
        self.stdout.write("Configured user: storekeeper / store123")

        # 3. Create Suppliers
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

        # 4. Create Drugs Catalog
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

        # 5. Create Batches & Stock-In Transactions by Location
        today = datetime.date.today()

        # Batch definitions helper
        def create_batch_with_stock(drug, batch_no, mfg_days, exp_days, qty, supplier, ref, location):
            mfg_date = today - datetime.timedelta(days=mfg_days)
            exp_date = today + datetime.timedelta(days=exp_days)
            
            batch = Batch.objects.create(
                drug=drug,
                batch_number=batch_no,
                manufacturing_date=mfg_date,
                expiry_date=exp_date,
                quantity_received=qty,
                quantity_remaining=qty,
                supplier=supplier,
                location=location
            )
            
            StockTransaction.objects.create(
                batch=batch,
                transaction_type='IN',
                quantity=qty,
                user=admin_user,
                reference=ref,
                location=location
            )
            return batch

        # --- SEED CENTRAL STORE STOCK ---
        # Paracetamol batches in Central Store
        create_batch_with_stock(paracetamol, 'CS-PARA-EXP-01', 365, -15, 25, medix, "Delivery: Initial batch ingest", central_store)
        create_batch_with_stock(paracetamol, 'CS-PARA-CRT-02', 180, 15, 100, medix, "Delivery: Stock replenishment", central_store)
        create_batch_with_stock(paracetamol, 'CS-PARA-SAF-03', 30, 280, 250, apex, "Delivery: Monthly contract", central_store)

        # Amoxicillin in Central Store
        create_batch_with_stock(amoxicillin, 'CS-AMX-PLN-01', 90, 45, 80, apex, "Emergency stock ingestion", central_store)
        create_batch_with_stock(amoxicillin, 'CS-AMX-SAF-02', 10, 360, 200, globe, "Standard bulk delivery", central_store)

        # Insulin in Central Store
        create_batch_with_stock(insulin, 'CS-INS-SAF-01', 60, 200, 50, medix, "Cold chain bulk order", central_store)

        # Cough Syrup in Central Store
        create_batch_with_stock(syrup, 'CS-SYR-SAF-01', 15, 400, 150, medix, "Restock order #299", central_store)

        # --- SEED FIRST FLOOR PHARMACY STOCK ---
        # Paracetamol in First Floor (Critical / Expired testing)
        create_batch_with_stock(paracetamol, 'FF-PARA-EXP-01', 365, -5, 10, medix, "First floor start stock", first_floor)
        create_batch_with_stock(paracetamol, 'FF-PARA-CRT-02', 180, 10, 12, medix, "First floor restock", first_floor)

        # Insulin in First Floor (Low Stock test: only 2 vials remaining, reorder level is 8)
        create_batch_with_stock(insulin, 'FF-INS-MON-01', 60, 120, 2, medix, "First floor cold chain", first_floor)

        # Cough Syrup in First Floor (Empty batch test)
        b_s1 = create_batch_with_stock(syrup, 'FF-SYR-DEP-01', 200, -50, 30, globe, "First floor syrup setup", first_floor)
        b_s1.quantity_remaining = 0
        b_s1.save()
        StockTransaction.objects.create(
            batch=b_s1,
            transaction_type='OUT',
            quantity=30,
            user=pharm_user,
            reference="FEFO Distribution to Ward B",
            location=first_floor
        )

        # --- SEED SECOND FLOOR PHARMACY STOCK ---
        # Amoxicillin in Second Floor (Low stock test)
        create_batch_with_stock(amoxicillin, 'SF-AMX-SAF-01', 15, 300, 6, apex, "Second floor initial stock", second_floor)

        self.stdout.write("Created batches and stock movement logs by location.")

        # 6. Run Alert Checks
        check_and_create_alerts()
        self.stdout.write("Alert definitions successfully checked and generated.")
        
        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
