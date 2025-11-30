from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from django.db.models import Sum, Q, F
from decimal import Decimal
import json
from django.utils.dateparse import parse_date
from django.db import IntegrityError, transaction
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Customer, Bill, BillItem, Payment, BillReturn

# ---------------------------------------
# Create new bill
# ---------------------------------------
@login_required
def create_bill(request):
    customers = Customer.objects.all().order_by('name')

    last_bill = Bill.objects.order_by('-bill_no').first()
    next_bill_no = 1 if not last_bill else last_bill.bill_no + 1

    # 🔥 NEW — Default date (last bill wala agar exist kare, otherwise today)
    last_bill_obj = Bill.objects.order_by('-date').first()
    default_date = last_bill_obj.date if last_bill_obj else timezone.now().date()

    if request.method == 'POST':
        customer_name = request.POST.get('customer_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        bill_date = request.POST.get('date')

        # 🚫 Future date block
        if bill_date > str(timezone.now().date()):
            messages.error(request, "🚫 Future date not allowed.")
            return redirect("create_bill")

        selected_customer = Customer.objects.filter(name=customer_name).first()
        final_customer_name = selected_customer.name if selected_customer else customer_name

        bill = Bill.objects.create(
            customer=selected_customer,
            bill_no=next_bill_no,
            customer_name=final_customer_name,
            phone=phone,
            date=bill_date,   # 👍 date save
        )
        return redirect('add_items', bill_id=bill.id)

    return render(request, 'create_bill.html', 
 {
        'customers': customers,
        'next_bill_no': next_bill_no,
        'default_date': default_date,  # 🔥 Ye line bhoolna mat
    })

# ---------------------------------------
# Add items to bill
# ---------------------------------------
@login_required
def add_items(request, bill_id):
    bill = Bill.objects.get(id=bill_id)

    if request.method == "GET":
        items = BillItem.objects.filter(bill=bill)
        return render(request, "add_items.html", {"bill": bill, "items": items})

    if request.method == "POST" and request.headers.get("Content-Type") == "application/json":
        data = json.loads(request.body.decode("utf-8"))

        items = data.get("items", [])
        packing_qty = data.get("packing_qty", 0)
        packing_rate = data.get("packing_rate", 0)
        packing_reason = data.get("packing_reason", "").strip()
        extra_reason = data.get("extra_reason", "").strip()
        extra_amount = data.get("extra_amount", 0)

        BillItem.objects.filter(bill=bill).delete()
        for item in items:
            BillItem.objects.create(
                bill=bill,
                description=item["description"],
                quantity=item["quantity"],
                rate=item["rate"],
                total=item["total"],
            )

        subtotal = sum(i["total"] for i in items)
        packing_total = packing_qty * packing_rate
        final_total = subtotal + packing_total + extra_amount

        bill.subtotal = subtotal
        bill.packing_qty = packing_qty
        bill.packing_rate = packing_rate
        bill.packing_amount = packing_total
        bill.packing_reason = packing_reason if packing_reason else "Packing"
        bill.extra_reason = extra_reason
        bill.extra_amount = extra_amount
        bill.final_amount = final_total
        bill.save()

        return JsonResponse({"success": True, "bill_id": bill.id})

    return JsonResponse({"success": False})
@login_required
def customer_monthly_statement(request):
    customer_name = request.GET.get('customer_name', '').strip()
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')

    bills = []
    total_amount = Decimal('0')
    total_paid = Decimal('0')
    total_returns_all = Decimal('0')

    if customer_name or (start_date and end_date):
        bills_qs = Bill.objects.all()

        if customer_name:
            bills_qs = bills_qs.filter(customer_name__icontains=customer_name)

        if start_date and end_date:
            bills_qs = bills_qs.filter(date__range=[start_date, end_date])

        bills_qs = bills_qs.order_by("date")

        # Get all returns of these bills only once (fast query)
        returns_qs = BillReturn.objects.filter(bill__in=bills_qs)
        returns_dict = {}
        for r in returns_qs:
            returns_dict.setdefault(r.bill_id, []).append(r)

        for bill in bills_qs:
            try:
                bill.update_total()
            except:
                pass

            base_total = Decimal(str(bill.total_amount or 0))

            # Return total per bill
            bill_returns = returns_dict.get(bill.id, [])
            returns_total = sum((Decimal(str(r.amount)) for r in bill_returns), Decimal('0'))

            # Positive paid only
            paid = bill.payments.filter(amount__gt=0).aggregate(sum=Sum('amount'))['sum'] or Decimal('0')

            # Real remaining
            remaining = base_total - paid - returns_total
            if remaining < 0:
                remaining = Decimal('0')

            # Assign display values
            bill.total_display = base_total
            bill.returns_total = returns_total
            bill.positive_paid = paid
            bill.remaining_display = remaining

            bills.append(bill)

            # Summary totals
            total_amount += base_total
            total_paid += paid
            total_returns_all += returns_total

    # Final remaining summary (important)
    total_remaining = total_amount - total_paid - total_returns_all
    if total_remaining < 0:
        total_remaining = Decimal('0')

    return render(request, 'customer_monthly_statement.html', {
        'bills': bills,
        'customer_name': customer_name,
        'start_date': start_date,
        'end_date': end_date,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_returns': total_returns_all,
        'total_remaining': total_remaining
    })
def index(request):
    return render(request, 'index.html')
# ---------------------------------------
# Customer statement with date filter
# ---------------------------------------
@login_required
def customer_statement(request):
    customer_name = request.GET.get('customer_name', '').strip()
    date_from = request.GET.get('from', '').strip()
    date_to = request.GET.get('to', '').strip()

    qs = Bill.objects.all()

    if customer_name:
        qs = qs.filter(customer_name__icontains=customer_name)

    if date_from:
        qs = qs.filter(date__gte=date_from)

    if date_to:
        qs = qs.filter(date__lte=date_to)

    qs = qs.order_by('-date', '-bill_no')

    bills = []
    for b in qs:
        total = Decimal(str(b.total_amount or 0))
        positive_paid = b.payments.filter(amount__gt=0).aggregate(sum=Sum("amount"))['sum'] or Decimal('0')
        returns_total = abs(b.payments.filter(amount__lt=0).aggregate(sum=Sum("amount"))['sum'] or Decimal('0'))
        remaining = max(total - positive_paid - returns_total, 0)

        b.returns_total = returns_total
        b.positive_paid = positive_paid
        b.remaining_amount = remaining

        bills.append(b)

    return render(request, 'customer_statement.html', 
 {
        'bills': bills,
        'search_name': customer_name,
        'date_from': date_from,
        'date_to': date_to,
    })


# ---------------------------------------
# Bill Detail Page
# ---------------------------------------
@login_required
def bill_detail(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)
    payments = bill.payments.all().order_by('-date')
    returns = BillReturn.objects.filter(bill=bill).order_by('-date')
    return render(request, 'bill_detail.html', {'bill': bill, 'payments': payments, 'returns': returns})


# ---------------------------------------
# View Customers
# ---------------------------------------
@login_required
def view_customers(request):
    q = request.GET.get('q', '').strip()
    customers = Customer.objects.all()

    if q:
        customers = customers.filter(name__icontains=q) | customers.filter(phone__icontains=q)

    customer_data = []
    for c in customers:
        bills = Bill.objects.filter(customer=c)
        total_amount = sum((b.total_amount or Decimal('0')) for b in bills)
        total_paid = sum((b.paid_amount or Decimal('0')) for b in bills)
        customer_data.append({
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "address": c.address,
            "total_bills": bills.count(),
            "total_amount": total_amount,
            "total_paid": total_paid,
            "total_remaining": total_amount - total_paid,
        })

    return render(request, "view_customers.html", {"customers": customer_data, "q": q})



# ---------------------------------------
# Customer Detail
# ---------------------------------------
@login_required
def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)
    bills_qs = Bill.objects.filter(customer=customer).order_by('-date', '-bill_no')

    bills = []
    total_amt = total_paid = total_return = total_rem = Decimal('0.00')

    for b in bills_qs:
        total = Decimal(str(b.total_amount or 0))

        positive_paid = b.payments.filter(amount__gt=0).aggregate(sum=Sum("amount"))['sum'] or Decimal('0')
        returns_total = abs(b.payments.filter(amount__lt=0).aggregate(sum=Sum("amount"))['sum'] or Decimal('0'))

        remaining = max(total - positive_paid - returns_total, 0)


        b.amount_display = total
        b.paid_display = positive_paid
        b.return_display = returns_total        # 🔥 सही variable
        b.remaining_display = remaining

        bills.append(b)
        total_amt += total
        total_paid += positive_paid
        total_return += returns_total
        total_rem += remaining

    return render(request, "customer_detail.html", {
        "customer": customer,
        "bills": bills,
        "total_amount": total_amt,
        "total_paid": total_paid,
        "total_return": total_return,     # 🔥 summary में भी भेजा
        "total_remaining": total_rem,
    })

