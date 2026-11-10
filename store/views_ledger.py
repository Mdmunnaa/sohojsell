"""কেনা, সাপ্লায়ার আর খরচের পেজ (হিসাব: store/ledger.py)।"""
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import ledger
from .dashboard import BN_MONTHS, bn_num
from .models import PAY_METHOD_CHOICES, Expense, Purchase, Supplier

LOGIN = '/accounts/login/'


def _month_start(day):
    return day.replace(day=1)


# ---------------------------------------------------------------- কেনা
@login_required(login_url=LOGIN)
def purchase_list(request):
    shop = request.user.shop
    today = timezone.localdate()
    purchases = Purchase.objects.filter(shop=shop).select_related('supplier').prefetch_related('items')
    q = request.GET.get('q', '').strip()
    if q:
        purchases = purchases.filter(Q(supplier__name__icontains=q) | Q(invoice_no__icontains=q) |
                                     Q(items__name__icontains=q)).distinct()
    page = Paginator(purchases, 25).get_page(request.GET.get('page'))
    return render(request, 'store/purchases.html', {
        'shop': shop, 'page_obj': page, 'q': q,
        'month': ledger.purchase_summary(shop, _month_start(today), today),
        'month_name': BN_MONTHS[today.month - 1],
        'has_any': Purchase.objects.filter(shop=shop).exists(),
    })


@login_required(login_url=LOGIN)
def purchase_new(request):
    shop = request.user.shop
    today = timezone.localdate()
    form = {'supplier': request.GET.get('supplier', ''), 'purchased_on': today.isoformat(), 'invoice_no': '',
            'paid': '', 'method': 'cash', 'note': '', 'new_supplier': '', 'new_phone': ''}
    rows = []
    if request.method == 'POST':
        post = request.POST
        form = {key: post.get(key, '').strip() for key in form}
        rows = [{'key': k, 'qty': q, 'cost': c} for k, q, c in zip(
            post.getlist('item_key[]'), post.getlist('item_qty[]'), post.getlist('item_cost[]')) if k]
        try:
            lines = ledger.lines_from_post(post)
            supplier = None
            if form['supplier'] == 'new':
                supplier = Supplier.objects.create(
                    shop=shop, **ledger.clean_supplier(shop, form['new_supplier'], form['new_phone']))
                form['supplier'] = str(supplier.id)          # ফর্ম ফিরে এলে আবার নতুন করে না বানায়
            elif form['supplier']:
                supplier = Supplier.objects.filter(shop=shop, pk=form['supplier']).first()
                if supplier is None:
                    raise ledger.LedgerError('সাপ্লায়ার পাওয়া যায়নি, আবার বেছে নিন।')
            purchase = ledger.create_purchase(
                shop, request.user, lines=lines, supplier=supplier, purchased_on=form['purchased_on'],
                invoice_no=form['invoice_no'], paid=form['paid'], method=form['method'], note=form['note'])
        except (ledger.LedgerError, ValueError) as exc:
            messages.error(request, str(exc) if isinstance(exc, ledger.LedgerError) else 'ফর্মের তথ্য ঠিক নেই।')
        else:
            text = f'কেনা জমা হয়েছে, স্টক বেড়েছে। মোট ৳{bn_num(f"{purchase.total_amount:,.0f}")}'
            if purchase.due_amount:
                text += f', বাকি ৳{bn_num(f"{purchase.due_amount:,.0f}")}'
            messages.success(request, text + '।')
            return redirect('purchase_detail', purchase.id)
    return render(request, 'store/purchase_new.html', {
        'shop': shop, 'form': form, 'today': today,
        'suppliers': Supplier.objects.filter(shop=shop),
        'methods': PAY_METHOD_CHOICES,
        'purchase_data': {'products': ledger.product_options(shop), 'rows': rows},
    })


@login_required(login_url=LOGIN)
def purchase_detail(request, purchase_id):
    purchase = get_object_or_404(Purchase.objects.select_related('supplier', 'created_by'), pk=purchase_id,
                                 shop=request.user.shop)
    return render(request, 'store/purchase_detail.html', {
        'shop': request.user.shop, 'purchase': purchase, 'items': list(purchase.items.all()),
        'payment': purchase.payments.first(),
    })


@login_required(login_url=LOGIN)
@require_POST
def purchase_delete(request, purchase_id):
    purchase = get_object_or_404(Purchase, pk=purchase_id, shop=request.user.shop)
    try:
        ledger.delete_purchase(request.user.shop, purchase)
    except ledger.LedgerError as exc:
        messages.error(request, str(exc))
        return redirect('purchase_detail', purchase_id)
    messages.success(request, 'কেনাটা মুছে ফেলা হয়েছে, স্টক আগের জায়গায় ফিরেছে।')
    return redirect('purchase_list')


# ---------------------------------------------------------------- সাপ্লায়ার
@login_required(login_url=LOGIN)
def supplier_list(request):
    shop = request.user.shop
    if request.method == 'POST':
        try:
            Supplier.objects.create(shop=shop, **ledger.clean_supplier(
                shop, request.POST.get('name'), request.POST.get('phone'), request.POST.get('address'),
                request.POST.get('note'), request.POST.get('opening_due')))
        except ledger.LedgerError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, 'সাপ্লায়ার যোগ হয়েছে।')
        return redirect('supplier_list')
    rows = ledger.supplier_rows(shop)
    q = request.GET.get('q', '').strip()
    if q:
        rows = [s for s in rows if q.lower() in s.name.lower() or q in s.phone]
    rows.sort(key=lambda s: (-s.due, s.name))
    return render(request, 'store/suppliers.html', {
        'shop': shop, 'suppliers': rows, 'q': q,
        'total_due': sum((s.due for s in rows if s.due > 0), ledger.ZERO),
        'due_count': sum(1 for s in rows if s.due > 0),
    })


