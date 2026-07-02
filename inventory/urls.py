from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    
    # Dashboard
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # Drugs
    path('drugs/', views.drug_list, name='drug_list'),
    path('drugs/add/', views.drug_create, name='drug_create'),
    path('drugs/<int:pk>/', views.drug_detail, name='drug_detail'),
    path('drugs/<int:pk>/edit/', views.drug_edit, name='drug_edit'),
    path('drugs/<int:pk>/delete/', views.drug_delete, name='drug_delete'),
    
    # Suppliers
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/add/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),
    
    # Batches
    path('batches/', views.batch_list, name='batch_list'),
    path('batches/<int:pk>/edit/', views.batch_edit, name='batch_edit'),
    
    # Transactions
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/stock-in/', views.stock_in_view, name='stock_in'),
    path('transactions/stock-out/', views.stock_out_view, name='stock_out'),
    
    # Alerts
    path('alerts/', views.alerts_list, name='alerts_list'),
    path('alerts/<int:pk>/resolve/', views.resolve_alert, name='resolve_alert'),
    
    # Reports
    path('reports/', views.reports_dashboard, name='reports_dashboard'),
    path('reports/export/drugs/', views.export_drugs_csv, name='export_drugs_csv'),
    path('reports/export/transactions/', views.export_transactions_csv, name='export_transactions_csv'),

    # Users (Admin Only)
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
]