# ---------------------------------------
# Return Bill
# ---------------------------------------
@login_required
@require_POST
def return_bill(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)

    try:
        amount = Decimal(str(request.POST.get("amount") or 0))
    except:
        amount = Decimal("0")

    note = (request.POST.get("note") or "").strip() or "Return"

    if amount <= 0:
        messages.error(request, "Invalid return amount")
        return redirect("customer_detail", customer_id=bill.customer.id)

    with transaction.atomic():
        # Save return record
        BillReturn.objects.create(
            bill=bill,
            amount=amount,
            note=note,
            date=timezone.now()
        )

        # Negative payment entry
        Payment.objects.create(
            bill=bill,
            amount=-amount,
            note=f"Return: {note}",
            date=timezone.now()
        )

        # Update paid_total ONLY with positive payments
        positive_paid = bill.payments.filter(amount__gt=0).aggregate(sum=Sum('amount'))['sum'] or Decimal('0')
        bill.paid_amount = positive_paid
        bill.save(update_fields=['paid_amount'])

        if bill.customer:
            bill.customer.refresh_totals()

    messages.success(request, f"₹{amount} returned for Bill #{bill.bill_no}")
    return redirect("customer_detail", customer_id=bill.customer.id)
# ---------------------------------------
# Delete Bill
# ---------------------------------------
@login_required
def delete_bill(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)
    customer_id = bill.customer.id if bill.customer else None
    bill.delete()

    messages.success(request, f"Bill #{bill.bill_no} deleted successfully!")
    return redirect(f"/customer/{customer_id}/") if customer_id else redirect("home")


