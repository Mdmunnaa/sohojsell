"""
"সব ডাটা নামান" — দোকানের সব তথ্য এক Excel ফাইলে, আলাদা শিটে (প্রোডাক্ট থেকে খরচ পর্যন্ত)।

রিপোর্টের Excel (store/reports.py) একটা সময়ের হিসাব; এটা পুরো দোকানের কপি — চলে যেতে চাইলে বা নিজের কাছে
ব্যাকআপ রাখতে। শুধু মালিক নামাতে পারেন, মেয়াদ শেষ হয়ে ড্যাশবোর্ড লক থাকলেও (subscription_middleware)।
"""
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

MONEY = '#,##0.00'


def _when(value):
    if not value:
        return ''
    if hasattr(value, 'tzinfo'):
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
    return value.isoformat()


def _num(value):
    return float(value) if isinstance(value, Decimal) else value


class _Book:
    """openpyxl-এর write-only বই — হাজার হাজার অর্ডারেও মেমরি কম লাগে।"""

    def __init__(self):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        self.wb = Workbook(write_only=True)
        self.head_font = Font(bold=True, color='FFFFFF')
        self.head_fill = PatternFill('solid', fgColor='0F172A')
        self.counts = {}

    def sheet(self, title, headers, widths, rows, money=()):
        from openpyxl.cell import WriteOnlyCell
        from openpyxl.utils import get_column_letter
        ws = self.wb.create_sheet(title)
        for index, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(index)].width = width
        ws.freeze_panes = 'A2'
        head = []
        for text in headers:
            cell = WriteOnlyCell(ws, value=text)
            cell.font, cell.fill = self.head_font, self.head_fill
            head.append(cell)
        ws.append(head)
        n = 0
        money = set(money)
        for row in rows:
            out = []
            for index, value in enumerate(row, start=1):
                value = _num(value)
                if index in money and value not in (None, ''):
                    cell = WriteOnlyCell(ws, value=value)
                    cell.number_format = MONEY
                    out.append(cell)
                else:
                    out.append(value)
            ws.append(out)
            n += 1
        self.counts[title] = n


