from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Supplier, Drug, Batch, StockTransaction, Alert

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'role', 'phone', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role', 'phone')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('role', 'phone')}),
    )

class DrugAdmin(admin.ModelAdmin):
    list_display = ['drug_name', 'category', 'unit', 'reorder_level', 'total_stock', 'is_low_stock']
    list_filter = ['category', 'unit']
    search_fields = ['drug_name', 'description']

class BatchAdmin(admin.ModelAdmin):
    list_display = ['batch_number', 'drug', 'expiry_date', 'quantity_remaining', 'quantity_received', 'is_expired']
    list_filter = ['expiry_date', 'drug__category']
    search_fields = ['batch_number', 'drug__drug_name']

class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'transaction_date', 'transaction_type', 'batch', 'quantity', 'user']
    list_filter = ['transaction_type', 'transaction_date']
    search_fields = ['batch__drug__drug_name', 'reference']

class AlertAdmin(admin.ModelAdmin):
    list_display = ['id', 'alert_date', 'alert_type', 'status', 'message']
    list_filter = ['alert_type', 'status']
    search_fields = ['message']

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(Supplier)
admin.site.register(Drug, DrugAdmin)
admin.site.register(Batch, BatchAdmin)
admin.site.register(StockTransaction, StockTransactionAdmin)
admin.site.register(Alert, AlertAdmin)