# ---------------------------------------
# Mark Single Bill Paid
# ---------------------------------------
@login_required
@require_POST
def mark_bill_paid(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)

    total = Decimal(str(bill.total_amount or 0))
    paid = Decimal(str(bill.paid_amount or 0))
    remaining = total - paid

    if remaining <= 0:
        messages.info(request, f"Bill #{bill.bill_no} is already fully paid.")
        return redirect(f"/customer/{bill.customer.id}/")

    with transaction.atomic():
        Payment.objects.create(
            bill=bill, amount=remaining, note="Marked paid", date=timezone.now()
        )

        bill.paid_amount = total
        bill.is_paid = True
        bill.paid_date = timezone.now()
        bill.save(update_fields=['paid_amount', 'is_paid', 'paid_date'])

        if bill.customer:
            bill.customer.refresh_totals()

    messages.success(request, f"Bill #{bill.bill_no} marked as paid (₹{remaining}).")
    return redirect(f"/customer/{bill.customer.id}/")


# ---------------------------------------
# Login / Logout
# ---------------------------------------
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("home")
        messages.error(request, "Invalid username or password")
        return redirect("login")
    return render(request, "login.html")


@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


# ---------------------------------------
# Dashboard
# ---------------------------------------
@login_required
def home(request):
  return render(request, 'index.html')


@login_required
def add_items_generate(request, bill_id):
    return redirect('generate_bill', bill_id=bill_id)

@login_required
def generate_bill(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)
    items = BillItem.objects.filter(bill=bill)

    items_total = sum((item.total or Decimal('0.00')) for item in items)
    packing_qty = int(bill.packing_qty or 0)
    packing_rate = Decimal(str(bill.packing_rate or 0))
    packing_reason = bill.packing_reason or "Packing"
    packing_total = packing_qty * packing_rate

    extra_reason = bill.extra_reason or ""
    extra_amount = Decimal(str(bill.extra_amount or 0))

    final_total = items_total + packing_total + extra_amount

    total_paid = sum((p.amount or Decimal('0.00')) for p in bill.payments.all())
    bill.total_amount = final_total
    bill.paid_amount = min(total_paid, final_total)
    bill.save(update_fields=['total_amount', 'paid_amount'])

    remaining = max(final_total - bill.paid_amount, Decimal('0.00'))

    return render(request, 'generate_bill.html', {
        'bill': bill,
        'items': items,
        'items_total': items_total,

        # 🔥 yeh 4 values packing reason line ke liye required hain
        'packing_qty': packing_qty,
        'packing_rate': packing_rate,
        'packing_total': packing_total,
        'packing_reason': packing_reason,

        # 🔥 Extra charges agar future me use ho
        'extra_reason': extra_reason,
        'extra_amount': extra_amount,

        'final_total': final_total,
        'remaining': remaining,
    })