def build_full_export(shop, absolute=lambda url: url):
    from . import reports
    from .models import (Customer, Expense, Order, OrderItem, Product, ProductVariant, Purchase, PurchaseItem,
                         SalePayment, SaleReturn, Supplier, SupplierPayment)
    book = _Book()
    info = book.wb.create_sheet('তথ্য')          # শেষে ভরা হয় (কোন শিটে কত সারি), কিন্তু প্রথমে থাকে

    def image(product):
        try:
            return absolute(product.image.url) if product.image else ''
        except ValueError:
            return ''

    products = Product.objects.filter(shop=shop).select_related('category').order_by('id')
    book.sheet('প্রোডাক্ট',
               ['আইডি', 'নাম', 'ক্যাটাগরি', 'দাম', 'আগের দাম', 'কেনা দাম', 'স্টক', 'বারকোড', 'চালু', 'ছবির লিংক',
                'বিবরণ', 'যোগ হয়েছে'],
               [8, 34, 18, 12, 12, 12, 8, 18, 7, 40, 50, 17],
               ([p.id, p.name, p.category.name if p.category else '', p.price, p.compare_price, p.cost_price,
                 p.stock_quantity, p.barcode or '', 'হ্যাঁ' if p.is_active else 'না', image(p), p.description or '',
                 _when(p.created_at)] for p in products.iterator(chunk_size=500)),
               money=(4, 5, 6))
    book.sheet('সাইজ-রং',
               ['প্রোডাক্ট আইডি', 'প্রোডাক্ট', 'সাইজ / রং', 'দাম', 'স্টক', 'বারকোড'],
               [12, 34, 20, 12, 8, 18],
               ([v.product_id, v.product.name, v.name, v.price, v.stock_quantity, v.barcode or '']
                for v in ProductVariant.objects.filter(product__shop=shop).select_related('product')
                .order_by('product_id', 'position', 'id').iterator(chunk_size=500)),
               money=(4,))
    customers = (Customer.objects.filter(shop=shop).annotate(n_orders=Count('orders', distinct=True)).order_by('id'))
    book.sheet('কাস্টমার',
               ['আইডি', 'নাম', 'মোবাইল', 'ঠিকানা', 'অর্ডার', 'ব্লক করা', 'বাকি দেওয়ার কথা', 'বাকির নোট', 'যোগ হয়েছে'],
               [8, 26, 15, 40, 8, 9, 14, 30, 17],
               ([c.id, c.name, c.phone, c.address, c.n_orders, 'হ্যাঁ' if c.is_blocked else '', _when(c.due_promise),
                 c.due_note or '', _when(c.created_at)] for c in customers.iterator(chunk_size=500)))
    orders = Order.objects.filter(shop=shop).select_related('customer').order_by('id')
    book.sheet('অর্ডার',
               ['অর্ডার নং', 'তারিখ', 'কাস্টমার', 'মোবাইল', 'ঠিকানা', 'কোথা থেকে', 'অবস্থা', 'পেমেন্ট', 'ছাড়',
                'ডেলিভারি চার্জ', 'VAT', 'মোট', 'পরিশোধিত', 'বাকি', 'কুরিয়ার', 'ট্র্যাকিং', 'কুপন', 'নোট'],
               [11, 17, 24, 15, 36, 14, 14, 12, 10, 12, 10, 12, 12, 12, 12, 18, 12, 30],
               ([f'ORD-{o.id}', _when(o.created_at), o.customer.name, o.customer.phone, o.customer.address,
                 reports.CHANNEL_LABELS.get(o.source, o.source), reports.STATUS_LABELS.get(o.status, (o.status,))[0],
                 o.payment_method or '', o.discount, o.delivery_charge, o.vat_amount, o.total_amount, o.advance_paid,
                 o.due_amount, o.courier_partner or '', o.steadfast_tracking_code or '', o.coupon_code or '',
                 o.note or ''] for o in orders.iterator(chunk_size=500)),
               money=(9, 10, 11, 12, 13, 14))
    book.sheet('অর্ডারের পণ্য',
               ['অর্ডার নং', 'প্রোডাক্ট', 'সাইজ / রং', 'পরিমাণ', 'দাম', 'কেনা দাম', 'মোট'],
               [11, 34, 18, 8, 12, 12, 12],
               ([f'ORD-{i.order_id}', i.product.name if i.product else '', i.variant_name or '', i.quantity, i.price,
                 i.cost_price, i.price * i.quantity]
                for i in OrderItem.objects.filter(order__shop=shop).select_related('product').order_by('order_id', 'id')
                .iterator(chunk_size=1000)),
               money=(5, 6, 7))
    book.sheet('টাকা আদায়',
               ['তারিখ', 'অর্ডার নং', 'ধরন', 'মাধ্যম', 'টাকা', 'রেফারেন্স'],
               [17, 11, 16, 12, 12, 20],
               ([_when(p.created_at), f'ORD-{p.order_id}' if p.order_id else '', p.get_kind_display(),
                 p.get_method_display(), p.amount, p.reference or '']
                for p in SalePayment.objects.filter(shop=shop).order_by('id').iterator(chunk_size=1000)),
               money=(5,))
    book.sheet('ফেরত',
               ['তারিখ', 'অর্ডার নং', 'পুরো ফেরত', 'ফেরতের মূল্য', 'টাকা ফেরত', 'মাধ্যম', 'কারণ'],
               [17, 11, 10, 12, 12, 12, 30],
               ([_when(r.created_at), f'ORD-{r.order_id}', 'হ্যাঁ' if r.full else 'আংশিক', r.value, r.refund,
                 r.get_refund_method_display() if r.refund_method else '', r.reason or '']
                for r in SaleReturn.objects.filter(shop=shop).order_by('id').iterator(chunk_size=1000)),
               money=(4, 5))
    book.sheet('সাপ্লায়ার',
               ['আইডি', 'নাম', 'মোবাইল', 'ঠিকানা', 'আগের বাকি', 'নোট', 'যোগ হয়েছে'],
               [8, 26, 15, 34, 12, 30, 17],
               ([s.id, s.name, s.phone, s.address, s.opening_due, s.note, _when(s.created_at)]
                for s in Supplier.objects.filter(shop=shop).order_by('id').iterator()),
               money=(5,))
    book.sheet('মাল কেনা',
               ['কেনা নং', 'তারিখ', 'সাপ্লায়ার', 'চালান', 'মোট', 'দেওয়া', 'বাকি', 'নোট'],
               [9, 12, 26, 14, 12, 12, 12, 30],
               ([p.id, _when(p.purchased_on), p.supplier.name if p.supplier else '', p.invoice_no, p.total_amount,
                 p.paid_amount, p.total_amount - p.paid_amount, p.note]
                for p in Purchase.objects.filter(shop=shop).select_related('supplier').order_by('id').iterator()),
               money=(5, 6, 7))
    book.sheet('কেনার পণ্য',
               ['কেনা নং', 'পণ্য', 'পরিমাণ', 'একক দাম', 'মোট'],
               [9, 34, 8, 12, 12],
               ([i.purchase_id, i.name, i.quantity, i.unit_cost, i.unit_cost * i.quantity]
                for i in PurchaseItem.objects.filter(purchase__shop=shop).order_by('purchase_id', 'id').iterator()),
               money=(4, 5))
    book.sheet('সাপ্লায়ারকে টাকা',
               ['তারিখ', 'সাপ্লায়ার', 'কেনা নং', 'টাকা', 'মাধ্যম', 'নোট'],
               [12, 26, 9, 12, 12, 30],
               ([_when(p.paid_on), p.supplier.name if p.supplier else '', p.purchase_id or '', p.amount,
                 p.get_method_display() if p.method else '', p.note]
                for p in SupplierPayment.objects.filter(shop=shop).select_related('supplier').order_by('id').iterator()),
               money=(4,))
    book.sheet('খরচ',
               ['তারিখ', 'খাত', 'বিবরণ', 'মাধ্যম', 'টাকা'],
               [12, 22, 34, 12, 12],
               ([_when(e.spent_on), e.get_category_display(), e.title, e.get_method_display(), e.amount]
                for e in Expense.objects.filter(shop=shop).order_by('spent_on', 'id').iterator()),
               money=(5,))

    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    info.column_dimensions['A'].width = 28
    info.column_dimensions['B'].width = 44
    title = WriteOnlyCell(info, value=f'{shop.name} — সব তথ্য')
    title.font = Font(bold=True, size=14)
    info.append([title])
    info.append(['নামানো হয়েছে', timezone.localtime().strftime('%Y-%m-%d %H:%M')])
    info.append(['দোকান', f'{shop.name} ({shop.slug})'])
    info.append(['কোথা থেকে', 'SellPunch — এডুমি (Edumi)-এর একটি পণ্য'])
    info.append([])
    head = WriteOnlyCell(info, value='কোন শিটে কত সারি')
    head.font = Font(bold=True)
    info.append([head])
    for name, n in book.counts.items():
        info.append([name, n])
    info.append([])
    info.append(['ছবি', 'প্রোডাক্টের ছবি "প্রোডাক্ট" শিটের লিংকে — লিংক খুলে নামানো যায়'])
    return book.wb


def export_filename(shop):
    return f"sellpunch-{shop.slug or shop.pk}-{timezone.localdate():%Y-%m-%d}.xlsx"
