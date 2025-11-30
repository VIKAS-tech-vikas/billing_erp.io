from django import forms
from .models import Bill, BillItem

class BillForm(forms.ModelForm):
    class Meta:
        model = Bill
        fields = ['bill_no', 'customer_name', 'packing_charge']

class BillItemForm(forms.ModelForm):
    class Meta:
        model = BillItem
        fields = ['code', 'description', 'quantity', 'rate']
