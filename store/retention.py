"""
প্যাকেজ শেষের পর দোকানের ডাটা কত দিন থাকে — Edumi-র মতো ৯০ দিন (মুন্নার সিদ্ধান্ত, ১৪ নভেম্বর ২০২৬)।

- মেয়াদ (ট্রায়াল বা পেইড) শেষের দিন থেকে টানা ৯০ দিন বিল না দিলে দোকান, সব তথ্য আর মালিক-স্টাফের অ্যাকাউন্ট মুছে ফেলা যায়।
- মোছার আগে মালিককে SMS: মেয়াদ শেষের ৭, ৩০, ৬০ আর ৮০তম দিনে (দৈনিক কাজ, store/views_cron.py)।
- মোছা নিজে থেকে হয় না: Master HQ → "বকেয়া ও মুছে ফেলা" থেকে হাতে, সাবডোমেইন লিখে নিশ্চিত করে।
  শেষ (৮০ দিনের) সতর্কবার্তা যাওয়ার অন্তত ৭ দিন পরে তবেই।
- পুরো সময়টা মালিক বিল দিতে পারেন বা সব ডাটা Excel-এ নামাতে পারেন (লক থাকলেও)।
শর্তাবলি §৩, প্রাইভেসি §৪, নিরাপত্তা পাতা আর বিলিং পাতা এই সংখ্যাগুলোই দেখায়।
"""
import datetime
import logging

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .plans import TRIAL_PLAN, subscription_end

logger = logging.getLogger(__name__)

DATA_DELETION_DAYS = 90
REMINDER_DAYS = (7, 30, 60, 80)
FINAL_NOTICE_GAP_DAYS = 7
UPCOMING_WINDOW_DAYS = 30          # Master HQ: আর কত দিনের মধ্যে মোছার যোগ্য হবে, তাদের আলাদা তালিকা


def _today(today=None):
    return today or timezone.localdate()


def ended_on(shop, today=None):
    """মেয়াদ শেষ হয়ে থাকলে শেষ দিনটা (সেদিন পর্যন্ত চালু ছিল), নাহলে None। ডেমো আর বন্ধ করা দোকানে নিয়ম খাটে না।"""
    if shop.is_demo or shop.is_suspended:
        return None
    end = subscription_end(shop)
    if end is None or end >= _today(today):
        return None
    return end


def delete_on(end):
    return end + datetime.timedelta(days=DATA_DELETION_DAYS)


def deletion_notice(shop, today=None):
    """বিলিং পাতার জন্য: মেয়াদ শেষ হলে {'date', 'days_left', 'overdue_days'}; নাহলে None।"""
    today = _today(today)
    end = ended_on(shop, today)
    if end is None:
        return None
    date = delete_on(end)
    return {'date': date, 'days_left': max((date - today).days, 0), 'overdue_days': (today - end).days}


def reminder_stage_for(overdue_days):
    """কত দিন পার হলে কোন ধাপের সতর্কবার্তা পাওনা (০ = এখনো না)।"""
    due = [day for day in REMINDER_DAYS if day <= overdue_days]
    return due[-1] if due else 0


def _expired_before(day):
    """মেয়াদ day বা তার আগে শেষ হয়েছে এমন দোকান (ডাটাবেসে মোটা দাগে; ঠিক হিসাব ended_on দিয়ে)।"""
    from .hq import day_start
    return ((Q(subscription_plan=TRIAL_PLAN) & Q(trial_ends_at__lt=day_start(day + datetime.timedelta(days=1))))
            | (~Q(subscription_plan=TRIAL_PLAN) & Q(valid_until__lte=day)))


def _candidates(latest_end):
    from .models import Shop
    return (Shop.objects.filter(is_demo=False, is_suspended=False).filter(_expired_before(latest_end))
            .select_related('user'))


