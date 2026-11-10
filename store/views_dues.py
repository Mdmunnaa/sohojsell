"""কাস্টমারের বাকির খাতা (হিসাব: store/dues.py, আদায়: store/pos.py)।"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import dues, pos, sms
from .dashboard import bn_num
from .models import Shop

LOGIN = '/accounts/login/'


def _can_sms(user):
    return not user.is_shop_staff or user.staff_profile.can_send_sms


@login_required(login_url=LOGIN)
def due_list(request):
    shop = request.user.shop
    rows = dues.rows(shop)
    q = request.GET.get('q', '').strip()
    show = request.GET.get('show', '')
    if q:
        rows = [r for r in rows if q.lower() in r['name'].lower() or q in r['phone']]
    if show == 'old':
        rows = [r for r in rows if r['age'] == 'old']
    elif show == 'promise':
        rows = [r for r in rows if r['promise_passed']]
    return render(request, 'store/dues.html', {
        'shop': shop, 'rows': rows, 'q': q, 'show': show,
        'summary': dues.summary(shop, dues.rows(shop) if (q or show) else rows),
        'today': timezone.localdate(), 'can_sms': _can_sms(request.user),
        'sample_text': sms.due_reminder_text(shop, 'রহিম', 1250),
        'auto_choices': dues.AUTO_REMINDER_CHOICES,
        'methods': [('cash', 'নগদ'), ('bkash', 'bKash'), ('nagad', 'Nagad'), ('card', 'কার্ড'), ('bank', 'ব্যাংক')],
    })


@login_required(login_url=LOGIN)
def due_detail(request, phone):
    shop = request.user.shop
    book = dues.ledger(shop, phone)
    if book is None:
        messages.error(request, 'এই নম্বরে কোনো কাস্টমার নেই।')
        return redirect('due_list')
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'collect':
                collected, left = pos.collect_due(shop, request.user, phone, request.POST.get('amount'),
                                                  request.POST.get('method', 'cash'), request.POST.get('reference', ''))
                messages.success(request, f'৳{bn_num(f"{collected:,.0f}")} আদায় হলো।'
                                 + (f' এখনো বাকি ৳{bn_num(f"{left:,.0f}")}।' if left > 0 else ' পুরো বাকি শোধ হয়ে গেছে।'))
            elif action == 'promise':
                dues.set_promise(shop, phone, request.POST.get('promise'), request.POST.get('note'))
                messages.success(request, 'লিখে রাখা হয়েছে।')
            elif action == 'remind':
                if not _can_sms(request.user):
                    raise dues.DueError('SMS পাঠানোর অনুমতি নেই।')
                result = dues.send_reminders(shop, request.user, [phone], skip_recent=False)
                (messages.success if result.ok else messages.error)(request, sms.describe(result))
        except (pos.POSError, dues.DueError) as exc:
            messages.error(request, str(exc))
        return redirect('due_detail', phone)
    return render(request, 'store/due_detail.html', {
        'shop': shop, **book, 'today': timezone.localdate(), 'can_sms': _can_sms(request.user),
        'reminder_text': sms.due_reminder_text(shop, book['customer'].name, book['due']) if book['due'] > 0 else '',
        'methods': [('cash', 'নগদ'), ('bkash', 'bKash'), ('nagad', 'Nagad'), ('card', 'কার্ড'), ('bank', 'ব্যাংক')],
    })


@login_required(login_url=LOGIN)
@require_POST
def due_remind_all(request):
    """সবাইকে (বা বাছাই করা কয়েকজনকে) তাগাদা SMS।"""
    shop = request.user.shop
    if not _can_sms(request.user):
        messages.error(request, 'SMS পাঠানোর অনুমতি নেই।')
        return redirect('due_list')
    phones = request.POST.getlist('phones') or None
    try:
        result = dues.send_reminders(shop, request.user, phones)
    except dues.DueError as exc:
        messages.error(request, str(exc))
    else:
        (messages.success if result.ok else messages.error)(request, sms.describe(result))
    return redirect('due_list')


@login_required(login_url=LOGIN)
@require_POST
def due_auto_setting(request):
    shop = request.user.shop
    if request.user.is_shop_staff:
        messages.error(request, 'এটা মালিক বদলাতে পারবেন।')
        return redirect('due_list')
    try:
        days = int(request.POST.get('days', 0))
    except ValueError:
        days = 0
    if days not in dict(dues.AUTO_REMINDER_CHOICES):
        days = 0
    Shop.objects.filter(pk=shop.pk).update(due_reminder_days=days)
    messages.success(request, 'নিজে থেকে তাগাদা বন্ধ করা হয়েছে।' if not days
                     else f'বাকি থাকা কাস্টমারদের {bn_num(days)} দিন পর পর নিজে থেকে তাগাদা SMS যাবে।')
    return redirect('due_list')
