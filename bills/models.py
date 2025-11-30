from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.conf import settings


# 🧾 CUSTOMER MODEL
class Customer(models.Model):
    name = models.CharField(max_length=200, unique=True)
    phone = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"{self.name} ({self.phone})" if self.phone else self.name

    class Meta:
        ordering = ['name']

    def refresh_totals(self):
        bills = self.bill_set.all()
        total = sum((b.net_total or 0) for b in bills)
        paid = sum((b.paid_amount or 0) for b in bills)
        remaining = max(total - paid, 0)

        self.total_amount = total
        self.paid_amount = paid
        self.remaining_amount = remaining
        self.save(update_fields=['total_amount', 'paid_amount', 'remaining_amount'])


# 🧾 BILL MODEL
class Bill(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)

    date = models.DateField(default=timezone.now)
    bill_no = models.IntegerField(default=1)

    packing_qty = models.IntegerField(blank=True, null=True)
    packing_rate = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    packing_reason = models.CharField(max_length=255, blank=True, null=True)

    extra_reason = models.CharField(max_length=255, blank=True, null=True)
    extra_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    returned_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    is_paid = models.BooleanField(default=False)
    paid_date = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    def save(self, *args, **kwargs):
        # Auto bill no
        if not self.bill_no:
            last_bill = Bill.objects.order_by('-bill_no').first()
            self.bill_no = 1 if not last_bill else last_bill.bill_no + 1

        # Auto fill customer info
        if self.customer:
            self.customer_name = self.customer.name
            self.phone = self.customer.phone

        # Prevent None packing values
        if self.packing_qty is None:
            self.packing_qty = 0
        if self.packing_rate is None:
            self.packing_rate = Decimal('0.00')

        super().save(*args, **kwargs)

        # Refresh paid flag
        self._refresh_paid_flag()

        # Refresh customer totals
        if self.customer:
            self.customer.refresh_totals()

    # Bill Total = Items + Packing + Extra
    def update_total(self):
        items_total = sum((i.total or 0) for i in self.items.all())
        packing_total = (self.packing_qty or 0) * (self.packing_rate or 0)
        extra_total = self.extra_amount or 0

        self.total_amount = Decimal(items_total) + Decimal(packing_total) + Decimal(extra_total)
        self.save(update_fields=['total_amount'])

    # 🔥 Required Method — missing earlier
    def _refresh_paid_flag(self):
        fully_paid = self.paid_amount >= self.net_total > 0
        if fully_paid and not self.is_paid:
            self.is_paid = True
            self.paid_date = timezone.now()
            self.save(update_fields=['is_paid', 'paid_date'])
        elif not fully_paid and self.is_paid:
            self.is_paid = False
            self.paid_date = None
            self.save(update_fields=['is_paid', 'paid_date'])

    @property
    def net_total(self):
        return max((self.total_amount or 0) - (self.returned_amount or 0), 0)

    @property
    def remaining(self):
        return max(self.net_total - (self.paid_amount or 0), 0)

    class Meta:
        ordering = ['-date', '-bill_no']



# 🧾 BILL ITEM MODEL
class BillItem(models.Model):
    bill = models.ForeignKey(Bill, related_name='items', on_delete=models.CASCADE)
    description = models.TextField(blank=True)
    quantity = models.PositiveIntegerField(default=1)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    def save(self, *args, **kwargs):
        self.total = Decimal(self.quantity) * Decimal(self.rate)
        super().save(*args, **kwargs)
        self.bill.update_total()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.bill.update_total()


# 💰 PAYMENT MODEL
class Payment(models.Model):
    bill = models.ForeignKey(Bill, related_name='payments', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.now)
    note = models.CharField(max_length=200, blank=True, null=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_bill_paid_total()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.update_bill_paid_total()

    def update_bill_paid_total(self):
        total_paid = sum((p.amount or 0) for p in self.bill.payments.all())
        self.bill.paid_amount = max(total_paid, 0)
        self.bill.save(update_fields=['paid_amount'])
        self.bill._refresh_paid_flag()
        if self.bill.customer:
            self.bill.customer.refresh_totals()


# 💼 BILL RETURN MODEL
class BillReturn(models.Model):
    bill = models.ForeignKey(Bill, related_name='returns', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.TextField(blank=True, null=True)
    date = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        total_return = sum(r.amount for r in self.bill.returns.all())
        self.bill.returned_amount = max(total_return, 0)
        self.bill.save(update_fields=['returned_amount'])
        self.bill.update_total()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        total_return = sum(r.amount for r in self.bill.returns.all())
        self.bill.returned_amount = max(total_return, 0)
        self.bill.save(update_fields=['returned_amount'])
        self.bill.update_total()