def warning_text(overdue_days, date, final=False):
    from .company import bn_date
    site = getattr(settings, 'SITE_NAME', 'SellPunch')
    domain = getattr(settings, 'STORE_BASE_DOMAIN', '') or 'sellpunch.com'
    n = str(overdue_days).translate(str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯'))
    if final:
        return (f'{site} শেষ সতর্কবার্তা: প্যাকেজের মেয়াদ {n} দিন আগে শেষ। {bn_date(date)}-এর পর দোকানের সব তথ্য মুছে যাবে। '
                f'এখনই বিল দিন বা সব ডাটা নামান: {domain}/billing/')
    return (f'{site}: প্যাকেজের মেয়াদ {n} দিন আগে শেষ। {bn_date(date)}-এর পর দোকানের সব তথ্য মুছে যাবে। '
            f'বিল দিন বা সব ডাটা নামান: {domain}/billing/')


def _phones(shop):
    from . import sms
    out = []
    for value in (getattr(shop.user, 'phone_number', ''), shop.phone):
        phone = sms.normalize(value)
        if phone and phone not in out:
            out.append(phone)
    return out


def send_expiry_warnings(today=None):
    """
    যাদের পাওনা, তাদের সতর্কবার্তা — প্রতিটা ধাপ একবারই (দেরিতে চালু হলে শুধু সর্বশেষ পাওনা ধাপ)।
    দুটো প্রসেস একসাথে চললেও একই SMS দুবার যায় না: শর্তসহ update করে যে "দাবি" করে, সে-ই পাঠায়।
    SMS গেটওয়ে চালু না থাকলে কিছুই দাবি করে না — যেন "পাঠানো হয়েছে" ভেবে কেউ আগে মুছে না ফেলে।
    ফেরত: কয়টা দোকানে পাঠানো হলো।
    """
    from . import sms
    from .models import Shop
    if not sms.gateway_ready():
        return 0
    today = _today(today)
    sent = 0
    for shop in _candidates(today - datetime.timedelta(days=REMINDER_DAYS[0])):
        end = ended_on(shop, today)
        if end is None:
            continue
        overdue = (today - end).days
        stage = reminder_stage_for(overdue)
        if not stage or (shop.expiry_warn_end == end and shop.expiry_warn_stage >= stage):
            continue
        claimed = (Shop.objects.filter(pk=shop.pk)
                   .filter(Q(expiry_warn_end__isnull=True) | ~Q(expiry_warn_end=end) | Q(expiry_warn_stage__lt=stage))
                   .update(expiry_warn_end=end, expiry_warn_stage=stage, expiry_warn_sent_on=today))
        if not claimed:
            continue
        text = warning_text(overdue, delete_on(end), final=stage == REMINDER_DAYS[-1])
        for phone in _phones(shop):
            try:
                sms.notify(phone, text)
            except Exception:       # noqa: BLE001 — একটা দোকানে আটকালেও বাকিরা পাবে
                logger.exception('Expiry warning SMS failed for shop %s', shop.pk)
        sent += 1
    return sent


def final_notice_blocker(shop, today=None):
    """
    Master HQ মোছার আগে: শেষ সতর্কবার্তা গেছে কিনা, আর তার পর ৭ দিন পার হয়েছে কিনা (নাহলে কারণ, হলে None)।
    মেয়াদ শেষ না হলে (টেস্ট সাইনআপ, মালিকের নিজের অনুরোধ) এই শর্ত নেই।
    """
    today = _today(today)
    end = ended_on(shop, today)
    if end is None:
        return None
    if not (shop.expiry_warn_end == end and shop.expiry_warn_stage >= REMINDER_DAYS[-1] and shop.expiry_warn_sent_on):
        return 'এখনো শেষ সতর্কবার্তা (SMS) যায়নি — নিয়ম অনুযায়ী তার আগে মোছা যায় না।'
    allowed_on = shop.expiry_warn_sent_on + datetime.timedelta(days=FINAL_NOTICE_GAP_DAYS)
    if today < allowed_on:
        return f'শেষ সতর্কবার্তা {shop.expiry_warn_sent_on:%d-%m-%Y} তারিখে গেছে — {allowed_on:%d-%m-%Y} থেকে মোছা যাবে।'
    return None


def overdue_shops(today=None):
    """
    Master HQ-র "বকেয়া ও মুছে ফেলা": (মোছার যোগ্য, আগামী ৩০ দিনে যোগ্য হবে) — প্রতিটায় dict(shop, end, overdue_days,
    delete_on, blocker)। পুরনো মেয়াদ আগে।
    """
    today = _today(today)
    latest = today - datetime.timedelta(days=DATA_DELETION_DAYS - UPCOMING_WINDOW_DAYS)
    eligible, upcoming = [], []
    for shop in _candidates(latest):
        end = ended_on(shop, today)
        if end is None:
            continue
        row = {'shop': shop, 'end': end, 'overdue_days': (today - end).days, 'delete_on': delete_on(end)}
        if row['delete_on'] <= today:
            row['blocker'] = final_notice_blocker(shop, today)
            eligible.append(row)
        else:
            upcoming.append(row)
    key = lambda row: (row['end'], row['shop'].pk)     # noqa: E731
    return sorted(eligible, key=key), sorted(upcoming, key=key)


def eligible_count(today=None):
    return len(overdue_shops(today)[0])
