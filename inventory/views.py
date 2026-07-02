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
    StockInForm, StockOutForm, CustomUserForm
)
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

    # 2. Expiry forecasts (batches expiring in the next 180 days)
    expiring_batches = Batch.objects.filter(
        expiry_date__gt=today,
        expiry_date__lte=today + datetime.timedelta(days=180),
        quantity_remaining__gt=0
    ).order_by('expiry_date')

    # 3. Overall Inventory Value approximation (if cost were tracked, but since we don't have it, let's display counts)
    category_summary = Drug.objects.values('category').annotate(
        total_types=Count('id')
    ).order_by('-total_types')

    context = {
        'drug_sales': drug_sales,
        'expiring_batches': expiring_batches,
        'category_summary': category_summary,
    }
    return render(request, 'inventory/reports/dashboard.html', context)


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

