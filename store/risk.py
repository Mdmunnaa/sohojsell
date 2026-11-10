"""
ভুয়া অর্ডার ধরা: একটা ফোন নম্বর আগে কতগুলো অর্ডার নিয়েছে আর কতগুলো ফেরত/বাতিল করেছে।

নিজের দোকানের হিসাবের সাথে SellPunch-এর অন্য দোকানের মোট সংখ্যাও ধরা হয় (কোন দোকান সেটা দেখানো হয় না) —
নতুন কাস্টমার অন্য জায়গায় বারবার ফেরত দিয়ে থাকলে আগেই জানা যায়। দোকানের (POS) বিক্রি ধরা হয় না।
"""
from dataclasses import dataclass

from django.db.models import Count, Q

from .dashboard import bn_num
from .models import Customer, Order

FAILED = ('Returned', 'Cancelled')
WALK_IN_PHONE = '00000000000'


@dataclass
class Risk:
    phone: str = ''
    own_delivered: int = 0
    own_failed: int = 0
    own_active: int = 0
    other_delivered: int = 0
    other_failed: int = 0
    blocked: bool = False

    @property
    def delivered(self):
        return self.own_delivered + self.other_delivered

    @property
    def failed(self):
        return self.own_failed + self.other_failed

    @property
    def finished(self):
        return self.delivered + self.failed

    @property
    def success_rate(self):
        return round(self.delivered * 100 / self.finished) if self.finished else None

    @property
    def level(self):
        if self.blocked:
            return 'blocked'
        if not self.finished:
            return 'new'
        fail_rate = self.failed / self.finished
        if self.failed >= 2 and fail_rate >= 0.5:
            return 'risk'
        if self.failed >= 1 and fail_rate >= 0.25:
            return 'watch'
        return 'good'

    @property
    def label(self):
        level = self.level
        if level == 'blocked':
            return 'ব্লক করা'
        if level == 'new':
            return 'নতুন নম্বর'
        if level == 'good':
            return f'ভালো · {bn_num(self.success_rate)}% সফল'
        word = 'ঝুঁকি বেশি' if level == 'risk' else 'সাবধান'
        return f'{word} · {bn_num(self.finished)}টার {bn_num(self.failed)}টা ফেরত'

    @property
    def detail(self):
        parts = [f'আপনার দোকানে: ডেলিভারি {bn_num(self.own_delivered)}, ফেরত/বাতিল {bn_num(self.own_failed)}'
                 + (f', চলমান {bn_num(self.own_active)}' if self.own_active else '')]
        if self.other_delivered or self.other_failed:
            parts.append(f'অন্য দোকানে: ডেলিভারি {bn_num(self.other_delivered)}, '
                         f'ফেরত/বাতিল {bn_num(self.other_failed)}')
        if self.level == 'new':
            parts = ['এই নম্বরের আগের কোনো ডেলিভারি বা ফেরতের হিসাব নেই']
        return ' · '.join(parts)

    def as_dict(self):
        return {'level': self.level, 'label': self.label, 'detail': self.detail, 'blocked': self.blocked,
                'success_rate': self.success_rate, 'delivered': self.delivered, 'failed': self.failed}


def for_phones(shop, phones):
    """{phone: Risk} — এক পেজের সব অর্ডারের জন্য দুটো কোয়েরিতে।"""
    phones = {p for p in phones if p and p != WALK_IN_PHONE}
    result = {phone: Risk(phone=phone) for phone in phones}
    if not phones:
        return result
    rows = (Order.objects.filter(customer__phone__in=phones).exclude(source='pos')
            .values('customer__phone')
            .annotate(own_delivered=Count('id', filter=Q(shop=shop, status='Delivered')),
                      own_failed=Count('id', filter=Q(shop=shop, status__in=FAILED)),
                      own_active=Count('id', filter=Q(shop=shop) & ~Q(status__in=FAILED + ('Delivered',))),
                      other_delivered=Count('id', filter=~Q(shop=shop) & Q(status='Delivered')),
                      other_failed=Count('id', filter=~Q(shop=shop) & Q(status__in=FAILED))))
    for row in rows:
        risk = result[row['customer__phone']]
        for key in ('own_delivered', 'own_failed', 'own_active', 'other_delivered', 'other_failed'):
            setattr(risk, key, row[key])
    for phone in Customer.objects.filter(shop=shop, phone__in=phones, is_blocked=True).values_list('phone', flat=True):
        result[phone].blocked = True
    return result


def for_phone(shop, phone):
    return for_phones(shop, [phone]).get(phone) or Risk(phone=phone or '')


def attach(shop, objects, phone_of):
    """প্রতিটা অবজেক্টে .risk বসায় (walk-in হলে None)।"""
    objects = list(objects)
    risks = for_phones(shop, [phone_of(o) for o in objects])
    for obj in objects:
        obj.risk = risks.get(phone_of(obj))
    return objects


def is_blocked(shop, phone):
    return Customer.objects.filter(shop=shop, phone=phone, is_blocked=True).exists()