@login_required
def add_customer(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()

        if not name:
            messages.error(request, "Customer name is required.")
            return redirect('add_customer')

        try:
            Customer.objects.create(name=name, phone=phone, address=address)
            messages.success(request, f"Customer '{name}' added successfully!")
            return redirect('create_bill')
        except IntegrityError:
            messages.warning(request, f"Customer '{name}' already exists!")
            return redirect('add_customer')

    return render(request, 'add_customer.html')   # ✔ सिर्फ इतना रखें


@login_required
def edit_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == 'POST':
        customer.name = request.POST.get('name', '').strip()
        customer.phone = request.POST.get('phone', '').strip()
        customer.address = request.POST.get('address', '').strip()
        customer.save()

        messages.success(request, f"Customer '{customer.name}' updated successfully!")
        return redirect('view_customers')

    return render(request, 'edit_customer.html', {'customer': customer})

@login_required
def delete_customer(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id)

    if request.method == "POST":
        customer_name = customer.name
        customer.delete()
        messages.success(request, f"Customer '{customer_name}' deleted successfully!")
        return redirect("view_customers")

    return render(request, "delete_customer.html", {"customer": customer})

@login_required
def two_invoices_view(request, customer_id):
    """
    Customer के दो invoice एक ही page पर show करने के लिए:
    Left → Latest Bill details
    Right → Return (RK) Records
    """
    from decimal import Decimal
    customer = get_object_or_404(Customer, id=customer_id)

    # Latest Bill (Left side)
    bill = Bill.objects.filter(customer=customer).order_by('-date', '-id').first()
    items = BillItem.objects.filter(bill=bill) if bill else []

    items_total = sum((item.total or Decimal('0')) for item in items)
    packing_total = (bill.packing_qty or 0) * (bill.packing_rate or 0) if bill else 0
    extra_amount = Decimal(str(bill.extra_amount or 0)) if bill else 0
    final_total = items_total + packing_total + extra_amount

    # RK (Return) Records (Right side)
    returns = BillReturn.objects.filter(bill__customer=customer).order_by('-date')
    rk_lines = [{"desc": f"Return - Bill #{r.bill.bill_no} ({r.note})", "amount": r.amount} for r in returns]
    rk_total = sum((r.amount for r in returns), Decimal('0'))

    context = {
        "customer": customer,
        "bill": bill,
        "items": items,
        "items_total": items_total,
        "packing_total": packing_total,
        "extra_amount": extra_amount,
        "final_total": final_total,
        "rk_lines": rk_lines,
        "rk_total": rk_total,
    }
    return render(request, "generate_bill_double.html", context)
@login_required
@require_POST
def pay_bill(request, bill_id):
    bill = get_object_or_404(Bill, id=bill_id)

    try:
        amount = Decimal(str(request.POST.get("amount") or 0))
    except:
        amount = Decimal("0")

    note = (request.POST.get("note") or "").strip()

    if amount <= 0:
        messages.error(request, "Invalid payment amount")
        return redirect("customer_detail", customer_id=bill.customer.id)

    # Overpayment block (remaining से ज्यादा nahi hone denge)
    remaining = (bill.total_amount or 0) - (bill.paid_amount or 0)
    if amount > remaining:
        messages.error(request, f"Payment can't exceed remaining balance (Remaining ₹{remaining})")
        return redirect("customer_detail", customer_id=bill.customer.id)

    with transaction.atomic():
        Payment.objects.create(
            bill=bill,
            amount=amount,
            note=note,
            date=timezone.now()
        )

        bill.paid_amount = (bill.paid_amount or 0) + amount
        bill.save(update_fields=["paid_amount"])

        # Refresh customer totals
        if bill.customer:
            bill.customer.refresh_totals()

    messages.success(request, f"₹{amount} received successfully for Bill #{bill.bill_no}")
    return redirect("customer_detail", customer_id=bill.customer.id)

