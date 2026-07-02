from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import Drug, Batch, Supplier, StockTransaction, CustomUser

class TailwindFormMixin:
    """Mixin to inject consistent, premium Tailwind CSS classes into form fields."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            base_classes = (
                "w-full bg-white border border-slate-300 text-slate-900 rounded-lg px-4 py-2 "
                "focus:outline-none focus:border-teal-600 focus:ring-1 focus:ring-teal-600 "
                "dark:bg-slate-800 dark:border-slate-700 dark:text-white dark:focus:border-teal-500 dark:focus:ring-teal-500 "
                "transition duration-150 ease-in-out placeholder-slate-400 dark:placeholder-slate-500 text-sm"
            )
            
            # Checkbox styling
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = "h-4 w-4 rounded bg-white border-slate-300 text-teal-600 focus:ring-teal-500 dark:bg-slate-800 dark:border-slate-700"
            else:
                existing_classes = field.widget.attrs.get('class', '')
                field.widget.attrs['class'] = f"{base_classes} {existing_classes}".strip()


class CustomAuthenticationForm(TailwindFormMixin, AuthenticationForm):
    """Custom Login Form with styling."""
    username = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'Enter your username'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': '••••••••'}))


class DrugForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Drug
        fields = ['drug_name', 'category', 'unit', 'reorder_level', 'min_stock', 'max_stock', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe drug uses, dosage forms, warnings...'}),
            'drug_name': forms.TextInput(attrs={'placeholder': 'e.g. Paracetamol'}),
            'reorder_level': forms.NumberInput(attrs={'min': 0}),
            'min_stock': forms.NumberInput(attrs={'min': 0}),
            'max_stock': forms.NumberInput(attrs={'min': 1}),
        }


class SupplierForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['supplier_name', 'contact_person', 'phone', 'email', 'address']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Office/Warehouse address'}),
            'supplier_name': forms.TextInput(attrs={'placeholder': 'e.g. PharmaCorp Ltd'}),
            'contact_person': forms.TextInput(attrs={'placeholder': 'e.g. Dr. John Doe'}),
            'phone': forms.TextInput(attrs={'placeholder': '+234...'}),
            'email': forms.EmailInput(attrs={'placeholder': 'info@supplier.com'}),
        }


class BatchForm(TailwindFormMixin, forms.ModelForm):
    class Meta:
        model = Batch
        fields = ['drug', 'batch_number', 'manufacturing_date', 'expiry_date', 'quantity_received', 'supplier']
        widgets = {
            'manufacturing_date': forms.DateInput(attrs={'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
            'batch_number': forms.TextInput(attrs={'placeholder': 'e.g. BATCH-2026-A'}),
            'quantity_received': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Total units received'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        mfg_date = cleaned_data.get("manufacturing_date")
        exp_date = cleaned_data.get("expiry_date")
        
        if mfg_date and exp_date and mfg_date >= exp_date:
            raise forms.ValidationError("Expiry date must be after manufacturing date.")
        return cleaned_data


class StockInForm(TailwindFormMixin, forms.Form):
    """
    Form to record Stock-In, which creates a new batch or augments an existing one.
    It combines batch fields and creates transaction records.
    """
    drug = forms.ModelChoiceField(queryset=Drug.objects.all(), empty_label="Select Drug")
    batch_number = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'placeholder': 'e.g. BATCH-101'}))
    manufacturing_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    expiry_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    quantity_received = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'placeholder': 'e.g. 500'}))
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.all(), required=False, empty_label="Select Supplier (Optional)")
    reference = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'placeholder': 'Invoice #, PO Number, etc.'}))

    def clean(self):
        cleaned_data = super().clean()
        mfg_date = cleaned_data.get("manufacturing_date")
        exp_date = cleaned_data.get("expiry_date")
        
        if mfg_date and exp_date and mfg_date >= exp_date:
            raise forms.ValidationError("Expiry date must be after manufacturing date.")
        return cleaned_data


class StockOutForm(TailwindFormMixin, forms.Form):
    """
    Form to record Stock-Out. Supports FEFO (auto-deducting oldest expiring batches)
    or selecting a specific batch.
    """
    OUT_METHOD_CHOICES = (
        ('FEFO', 'First-Expired, First-Out (Auto FEFO)'),
        ('BATCH', 'Select Specific Batch Manually'),
    )
    drug = forms.ModelChoiceField(queryset=Drug.objects.all(), empty_label="Select Drug", required=False)
    batch = forms.ModelChoiceField(queryset=Batch.objects.none(), required=False, empty_label="Select Batch (Choose drug first)")
    method = forms.ChoiceField(choices=OUT_METHOD_CHOICES, widget=forms.RadioSelect(attrs={'class': 'inline-flex mr-4'}))
    quantity = forms.IntegerField(min_value=1, widget=forms.NumberInput(attrs={'placeholder': 'Quantity to distribute'}))
    reference = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={'placeholder': 'e.g. Dispensed to Ward B, Patient X'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamic Batch queryset population based on selected drug
        if 'drug' in self.data:
            try:
                drug_id = int(self.data.get('drug'))
                self.fields['batch'].queryset = Batch.objects.filter(drug_id=drug_id, quantity_remaining__gt=0).order_by('expiry_date')
            except (ValueError, TypeError):
                pass
        elif self.initial.get('drug'):
            drug_id = self.initial.get('drug').id
            self.fields['batch'].queryset = Batch.objects.filter(drug_id=drug_id, quantity_remaining__gt=0).order_by('expiry_date')
        else:
            self.fields['batch'].queryset = Batch.objects.filter(quantity_remaining__gt=0).order_by('expiry_date')

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        drug = cleaned_data.get('drug')
        batch = cleaned_data.get('batch')
        quantity = cleaned_data.get('quantity')

        if method == 'FEFO' and not drug:
            self.add_error('drug', 'Please select a drug for FEFO auto-distribution.')
        elif method == 'BATCH' and not batch:
            self.add_error('batch', 'Please select a specific batch.')

        if quantity:
            if method == 'FEFO' and drug:
                total_stock = drug.total_stock
                if total_stock < quantity:
                    raise forms.ValidationError(f"Insufficient stock. Requested: {quantity}, Available: {total_stock} units.")
            elif method == 'BATCH' and batch:
                if batch.quantity_remaining < quantity:
                    raise forms.ValidationError(f"Insufficient stock in Batch {batch.batch_number}. Requested: {quantity}, Available: {batch.quantity_remaining} units.")

        return cleaned_data


class CustomUserForm(TailwindFormMixin, forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Leave blank to keep current password'}),
        required=False,
    )

    class Meta:
        model = CustomUser
        fields = ['username', 'first_name', 'last_name', 'email', 'phone', 'role', 'password']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Enter unique username'}),
            'first_name': forms.TextInput(attrs={'placeholder': 'First Name'}),
            'last_name': forms.TextInput(attrs={'placeholder': 'Last Name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'user@rxstock.com'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Phone Number'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If this is a new user, password is required
        if not self.instance.pk:
            self.fields['password'].required = True
            self.fields['password'].widget.attrs['placeholder'] = '••••••••'

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password')
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class BulkUploadForm(TailwindFormMixin, forms.Form):
    file = forms.FileField(
        label="Select File",
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        if uploaded_file:
            name = uploaded_file.name.lower()
            if not (name.endswith('.csv') or name.endswith('.xlsx')):
                raise forms.ValidationError("Unsupported file extension. Only .csv and .xlsx files are allowed.")
        return uploaded_file

