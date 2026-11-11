"""
কাস্টমারের বাকির খাতা।

বাকি = দোকানের (POS) বিক্রিতে যত টাকা এখনো পাওয়া যায়নি (Order.total_amount − advance_paid)।
আদায় হয় store/pos.py-এর collect_due দিয়ে (পুরনো বিল আগে শোধ হয়)। এখানে: কার কত বাকি, কত দিনের,
প্রতিজনের খাতা, তাগাদা SMS (হাতে বা নিজে থেকে এত দিন পর পর)।
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Max, Min, Sum
from django.utils import timezone

from .models import Customer, Order, SalePayment, Shop

ZERO = Decimal('0')
NOT_COUNTED = ('Returned', 'Cancelled')
WALK_IN_PHONE = '00000000000'
REMINDER_GAP_DAYS = 1          # একই কাস্টমারকে দিনে একবারের বেশি তাগাদা না
AUTO_REMINDER_CHOICES = [(0, 'বন্ধ'), (7, '৭ দিন পর পর'), (15, '১৫ দিন পর পর'), (30, '৩০ দিন পর পর')]


class DueError(ValueError):
    """সেলারকে দেখানোর মতো বাংলা বার্তা।"""


def _due_orders(shop):
    return (Order.objects.filter(shop=shop, source='pos', advance_paid__lt=F('total_amount'))
            .exclude(status__in=NOT_COUNTED).exclude(customer__phone=WALK_IN_PHONE))


def rows(shop):
    """ফোন নম্বর ধরে: নাম, মোট বাকি, কয়টা বিল, সবচেয়ে পুরনোটা কত দিনের, শেষ আদায়, প্রতিশ্রুতি।"""
    today = timezone.localdate()
    grouped = (_due_orders(shop).values('customer__phone')
               .annotate(due=Sum(F('total_amount') - F('advance_paid')), bills=Count('id'),
                         oldest=Min('created_at'), newest=Max('created_at')).order_by('-due'))
    phones = [g['customer__phone'] for g in grouped]
    people = {}
    for c in Customer.objects.filter(shop=shop, phone__in=phones).order_by('id'):
        people[c.phone] = c          # একই নম্বরে একাধিক থাকলে শেষেরটা (সবচেয়ে নতুন নাম)
    last_paid = dict(SalePayment.objects.filter(shop=shop, kind=SalePayment.DUE_COLLECTION,
                                                order__customer__phone__in=phones)
                     .values_list('order__customer__phone').annotate(t=Max('created_at')))
    result = []
    for g in grouped:
        phone = g['customer__phone']
        customer = people.get(phone)
        oldest = timezone.localtime(g['oldest']).date()
        days = (today - oldest).days
        result.append({
            'phone': phone, 'name': customer.name if customer else '', 'customer': customer,
            'due': g['due'], 'bills': g['bills'], 'oldest': oldest, 'days': days,
            'age': 'old' if days >= 30 else 'mid' if days >= 7 else 'new',
            'last_paid': last_paid.get(phone), 'promise': customer.due_promise if customer else None,
            'promise_passed': bool(customer and customer.due_promise and customer.due_promise < today),
            'note': customer.due_note if customer else '',
            'reminded_at': customer.due_reminded_at if customer else None,
        })
    return result


def summary(shop, due_rows=None):
    due_rows = rows(shop) if due_rows is None else due_rows
    total = sum((r['due'] for r in due_rows), ZERO)
    old = sum((r['due'] for r in due_rows if r['age'] == 'old'), ZERO)
    month_start = timezone.localdate().replace(day=1)
    collected = (SalePayment.objects.filter(shop=shop, kind=SalePayment.DUE_COLLECTION, created_at__date__gte=month_start)
                 .aggregate(t=Sum('amount'))['t'] or ZERO)
    return {'total': total, 'people': len(due_rows), 'old': old,
            'old_people': sum(1 for r in due_rows if r['age'] == 'old'), 'collected_month': collected,
            'promise_passed': sum(1 for r in due_rows if r['promise_passed'])}


def ledger(shop, phone):
    """একজনের খাতা: বাকি থাকা বিল আর আদায়ের ইতিহাস, নতুনটা উপরে।"""
    customers = list(Customer.objects.filter(shop=shop, phone=phone).order_by('-id'))
    if not customers:
        return None
    ids = [c.id for c in customers]
    bills = list(Order.objects.filter(shop=shop, source='pos', customer_id__in=ids).exclude(status__in=NOT_COUNTED)
                 .order_by('-created_at'))
    for bill in bills:
        bill.due = max(bill.total_amount - bill.advance_paid, ZERO)
    payments = list(SalePayment.objects.filter(shop=shop, kind=SalePayment.DUE_COLLECTION, order__customer_id__in=ids)
                    .select_related('order', 'received_by').order_by('-created_at'))
    due = sum((b.due for b in bills), ZERO)
    return {'customer': customers[0], 'phone': phone, 'bills': bills, 'due_bills': [b for b in bills if b.due > 0],
            'payments': payments, 'due': due, 'bought': sum((b.total_amount for b in bills), ZERO),
            'paid_total': sum((p.amount for p in payments), ZERO)}


def set_promise(shop, phone, promise, note):
    from datetime import date
    customers = Customer.objects.filter(shop=shop, phone=phone)
    if not customers.exists():
        raise DueError('কাস্টমার পাওয়া যায়নি।')
    day = None
    if promise:
        try:
            day = date.fromisoformat(str(promise).strip())
        except ValueError:
            raise DueError('তারিখটা ঠিকমতো দিন।')
    customers.update(due_promise=day, due_note=' '.join(str(note or '').split())[:200])


# ---------------------------------------------------------------- তাগাদা SMS
def reminder_pairs(shop, phones=None, *, skip_recent=True, due_rows=None):
    """কাকে কী লেখা যাবে: [(phone, text, row), ...]। আজ তাগাদা পাওয়াদের বাদ (skip_recent)।"""
    due_rows = rows(shop) if due_rows is None else due_rows
    cutoff = timezone.now() - timedelta(days=REMINDER_GAP_DAYS)
    wanted = set(phones) if phones is not None else None
    pairs = []
    from . import sms
    for r in due_rows:
        if wanted is not None and r['phone'] not in wanted:
            continue
        if skip_recent and r['reminded_at'] and r['reminded_at'] > cutoff:
            continue
        pairs.append((r['phone'], sms.due_reminder_text(shop, r['name'], r['due']), r))
    return pairs


def send_reminders(shop, user, phones=None, *, skip_recent=True):
    """হাতে তাগাদা: phones=None হলে সবাইকে। ফেরত: SmsResult (sms.describe দিয়ে বার্তা)।"""
    from . import sms
    if not shop.is_sms_active:
        raise DueError('SMS প্যানেলে "কাস্টমারকে অটো SMS" বন্ধ আছে — আগে ওটা চালু করুন।')
    pairs = reminder_pairs(shop, phones, skip_recent=skip_recent)
    if not pairs:
        raise DueError('তাগাদা পাঠানোর মতো কেউ নেই (আজ যাদের পাঠানো হয়েছে, তারা বাদ)।')
    result = sms.send_each(shop, [(p, t) for p, t, _r in pairs],
                           'বাকির তাগাদা' if phones is None else f'বাকির তাগাদা · {pairs[0][0]}', user=user)
    if result.ok:
        Customer.objects.filter(shop=shop, phone__in=[p for p, _t, _r in pairs]).update(due_reminded_at=timezone.now())
    return result


def run_auto_reminders(now=None):
    """
    নিজে থেকে তাগাদা (ম্যানেজমেন্ট কমান্ড / cron থেকে দিনে একবার): যেসব দোকানে চালু, সেখানে
    যাদের বাকি আছে আর শেষ তাগাদার পর এত দিন পার হয়েছে, তাদের SMS। ফেরত: {shop_id: পাঠানো সংখ্যা}।
    """
    now = now or timezone.now()
    sent = {}
    for shop in Shop.objects.filter(due_reminder_days__gt=0, is_sms_active=True, sms_balance__gt=0, is_demo=False):
        cutoff = now - timedelta(days=shop.due_reminder_days)
        due_rows = [r for r in rows(shop) if not r['reminded_at'] or r['reminded_at'] <= cutoff]
        pairs = reminder_pairs(shop, [r['phone'] for r in due_rows], skip_recent=False, due_rows=due_rows)
        if not pairs:
            continue
        from . import sms
        result = sms.send_each(shop, [(p, t) for p, t, _r in pairs], 'বাকির তাগাদা (অটো)', kind='auto')
        if result.ok:
            Customer.objects.filter(shop=shop, phone__in=[p for p, _t, _r in pairs]).update(due_reminded_at=now)
            sent[shop.id] = result.delivered
    return sent
