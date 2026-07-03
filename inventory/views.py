from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone

import csv
import datetime

from .models import Drug, Batch, Supplier, StockTransaction, Alert, CustomUser
from .forms import (
    CustomAuthenticationForm, DrugForm, SupplierForm, BatchForm, 
    StockInForm, StockOutForm, CustomUserForm, BulkUploadForm
)
from django.db import transaction
import openpyxl
import io

from .utils import check_and_create_alerts, process_fefo_stock_out

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f"Welcome back, {user.username}!")
                return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'inventory/auth/login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('login')


@login_required
def profile_view(request):
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.phone = request.POST.get('phone', user.phone)
        user.save()
        messages.success(request, "Profile updated successfully.")
        return redirect('profile')
    return render(request, 'inventory/auth/profile.html')


@login_required
def dashboard_view(request):
    # Run dynamic checks
    check_and_create_alerts()

    # Base Metrics
    total_drugs = Drug.objects.count()
    
    # Active batches (stock remaining > 0)
    batches = Batch.objects.filter(quantity_remaining__gt=0)
    total_items_in_stock = batches.aggregate(Sum('quantity_remaining'))['quantity_remaining__sum'] or 0
    active_batches_count = batches.count()
    
    # Alerts
    pending_alerts = Alert.objects.filter(status='PENDING')
    active_alerts_count = pending_alerts.count()
    
    critical_alerts = pending_alerts.filter(
        Q(alert_type='EXPIRY', batch__expiry_date__lte=timezone.now().date() + datetime.timedelta(days=30)) | 
        Q(alert_type='REORDER')
    )[:5]

    # Low stock count
    low_stock_drugs = [d for d in Drug.objects.all() if d.is_low_stock]
    low_stock_count = len(low_stock_drugs)
    
    # Expired batches count
    expired_batches_count = Batch.objects.filter(expiry_date__lte=timezone.now().date(), quantity_remaining__gt=0).count()

    # Recent Transactions
    recent_transactions = StockTransaction.objects.all().order_by('-transaction_date')[:5]

    # Category breakdown for Chart / Display
    category_data = Drug.objects.values('category').annotate(
        count=Count('id')
    ).order_by('-count')

    # Expiry zone breakdown
    today = timezone.now().date()
    expiring_soon_count = Batch.objects.filter(
        expiry_date__gt=today,
        expiry_date__lte=today + datetime.timedelta(days=90),
        quantity_remaining__gt=0
    ).count()

    context = {
        'total_drugs': total_drugs,
        'total_items_in_stock': total_items_in_stock,
        'active_batches_count': active_batches_count,
        'active_alerts_count': active_alerts_count,
        'low_stock_count': low_stock_count,
        'expired_batches_count': expired_batches_count,
        'expiring_soon_count': expiring_soon_count,
        'critical_alerts': critical_alerts,
        'recent_transactions': recent_transactions,
        'category_data': category_data,
    }
    return render(request, 'inventory/dashboard.html', context)


# --- DRUG VIEWS ---
@login_required
def drug_list(request):
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    
    drugs = Drug.objects.all().order_by('drug_name')
    
    if query:
        drugs = drugs.filter(Q(drug_name__icontains=query) | Q(description__icontains=query))
    if category:
        drugs = drugs.filter(category=category)
        
    # Filter by stock status
    if status == 'low':
        drugs = [d for d in drugs if d.is_low_stock]
    elif status == 'out':
        drugs = [d for d in drugs if d.total_stock == 0]
    elif status == 'normal':
        drugs = [d for d in drugs if not d.is_low_stock and d.total_stock > 0]
        
    categories = Drug.CATEGORY_CHOICES
    
    context = {
        'drugs': drugs,
        'query': query,
        'selected_category': category,
        'selected_status': status,
        'categories': categories,
    }
    return render(request, 'inventory/drugs/list.html', context)