@login_required(login_url=LOGIN)
def supplier_detail(request, supplier_id):
    shop = request.user.shop
    supplier = get_object_or_404(Supplier, pk=supplier_id, shop=shop)
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'pay':
                payment = ledger.pay_supplier(shop, request.user, supplier, request.POST.get('amount'),
                                              request.POST.get('method'), request.POST.get('paid_on'),
                                              request.POST.get('note'))
                messages.success(request, f'৳{bn_num(f"{payment.amount:,.0f}")} পরিশোধ লেখা হয়েছে।')
            elif action == 'edit':
                data = ledger.clean_supplier(shop, request.POST.get('name'), request.POST.get('phone'),
                                             request.POST.get('address'), request.POST.get('note'),
                                             request.POST.get('opening_due'), exclude_id=supplier.id)
                Supplier.objects.filter(pk=supplier.pk).update(**data)
                messages.success(request, 'সাপ্লায়ারের তথ্য আপডেট হয়েছে।')
            elif action == 'delete_payment':
                deleted, _ = supplier.payments.filter(pk=request.POST.get('payment_id'), purchase__isnull=True).delete()
                if deleted:
                    messages.success(request, 'পরিশোধের এন্ট্রিটা মুছে ফেলা হয়েছে।')
            elif action == 'delete':
                if supplier.purchases.exists() or supplier.payments.exists():
                    raise ledger.LedgerError('এই সাপ্লায়ারের কেনা বা পরিশোধের হিসাব আছে, তাই মোছা যাবে না।')
                supplier.delete()
                messages.success(request, 'সাপ্লায়ার মুছে ফেলা হয়েছে।')
                return redirect('supplier_list')
        except ledger.LedgerError as exc:
            messages.error(request, str(exc))
        return redirect('supplier_detail', supplier.id)
    entries, due = ledger.supplier_ledger(supplier)
    return render(request, 'store/supplier_detail.html', {
        'shop': shop, 'supplier': supplier, 'entries': entries, 'due': due,
        'bought': sum((e['plus'] for e in entries), ledger.ZERO),
        'paid': sum((e['minus'] for e in entries), ledger.ZERO),
        'methods': PAY_METHOD_CHOICES, 'today': timezone.localdate(),
    })


# ---------------------------------------------------------------- খরচ
def _month_from(value, today):
    """?m=2026-11 → সেই মাসের ১ তারিখ; ভুল বা ভবিষ্যৎ হলে এই মাস।"""
    try:
        year, month = (int(x) for x in str(value or '').split('-'))
        start = date(year, month, 1)
    except (ValueError, TypeError):
        return _month_start(today)
    return min(start, _month_start(today))


@login_required(login_url=LOGIN)
def expense_list(request):
    shop = request.user.shop
    today = timezone.localdate()
    if request.method == 'POST':
        try:
            expense = ledger.add_expense(
                shop, request.user, category=request.POST.get('category'), amount=request.POST.get('amount'),
                title=request.POST.get('title'), spent_on=request.POST.get('spent_on'),
                method=request.POST.get('method'))
        except ledger.LedgerError as exc:
            messages.error(request, str(exc))
            return redirect('expense_list')
        messages.success(request, f'খরচ লেখা হয়েছে: {expense.get_category_display()} '
                                  f'৳{bn_num(f"{expense.amount:,.0f}")}।')
        return redirect(f"{request.path}?m={expense.spent_on:%Y-%m}")

    start = _month_from(request.GET.get('m'), today)
    end = min((start + timedelta(days=32)).replace(day=1) - timedelta(days=1), today)
    prev_start = (start - timedelta(days=1)).replace(day=1)
    next_start = (start + timedelta(days=32)).replace(day=1)
    summary = ledger.expense_summary(shop, start, end)
    previous = ledger.expense_summary(shop, prev_start, start - timedelta(days=1))
    return render(request, 'store/expenses.html', {
        'shop': shop, 'today': today, 'summary': summary, 'previous_total': previous['total'],
        'month_label': f'{BN_MONTHS[start.month - 1]} {bn_num(start.year)}',
        'prev_month': f'{prev_start:%Y-%m}',
        'next_month': f'{next_start:%Y-%m}' if next_start <= today else '',
        'expenses': Expense.objects.filter(shop=shop, spent_on__gte=start, spent_on__lte=end)
                    .select_related('created_by'),
        'categories': Expense.CATEGORY_CHOICES, 'methods': PAY_METHOD_CHOICES,
        'is_current': start == _month_start(today),
    })


@login_required(login_url=LOGIN)
@require_POST
def expense_delete(request, expense_id):
    expense = get_object_or_404(Expense, pk=expense_id, shop=request.user.shop)
    month = f'{expense.spent_on:%Y-%m}'
    expense.delete()
    messages.success(request, 'খরচের এন্ট্রিটা মুছে ফেলা হয়েছে।')
    return redirect(f"/expenses/?m={month}")
