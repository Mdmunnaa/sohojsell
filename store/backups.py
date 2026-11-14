"""
ব্যাকআপের অবস্থা দেখানো (Edumi-র core/backup_checks.py থেকে)।

* ব্যাকআপ নিজে চলে GitHub Actions-এ: প্রতি রাতে scripts/db_backup.py (এনক্রিপ্ট করে R2-এর private বাকেটে, ৩০ দিন),
  প্রতি শুক্রবার scripts/backup_restore_check.py (ফাঁকা ডাটাবেসে পুরো ফেরত এনে মিলিয়ে দেখা) — ফল store_backupcheck-এ এক লাইন।
* "নিরাপত্তা ও ডাটা" পাতা আর সেটিংস: শেষ সফল পরীক্ষার তারিখ — ১৪ দিনের বেশি পুরনো হলে লাইনটাই লুকায়
  (পুরনো দাবি কখনো দেখানো হয় না)। সংখ্যা (কত দোকান, কত অর্ডার) শুধু Master HQ-তে।
* Master HQ: পরীক্ষা ব্যর্থ হলে বা ৯ দিন কোনো পরীক্ষা না হলে "এখন যা করতে হবে"-তে ওঠে।
"""
import datetime

from django.utils import timezone

TRUST_FRESH_DAYS = 14
STALE_ALERT_DAYS = 9

_BN = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')


def duration_text(seconds):
    if seconds is None:
        return ''
    if seconds < 60:
        return '১ মিনিটেরও কম'
    return f'{str(int(seconds / 60 + 0.5)).translate(_BN)} মিনিট'


def latest_success(now=None):
    from .models import BackupCheck
    now = now or timezone.now()
    return BackupCheck.objects.filter(ok=True, checked_at__gte=now - datetime.timedelta(days=TRUST_FRESH_DAYS)).first()


def trust_line(now=None):
    """{'date': '৭ নভেম্বর ২০২৬', 'duration': '৩ মিনিট'} — টাটকা সফল পরীক্ষা না থাকলে None।"""
    from .company import bn_date
    check = latest_success(now)
    if check is None:
        return None
    return {'date': bn_date(timezone.localtime(check.checked_at).date()), 'duration': duration_text(check.restore_seconds)}


def hq_status(now=None):
    """Master HQ-র জন্য: শেষ পরীক্ষা, আর কিছু করার থাকলে এক লাইনের সতর্কতা (না থাকলে warning = '')।"""
    from .models import BackupCheck
    now = now or timezone.now()
    last = BackupCheck.objects.first()
    warning = ''
    if last is None:
        warning = 'ব্যাকআপ পরীক্ষার কোনো ফল এখনো আসেনি — GitHub-এ ব্যাকআপের Secrets বসানো হয়েছে কিনা দেখুন'
    elif not last.ok:
        warning = 'শেষ ব্যাকআপ পরীক্ষা ব্যর্থ হয়েছে — GitHub → Actions-এ কারণ দেখুন'
    elif last.checked_at < now - datetime.timedelta(days=STALE_ALERT_DAYS):
        warning = f'{STALE_ALERT_DAYS} দিনের বেশি কোনো ব্যাকআপ পরীক্ষা হয়নি — GitHub → Actions দেখুন'
    return {'last': last, 'warning': warning}