@login_required
def drug_detail(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    batches = drug.batches.all().order_by('expiry_date')
    alerts = drug.alerts.filter(status='PENDING')
    
    context = {
        'drug': drug,
        'batches': batches,
        'alerts': alerts,
    }
    return render(request, 'inventory/drugs/detail.html', context)


@login_required
def drug_create(request):
    if request.method == 'POST':
        form = DrugForm(request.POST)
        if form.is_valid():
            drug = form.save()
            messages.success(request, f"Drug '{drug.drug_name}' added successfully!")
            return redirect('drug_detail', pk=drug.pk)
    else:
        form = DrugForm()
    return render(request, 'inventory/drugs/form.html', {'form': form, 'title': 'Add New Drug'})


@login_required
def drug_edit(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    if request.method == 'POST':
        form = DrugForm(request.POST, instance=drug)
        if form.is_valid():
            form.save()
            messages.success(request, f"Drug '{drug.drug_name}' updated successfully!")
            return redirect('drug_detail', pk=drug.pk)
    else:
        form = DrugForm(instance=drug)
    return render(request, 'inventory/drugs/form.html', {'form': form, 'title': f'Edit Drug: {drug.drug_name}'})


@login_required
def drug_delete(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    if request.method == 'POST':
        drug.delete()
        messages.success(request, f"Drug '{drug.drug_name}' deleted successfully.")
        return redirect('drug_list')
    return render(request, 'inventory/drugs/delete_confirm.html', {'object': drug, 'type': 'Drug'})


# --- SUPPLIER VIEWS ---
@login_required
def supplier_list(request):
    query = request.GET.get('q', '')
    suppliers = Supplier.objects.all().order_by('supplier_name')
    if query:
        suppliers = suppliers.filter(
            Q(supplier_name__icontains=query) | 
            Q(contact_person__icontains=query) |
            Q(email__icontains=query)
        )
    return render(request, 'inventory/suppliers/list.html', {'suppliers': suppliers, 'query': query})


@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save()
            messages.success(request, f"Supplier '{supplier.supplier_name}' added successfully!")
            return redirect('supplier_list')
    else:
        form = SupplierForm()
    return render(request, 'inventory/suppliers/form.html', {'form': form, 'title': 'Add New Supplier'})


@login_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, f"Supplier '{supplier.supplier_name}' updated successfully!")
            return redirect('supplier_list')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'inventory/suppliers/form.html', {'form': form, 'title': f'Edit Supplier: {supplier.supplier_name}'})


@login_required
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        supplier.delete()
        messages.success(request, f"Supplier '{supplier.supplier_name}' deleted successfully.")
        return redirect('supplier_list')
    return render(request, 'inventory/drugs/delete_confirm.html', {'object': supplier, 'type': 'Supplier'})


# --- BATCH VIEWS ---
@login_required
def batch_list(request):
    query = request.GET.get('q', '')
    batches = Batch.objects.all().order_by('expiry_date')
    if query:
        batches = batches.filter(
            Q(batch_number__icontains=query) | 
            Q(drug__drug_name__icontains=query)
        )
    return render(request, 'inventory/batches/list.html', {'batches': batches, 'query': query})


@login_required
def batch_edit(request, pk):
    batch = get_object_or_404(Batch, pk=pk)
    if request.method == 'POST':
        form = BatchForm(request.POST, instance=batch)
        if form.is_valid():
            form.save()
            check_and_create_alerts()
            messages.success(request, f"Batch {batch.batch_number} updated successfully!")
            return redirect('batch_list')
    else:
        form = BatchForm(instance=batch)
    return render(request, 'inventory/batches/form.html', {'form': form, 'title': f'Edit Batch: {batch.batch_number}'})


# --- TRANSACTION & STOCK VIEWS ---
@login_required
def transaction_list(request):
    query = request.GET.get('q', '')
    t_type = request.GET.get('type', '')
    
    transactions = StockTransaction.objects.all().order_by('-transaction_date')
    
    if query:
        transactions = transactions.filter(
            Q(batch__drug__drug_name__icontains=query) | 
            Q(batch__batch_number__icontains=query) |
            Q(reference__icontains=query)
        )
    if t_type:
        transactions = transactions.filter(transaction_type=t_type)
        
    return render(request, 'inventory/transactions/list.html', {
        'transactions': transactions, 
        'query': query,
        'selected_type': t_type
    })


@login_required
def stock_in_view(request):
    if request.method == 'POST':
        form = StockInForm(request.POST)
        if form.is_valid():
            drug = form.cleaned_data['drug']
            batch_num = form.cleaned_data['batch_number']
            mfg_date = form.cleaned_data['manufacturing_date']
            exp_date = form.cleaned_data['expiry_date']
            qty = form.cleaned_data['quantity_received']
            supplier = form.cleaned_data['supplier']
            ref = form.cleaned_data['reference']
            
            # Check if this batch already exists for this drug
            batch, created = Batch.objects.get_or_create(
                drug=drug,
                batch_number=batch_num,
                defaults={
                    'manufacturing_date': mfg_date,
                    'expiry_date': exp_date,
                    'quantity_received': qty,
                    'quantity_remaining': qty,
                    'supplier': supplier
                }
            )
            
            if not created:
                # Augment stock on existing batch
                batch.quantity_received += qty
                batch.quantity_remaining += qty
                batch.save()
            
            # Record transaction
            StockTransaction.objects.create(
                batch=batch,
                transaction_type='IN',
                quantity=qty,
                user=request.user,
                reference=ref or f"Manual Ingestion ({'Created' if created else 'Updated'} Batch)"
            )
            
            check_and_create_alerts()
            messages.success(request, f"Stock-In successful. Added {qty} units of {drug.drug_name} to Batch {batch_num}.")
            return redirect('transaction_list')
    else:
        form = StockInForm()
    return render(request, 'inventory/transactions/stock_in.html', {'form': form})


@login_required
def stock_out_view(request):
    if request.method == 'POST':
        form = StockOutForm(request.POST)
        if form.is_valid():
            method = form.cleaned_data['method']
            qty = form.cleaned_data['quantity']
            ref = form.cleaned_data['reference']
            
            try:
                if method == 'FEFO':
                    drug = form.cleaned_data['drug']
                    process_fefo_stock_out(drug, qty, request.user, ref)
                    messages.success(request, f"Successfully distributed {qty} units of {drug.drug_name} using FEFO.")
                else:
                    batch = form.cleaned_data['batch']
                    # Manual Batch selection
                    batch.quantity_remaining -= qty
                    batch.save()
                    
                    StockTransaction.objects.create(
                        batch=batch,
                        transaction_type='OUT',
                        quantity=qty,
                        user=request.user,
                        reference=ref or f"Manual Batch Dispatch"
                    )
                    check_and_create_alerts()
                    messages.success(request, f"Successfully distributed {qty} units of {batch.drug.drug_name} from Batch {batch.batch_number}.")
                
                return redirect('transaction_list')
            except ValidationError as e:
                form.add_error(None, e.message)
    else:
        # Check if pre-populated from a drug page
        drug_id = request.GET.get('drug_id')
        initial = {'method': 'FEFO'}
        if drug_id:
            drug = get_object_or_404(Drug, id=drug_id)
            initial['drug'] = drug
        form = StockOutForm(initial=initial)
        
    return render(request, 'inventory/transactions/stock_out.html', {'form': form})


# --- ALERTS VIEWS ---
@login_required
def alerts_list(request):
    check_and_create_alerts()
    a_type = request.GET.get('type', '')
    status = request.GET.get('status', 'PENDING') # Default to pending alerts
    
    alerts = Alert.objects.all().order_by('-alert_date')
    
    if a_type:
        alerts = alerts.filter(alert_type=a_type)
    if status:
        alerts = alerts.filter(status=status)
        
    return render(request, 'inventory/alerts/list.html', {
        'alerts': alerts,
        'selected_type': a_type,
        'selected_status': status
    })


@login_required
def resolve_alert(request, pk):
    alert = get_object_or_404(Alert, pk=pk)
    alert.status = 'RESOLVED'
    alert.message = f"RESOLVED manually by {request.user.username}: " + alert.message
    alert.save()
    messages.success(request, "Alert marked as resolved.")
    return redirect('alerts_list')


# --- REPORTS & EXPORT VIEWS ---
def _get_expiring_batches_queryset(request, today):
    expiry_days = request.GET.get('expiry_days', '180')
    expiry_start = request.GET.get('expiry_start', '')
    expiry_end = request.GET.get('expiry_end', '')

    filters = {
        'quantity_remaining__gt': 0,
    }

    if expiry_days == 'custom':
        if expiry_start:
            try:
                filters['expiry_date__gte'] = datetime.datetime.strptime(expiry_start, '%Y-%m-%d').date()
            except ValueError:
                pass
        if expiry_end:
            try:
                filters['expiry_date__lte'] = datetime.datetime.strptime(expiry_end, '%Y-%m-%d').date()
            except ValueError:
                pass
    elif expiry_days == 'all':
        # Show all future expirations
        filters['expiry_date__gt'] = today
    else:
        # Defaults or preset days
        try:
            days = int(expiry_days)
        except ValueError:
            days = 180
            expiry_days = '180'
        
        filters['expiry_date__gt'] = today
        filters['expiry_date__lte'] = today + datetime.timedelta(days=days)

    return Batch.objects.filter(**filters).order_by('expiry_date'), expiry_days, expiry_start, expiry_end


@login_required
def reports_dashboard(request):
    # Dynamic calculations
    today = timezone.now().date()
    
    # 1. Slow moving vs fast moving
    # We can evaluate drugs by total quantity sold/distributed in the last 30 days
    last_30_days = timezone.now() - datetime.timedelta(days=30)
    drug_sales = StockTransaction.objects.filter(
        transaction_type='OUT',
        transaction_date__gte=last_30_days
    ).values('batch__drug__drug_name', 'batch__drug__category').annotate(
        total_dispensed=Sum('quantity')
    ).order_by('-total_dispensed')[:10]

    # 2. Expiry forecasts (with filters)
    expiring_batches, expiry_days, expiry_start, expiry_end = _get_expiring_batches_queryset(request, today)

    # 3. Overall Inventory Value approximation (if cost were tracked, but since we don't have it, let's display counts)
    category_summary = Drug.objects.values('category').annotate(
        total_types=Count('id')
    ).order_by('-total_types')

    context = {
        'drug_sales': drug_sales,
        'expiring_batches': expiring_batches,
        'category_summary': category_summary,
        'expiry_days': expiry_days,
        'expiry_start': expiry_start,
        'expiry_end': expiry_end,
    }
    return render(request, 'inventory/reports/dashboard.html', context)


@login_required
def export_expiring_batches_csv(request):
    today = timezone.now().date()
    expiring_batches, expiry_days, expiry_start, expiry_end = _get_expiring_batches_queryset(request, today)
    
    response = HttpResponse(content_type='text/csv')
    
    # Generate custom filename indicating filters
    if expiry_days == 'custom':
        filename = f"expiring_batches_custom_{expiry_start}_to_{expiry_end}.csv"
    elif expiry_days == 'all':
        filename = "expiring_batches_all_future.csv"
    else:
        filename = f"expiring_batches_{expiry_days}_days.csv"
        
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    writer = csv.writer(response)
    writer.writerow(['Batch Number', 'Drug Name', 'Category', 'Expiry Date', 'Days Remaining', 'Quantity Remaining', 'Expiry Status Zone'])
    
    for batch in expiring_batches:
        writer.writerow([
            batch.batch_number,
            batch.drug.drug_name,
            batch.drug.category,
            batch.expiry_date.strftime('%Y-%m-%d') if batch.expiry_date else '',
            batch.days_until_expiry,
            batch.quantity_remaining,
            batch.expiry_status_zone
        ])
        
    return response



@login_required
def export_drugs_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="drugs_inventory_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Drug Name', 'Category', 'Unit', 'Total Stock', 'Min Stock', 'Reorder Level', 'Max Stock', 'Status'])
    
    drugs = Drug.objects.all().order_by('drug_name')
    for d in drugs:
        status = 'Normal'
        if d.total_stock == 0:
            status = 'Out of Stock'
        elif d.is_low_stock:
            status = 'Low Stock'
            
        writer.writerow([
            d.drug_name, 
            d.category, 
            d.unit, 
            d.total_stock, 
            d.min_stock, 
            d.reorder_level, 
            d.max_stock, 
            status
        ])
        
    return response


@login_required
def export_transactions_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="stock_transactions_log.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Transaction ID', 'Date', 'Type', 'Drug Name', 'Batch Number', 'Quantity', 'User', 'Reference'])
    
    transactions = StockTransaction.objects.all().order_by('-transaction_date')
    for t in transactions:
        writer.writerow([
            t.id,
            t.transaction_date.strftime('%Y-%m-%d %H:%M:%S'),
            t.get_transaction_type_display(),
            t.batch.drug.drug_name,
            t.batch.batch_number,
            t.quantity,
            t.user.username,
            t.reference or ''
        ])
        
    return response


# --- USER MANAGEMENT VIEWS (ADMIN ONLY) ---

def admin_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.role != 'ADMIN':
            messages.error(request, "Access Denied: Admin authorization required.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper

@admin_required
def user_list(request):
    query = request.GET.get('q', '')
    users = CustomUser.objects.all().order_by('username')
    if query:
        users = users.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )
    return render(request, 'inventory/users/list.html', {'users': users, 'query': query})

@admin_required
def user_create(request):
    if request.method == 'POST':
        form = CustomUserForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User '{user.username}' created successfully!")
            return redirect('user_list')
    else:
        form = CustomUserForm()
    return render(request, 'inventory/users/form.html', {'form': form, 'title': 'Create New User'})

@admin_required
def user_edit(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    if request.method == 'POST':
        form = CustomUserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"User '{user.username}' updated successfully!")
            return redirect('user_list')
    else:
        form = CustomUserForm(instance=user)
    return render(request, 'inventory/users/form.html', {'form': form, 'title': f'Edit User: {user.username}'})

@admin_required
def user_delete(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    if user == request.user:
        messages.error(request, "Safety block: You cannot delete your own logged-in administrator account.")
        return redirect('user_list')
    if request.method == 'POST':
        user.delete()
        messages.success(request, f"User '{user.username}' deleted successfully.")
        return redirect('user_list')
    return render(request, 'inventory/drugs/delete_confirm.html', {'object': user, 'type': 'User'})


@login_required
def download_drug_template(request):
    """Generates a downloadable CSV template for bulk drug uploads."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="drug_upload_template.csv"'
    
    writer = csv.writer(response)
    # Headers
    writer.writerow(['drug_name', 'category', 'unit', 'reorder_level', 'min_stock', 'max_stock', 'description'])
    # Sample rows
    writer.writerow(['Paracetamol 500mg', 'TABLET', 'Tablet', '100', '50', '1000', 'For pain relief and fever reduction.'])
    writer.writerow(['Amoxicillin 250mg', 'CAPSULE', 'Capsule', '50', '20', '500', 'Broad-spectrum antibiotic.'])
    writer.writerow(['Cough Syrup', 'SYRUP', 'Bottle', '30', '10', '200', 'Soothing cough formula.'])
    
    return response


@login_required
def bulk_upload_drugs(request):
    errors = []
    success_count = 0
    skipped_count = 0
    
    if request.method == 'POST':
        form = BulkUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']
            name = uploaded_file.name.lower()
            
            rows_data = []
            headers = []
            
            try:
                if name.endswith('.csv'):
                    file_data = uploaded_file.read().decode('utf-8-sig')
                    io_string = io.StringIO(file_data)
                    reader = csv.reader(io_string)
                    rows = list(reader)
                    if rows:
                        headers = [h.strip().lower() for h in rows[0]]
                        for r_idx, r in enumerate(rows[1:], start=2):
                            if not any(cell.strip() for cell in r):
                                continue # skip blank rows
                            row_dict = {}
                            for i, h in enumerate(headers):
                                row_dict[h] = r[i].strip() if i < len(r) else ""
                            row_dict['_row_num'] = r_idx
                            rows_data.append(row_dict)
                else: # .xlsx
                    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                    sheet = wb.active
                    rows = list(sheet.iter_rows(values_only=True))
                    if rows:
                        headers = [str(h).strip().lower() for h in rows[0] if h is not None]
                        for r_idx, r in enumerate(rows[1:], start=2):
                            if not any(cell is not None and str(cell).strip() for cell in r):
                                continue # skip blank rows
                            row_dict = {}
                            for i, h in enumerate(headers):
                                val = r[i] if i < len(r) else ""
                                row_dict[h] = str(val).strip() if val is not None else ""
                            row_dict['_row_num'] = r_idx
                            rows_data.append(row_dict)
            except Exception as e:
                errors.append(f"Failed to parse file: {str(e)}")
                
            # Check required headers
            required_fields = ['drug_name', 'category', 'unit', 'reorder_level', 'min_stock', 'max_stock']
            missing_fields = [f for f in required_fields if f not in headers]
            if missing_fields:
                errors.append(f"Missing required columns in header: {', '.join(missing_fields)}")
                
            if not errors and not rows_data:
                errors.append("The uploaded file does not contain any data rows.")

            if not errors:
                # Validate and insert in transaction
                valid_categories = {k.lower(): k for k, v in Drug.CATEGORY_CHOICES}
                valid_units = {k.lower(): k for k, v in Drug.UNIT_CHOICES}
                
                try:
                    with transaction.atomic():
                        drugs_to_create = []
                        for row in rows_data:
                            row_num = row['_row_num']
                            d_name = row.get('drug_name', '')
                            cat_raw = row.get('category', '').strip().lower()
                            unit_raw = row.get('unit', '').strip().lower()
                            r_lvl = row.get('reorder_level', '')
                            min_s = row.get('min_stock', '')
                            max_s = row.get('max_stock', '')
                            desc = row.get('description', '')
                            
                            # Validations
                            row_errors = []
                            if not d_name:
                                row_errors.append("Drug name is required.")
                                
                            cat = ""
                            if not cat_raw:
                                row_errors.append("Category is required.")
                            elif cat_raw not in valid_categories:
                                row_errors.append(f"Invalid category '{row.get('category', '')}'. Must be one of: {', '.join(valid_categories.values())}.")
                            else:
                                cat = valid_categories[cat_raw]
                                
                            unit = ""
                            if not unit_raw:
                                row_errors.append("Unit is required.")
                            elif unit_raw not in valid_units:
                                row_errors.append(f"Invalid unit '{row.get('unit', '')}'. Must be one of: {', '.join(valid_units.values())}.")
                            else:
                                unit = valid_units[unit_raw]
                                
                            # Numeric validations
                            try:
                                r_lvl_val = int(r_lvl)
                                if r_lvl_val < 0:
                                    row_errors.append("Reorder level must be >= 0.")
                            except ValueError:
                                row_errors.append(f"Invalid reorder level '{r_lvl}'. Must be an integer.")
                                
                            try:
                                min_s_val = int(min_s)
                                if min_s_val < 0:
                                    row_errors.append("Min stock must be >= 0.")
                            except ValueError:
                                row_errors.append(f"Invalid min stock '{min_s}'. Must be an integer.")
                                
                            try:
                                max_s_val = int(max_s)
                                if max_s_val < 0:
                                    row_errors.append("Max stock must be >= 0.")
                            except ValueError:
                                row_errors.append(f"Invalid max stock '{max_s}'. Must be an integer.")
                            
                            if not row_errors:
                                # Check duplicate in DB or list
                                if Drug.objects.filter(drug_name__iexact=d_name).exists() or any(d.drug_name.lower() == d_name.lower() for d in drugs_to_create):
                                    skipped_count += 1
                                else:
                                    drugs_to_create.append(Drug(
                                        drug_name=d_name,
                                        category=cat,
                                        unit=unit,
                                        reorder_level=r_lvl_val,
                                        min_stock=min_s_val,
                                        max_stock=max_s_val,
                                        description=desc
                                    ))
                            else:
                                for err in row_errors:
                                    errors.append(f"Row {row_num}: {err}")
                        
                        if not errors:
                            # Save all
                            Drug.objects.bulk_create(drugs_to_create)
                            success_count = len(drugs_to_create)
                        else:
                            # Raise exception to force transaction rollback
                            raise ValidationError("Validation failed.")
                except ValidationError:
                    # Expected if we have errors, transaction is rolled back
                    pass
                except Exception as e:
                    errors.append(f"Database error occurred: {str(e)}")

            if not errors:
                msg = f"Successfully imported {success_count} new drugs."
                if skipped_count > 0:
                    msg += f" {skipped_count} existing drugs were skipped."
                messages.success(request, msg)
                return redirect('drug_list')
    else:
        form = BulkUploadForm()
        
    return render(request, 'inventory/drugs/bulk_upload.html', {
        'form': form,
        'errors': errors,
        'title': 'Bulk Upload Drugs'
    })


@login_required
def download_stock_in_template(request):
    """Generates a downloadable CSV template for bulk Stock-In uploads."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="stock_in_upload_template.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['drug_name', 'batch_number', 'manufacturing_date', 'expiry_date', 'quantity_received', 'supplier_name', 'reference'])
    
    # Try to write matching real catalog items or fallback to Paracetamol
    drug_sample = Drug.objects.first()
    drug_name = drug_sample.drug_name if drug_sample else "Paracetamol 500mg"
    supplier_sample = Supplier.objects.first()
    supplier_name = supplier_sample.supplier_name if supplier_sample else "Test Pharma Inc"
    
    today = datetime.date.today()
    mfg_date = (today - datetime.timedelta(days=10)).strftime('%Y-%m-%d')
    exp_date = (today + datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    
    writer.writerow([drug_name, 'BATCH-001', mfg_date, exp_date, '500', supplier_name, 'INV-2026-001'])
    writer.writerow([drug_name, 'BATCH-002', mfg_date, exp_date, '250', supplier_name, 'PO-99238'])
    
    return response


@login_required
def bulk_stock_in(request):
    errors = []
    success_count = 0
    
    if request.method == 'POST':
        form = BulkUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = request.FILES['file']
            name = uploaded_file.name.lower()
            
            rows_data = []
            headers = []
            
            try:
                if name.endswith('.csv'):
                    file_data = uploaded_file.read().decode('utf-8-sig')
                    io_string = io.StringIO(file_data)
                    reader = csv.reader(io_string)
                    rows = list(reader)
                    if rows:
                        headers = [h.strip().lower() for h in rows[0]]
                        for r_idx, r in enumerate(rows[1:], start=2):
                            if not any(cell.strip() for cell in r):
                                continue # skip blank rows
                            row_dict = {}
                            for i, h in enumerate(headers):
                                row_dict[h] = r[i].strip() if i < len(r) else ""
                            row_dict['_row_num'] = r_idx
                            rows_data.append(row_dict)
                else: # .xlsx
                    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                    sheet = wb.active
                    rows = list(sheet.iter_rows(values_only=True))
                    if rows:
                        headers = [str(h).strip().lower() for h in rows[0] if h is not None]
                        for r_idx, r in enumerate(rows[1:], start=2):
                            if not any(cell is not None and str(cell).strip() for cell in r):
                                continue # skip blank rows
                            row_dict = {}
                            for i, h in enumerate(headers):
                                val = r[i] if i < len(r) else ""
                                row_dict[h] = str(val).strip() if val is not None else ""
                            row_dict['_row_num'] = r_idx
                            rows_data.append(row_dict)
            except Exception as e:
                errors.append(f"Failed to parse file: {str(e)}")
                
            # Check required headers
            required_fields = ['drug_name', 'batch_number', 'manufacturing_date', 'expiry_date', 'quantity_received']
            missing_fields = [f for f in required_fields if f not in headers]
            if missing_fields:
                errors.append(f"Missing required columns in header: {', '.join(missing_fields)}")
                
            if not errors and not rows_data:
                errors.append("The uploaded file does not contain any data rows.")

            if not errors:
                # --- Pass 1: validate all rows, build cleaned payload ---
                validated_rows = []
                for row in rows_data:
                    row_num = row['_row_num']
                    d_name = row.get('drug_name', '').strip()
                    b_num = row.get('batch_number', '').strip()
                    mfg_str = row.get('manufacturing_date', '').strip()
                    exp_str = row.get('expiry_date', '').strip()
                    qty_str = row.get('quantity_received', '').strip()
                    sup_name = row.get('supplier_name', '').strip()
                    ref = row.get('reference', '').strip()

                    row_errors = []

                    # Validate Drug
                    drug_obj = None
                    if not d_name:
                        row_errors.append("Drug name is required.")
                    else:
                        try:
                            drug_obj = Drug.objects.get(drug_name__iexact=d_name)
                        except Drug.DoesNotExist:
                            row_errors.append(f"Drug '{d_name}' does not exist in catalog. Please add it first.")

                    # Validate Batch Number
                    if not b_num:
                        row_errors.append("Batch number is required.")

                    # Validate Manufacturing Date
                    mfg_date = None
                    if not mfg_str:
                        row_errors.append("Manufacturing date is required.")
                    else:
                        try:
                            mfg_date = datetime.datetime.strptime(mfg_str.split(' ')[0], '%Y-%m-%d').date()
                        except ValueError:
                            row_errors.append(f"Invalid manufacturing date format '{mfg_str}'. Use YYYY-MM-DD.")

                    # Validate Expiry Date
                    exp_date = None
                    if not exp_str:
                        row_errors.append("Expiry date is required.")
                    else:
                        try:
                            exp_date = datetime.datetime.strptime(exp_str.split(' ')[0], '%Y-%m-%d').date()
                        except ValueError:
                            row_errors.append(f"Invalid expiry date format '{exp_str}'. Use YYYY-MM-DD.")

                    # Date ordering
                    if mfg_date and exp_date and mfg_date >= exp_date:
                        row_errors.append("Expiry date must be after manufacturing date.")

                    # Validate Quantity
                    qty_val = 0
                    if not qty_str:
                        row_errors.append("Quantity received is required.")
                    else:
                        try:
                            qty_val = int(qty_str)
                            if qty_val < 1:
                                row_errors.append("Quantity received must be at least 1.")
                        except ValueError:
                            row_errors.append(f"Invalid quantity '{qty_str}'. Must be an integer.")

                    if row_errors:
                        for err in row_errors:
                            errors.append(f"Row {row_num}: {err}")
                    else:
                        validated_rows.append({
                            'drug': drug_obj,
                            'batch_number': b_num,
                            'mfg_date': mfg_date,
                            'exp_date': exp_date,
                            'qty': qty_val,
                            'supplier_name': sup_name,
                            'reference': ref,
                        })

                # --- Pass 2: commit only if zero validation errors ---
                if not errors:
                    try:
                        with transaction.atomic():
                            for payload in validated_rows:
                                # Resolve or create supplier
                                supplier_obj = None
                                if payload['supplier_name']:
                                    supplier_obj, _ = Supplier.objects.get_or_create(
                                        supplier_name__iexact=payload['supplier_name'],
                                        defaults={'supplier_name': payload['supplier_name']}
                                    )

                                # Create or augment batch
                                batch, created = Batch.objects.get_or_create(
                                    drug=payload['drug'],
                                    batch_number=payload['batch_number'],
                                    defaults={
                                        'manufacturing_date': payload['mfg_date'],
                                        'expiry_date': payload['exp_date'],
                                        'quantity_received': payload['qty'],
                                        'quantity_remaining': payload['qty'],
                                        'supplier': supplier_obj
                                    }
                                )
                                if not created:
                                    batch.quantity_received += payload['qty']
                                    batch.quantity_remaining += payload['qty']
                                    batch.save()

                                # Record Stock Transaction
                                StockTransaction.objects.create(
                                    batch=batch,
                                    transaction_type='IN',
                                    quantity=payload['qty'],
                                    user=request.user,
                                    reference=payload['reference'] or f"Bulk Ingestion ({'Created' if created else 'Updated'} Batch)"
                                )
                                success_count += 1
                    except Exception as e:
                        errors.append(f"Database error occurred: {str(e)}")


            if not errors:
                messages.success(request, f"Successfully ingested {success_count} stock batches via bulk upload.")
                check_and_create_alerts()
                return redirect('transaction_list')
    else:
        form = BulkUploadForm()
        
    return render(request, 'inventory/transactions/bulk_stock_in.html', {
        'form': form,
        'errors': errors,
        'title': 'Bulk Stock-In Ingestion',
        'required_cols': [
            ('drug_name', 'must match an existing catalog drug'),
            ('batch_number', 'unique code for this delivery batch'),
            ('manufacturing_date', 'format: YYYY-MM-DD'),
            ('expiry_date', 'format: YYYY-MM-DD, must be after manufacturing'),
            ('quantity_received', 'whole integer ≥ 1'),
            ('supplier_name', 'optional — auto-created if not found'),
            ('reference', 'optional invoice or PO number'),
        ]
    })



