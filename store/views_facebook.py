"""
Facebook অটোমেশনের পাতা (/facebook/automation/) আর Messenger-এর কথোপকথন (/messenger/)।

অটোমেশন: কমেন্ট · Messenger · প্রশ্ন-উত্তর · Facebook থেকে বিক্রি · কমেন্টের হিসাব — দোকানের সেটিংসের অনুমতি লাগে।
কথোপকথন: কে উত্তরের অপেক্ষায়, বট থামানো/চালু — অর্ডারের অনুমতি লাগে (store/middleware.py)।
"""
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import facebook_bot, messenger, order_flow
from .models import FacebookAutoReply, FacebookCommentReply, FacebookPageConnection, MessengerContact, Order
from .plans import has_facebook, upgrade_message

TABS = [('comments', 'bi-chat-left-text', 'কমেন্ট'), ('messenger', 'bi-messenger', 'Messenger'),
        ('faq', 'bi-question-circle', 'প্রশ্ন-উত্তর'), ('sales', 'bi-graph-up-arrow', 'Facebook থেকে বিক্রি'),
        ('log', 'bi-list-check', 'কমেন্টের হিসাব')]
FB_SOURCES = ('comment', 'messenger', 'chat')
SOURCE_LABELS = {'comment': 'কমেন্টের পর ইনবক্সের লিংক', 'messenger': 'Messenger-এর লিংক', 'chat': 'Messenger-এ চ্যাট করে'}


class CommentSettingsForm(forms.ModelForm):
    class Meta:
        model = FacebookPageConnection
        fields = ['comment_bot_enabled', 'public_reply_enabled', 'public_reply_texts', 'comment_dm_intro',
                  'hide_phone_comments', 'hide_link_comments', 'hide_words']
        widgets = {
            'public_reply_texts': forms.Textarea(attrs={'rows': 4, 'class': 'form-control',
                                                        'placeholder': 'ইনবক্স চেক করুন, বিস্তারিত পাঠানো হয়েছে।'}),
            'comment_dm_intro': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 300,
                                                       'placeholder': 'আসসালামু আলাইকুম {name}! কমেন্ট করার জন্য ধন্যবাদ।'}),
            'hide_words': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'যেমন: ফেক, স্ক্যাম'}),
        }


class MessengerSettingsForm(forms.ModelForm):
    class Meta:
        model = FacebookPageConnection
        fields = ['messenger_bot_enabled', 'welcome_text', 'messenger_order_enabled', 'order_updates_enabled',
                  'open_time', 'close_time', 'offhours_text']
        widgets = {
            'welcome_text': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'maxlength': 500}),
            'open_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
            'close_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}, format='%H:%M'),
            'offhours_text': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'maxlength': 500}),
        }

    def clean(self):
        data = super().clean()
        if bool(data.get('open_time')) != bool(data.get('close_time')):
            raise forms.ValidationError('খোলা আর বন্ধের দুটো সময়ই দিন, অথবা দুটোই খালি রাখুন (সবসময় খোলা)।')
        return data


class AutoReplyForm(forms.ModelForm):
    class Meta:
        model = FacebookAutoReply
        fields = ['keywords', 'answer']
        widgets = {
            'keywords': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 300,
                                               'placeholder': 'যেমন: সাইজ, size, মাপ'}),
            'answer': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'maxlength': 1500,
                                            'placeholder': 'যেমন: M, L, XL আর XXL সাইজ আছে। মাপের চার্ট পোস্টে দেওয়া আছে।'}),
        }

    def clean_keywords(self):
        words = [w.strip() for w in self.cleaned_data['keywords'].replace('،', ',').split(',') if w.strip()]
        if not words:
            raise forms.ValidationError('অন্তত একটা শব্দ দিন।')
        return ', '.join(dict.fromkeys(words))[:300]


def _shop(request):
    return getattr(request.user, 'shop', None)


def _guard(request):
    """দোকান আর প্যাকেজ ঠিক আছে কিনা; না থাকলে কোথায় পাঠাতে হবে।"""
    shop = _shop(request)
    if shop is None:
        return None, redirect('setup_shop')
    if not has_facebook(shop):
        messages.warning(request, upgrade_message("Facebook অটোমেশন (Standard ও Premium প্যাকেজে আছে)"))
        return None, redirect('billing')
    return shop, None


def sales_report(shop, days):
    since = timezone.now() - timedelta(days=days)
    orders = Order.objects.filter(shop=shop, fb_source__in=FB_SOURCES, created_at__gte=since)
    counted = orders.exclude(status__in=order_flow.NOT_COUNTED)
    totals = counted.aggregate(n=Count('id'), amount=Sum('total_amount'))
    by_source = {row['fb_source']: row for row in counted.values('fb_source').annotate(n=Count('id'), amount=Sum('total_amount'))}
    sources = [{'key': key, 'label': SOURCE_LABELS[key], 'n': by_source.get(key, {}).get('n', 0),
                'amount': by_source.get(key, {}).get('amount') or 0} for key in FB_SOURCES]
    posts = list(counted.exclude(fb_post_id='').values('fb_post_id').annotate(n=Count('id'), amount=Sum('total_amount'))
                 .order_by('-amount')[:8])
    comments = FacebookCommentReply.objects.filter(shop=shop, created_at__gte=since).aggregate(
        total=Count('id'), sent=Count('id', filter=Q(status='sent')), failed=Count('id', filter=Q(status='failed')),
        hidden=Count('id', filter=~Q(hidden_reason='')))
    chats = MessengerContact.objects.filter(shop=shop, last_in_at__gte=since).count()
    return {
        'days': days, 'orders': totals['n'] or 0, 'amount': totals['amount'] or 0,
        'cancelled': orders.filter(status__in=order_flow.NOT_COUNTED).count(),
        'sources': sources, 'posts': [dict(p, url=f'https://www.facebook.com/{p["fb_post_id"]}') for p in posts],
        'comments': comments, 'chats': chats,
        'recent': list(orders.select_related('customer').order_by('-id')[:10]),
    }


@login_required(login_url='/accounts/login/')
def fb_automation(request):
    shop, bounce = _guard(request)
    if bounce:
        return bounce
    connection = FacebookPageConnection.objects.filter(shop=shop).first()
    tab = request.GET.get('tab') or request.POST.get('tab') or 'comments'
    if tab not in dict((key, 1) for key, _i, _l in TABS):
        tab = 'comments'
    context = {'shop': shop, 'connection': connection, 'tabs': TABS, 'tab': tab}
    if connection is None:
        return render(request, 'store/facebook/automation.html', context)

    comment_form = CommentSettingsForm(instance=connection)
    messenger_form = MessengerSettingsForm(instance=connection)
    if request.method == 'POST' and tab in ('comments', 'messenger') and not shop.is_demo:
        form_class = CommentSettingsForm if tab == 'comments' else MessengerSettingsForm
        form = form_class(request.POST, instance=connection)
        if form.is_valid():
            connection = form.save()
            facebook_bot.subscribe_page(connection.page_id, connection.page_access_token)
            if tab == 'messenger' and connection.messenger_bot_enabled:
                messenger.setup_profile(connection)
            messages.success(request, 'সেটিং সেভ হয়েছে।')
            return redirect(f"{reverse('fb_automation')}?tab={tab}")
        if tab == 'comments':
            comment_form = form
        else:
            messenger_form = form

    context.update(comment_form=comment_form, messenger_form=messenger_form)
    if tab == 'faq':
        context.update(replies=FacebookAutoReply.objects.filter(shop=shop), reply_form=AutoReplyForm())
    elif tab == 'sales':
        days = int(request.GET.get('days') or 30) if str(request.GET.get('days') or '30').isdigit() else 30
        days = days if days in (7, 30, 90) else 30
        context.update(report=sales_report(shop, days), periods=[(7, '৭ দিন'), (30, '৩০ দিন'), (90, '৯০ দিন')])
    elif tab == 'log':
        context.update(log=FacebookCommentReply.objects.filter(shop=shop).select_related('product')[:60])
    context['waiting'] = MessengerContact.objects.filter(shop=shop, waiting_since__isnull=False).count()
    context['faq_count'] = FacebookAutoReply.objects.filter(shop=shop).count()
    return render(request, 'store/facebook/automation.html', context)


@login_required(login_url='/accounts/login/')
@require_POST
def fb_faq_save(request):
    shop, bounce = _guard(request)
    if bounce:
        return bounce
    instance = None
    if request.POST.get('id'):
        instance = get_object_or_404(FacebookAutoReply, pk=request.POST['id'], shop=shop)
    form = AutoReplyForm(request.POST, instance=instance)
    if shop.is_demo:
        messages.info(request, 'ডেমো দোকানে প্রশ্ন-উত্তর সেভ হয় না।')
    elif form.is_valid():
        if instance is None and FacebookAutoReply.objects.filter(shop=shop).count() >= 100:
            messages.error(request, 'সর্বোচ্চ ১০০টা প্রশ্ন-উত্তর রাখা যায়।')
        else:
            reply = form.save(commit=False)
            reply.shop = shop
            reply.save()
            messages.success(request, 'প্রশ্ন-উত্তর সেভ হয়েছে।')
    else:
        messages.error(request, ' '.join(e for errors in form.errors.values() for e in errors))
    return redirect(f"{reverse('fb_automation')}?tab=faq")


@login_required(login_url='/accounts/login/')
@require_POST
def fb_faq_action(request, pk):
    shop, bounce = _guard(request)
    if bounce:
        return bounce
    reply = get_object_or_404(FacebookAutoReply, pk=pk, shop=shop)
    action = request.POST.get('action')
    if action == 'delete':
        reply.delete()
        messages.success(request, 'প্রশ্ন-উত্তর মুছে ফেলা হয়েছে।')
    elif action == 'toggle':
        reply.is_active = not reply.is_active
        reply.save(update_fields=['is_active'])
    return redirect(f"{reverse('fb_automation')}?tab=faq")


@login_required(login_url='/accounts/login/')
def messenger_inbox(request):
    shop, bounce = _guard(request)
    if bounce:
        return bounce
    connection = FacebookPageConnection.objects.filter(shop=shop).first()
    contacts = MessengerContact.objects.filter(shop=shop)
    waiting = contacts.filter(waiting_since__isnull=False).count()
    view = request.GET.get('view') or ('waiting' if waiting else 'all')
    listed = contacts.filter(waiting_since__isnull=False).order_by('waiting_since') if view == 'waiting' \
        else contacts.order_by('-last_in_at')
    now = timezone.now()
    rows = []
    for contact in listed.select_related('last_product')[:100]:
        paused = bool(contact.bot_paused_until and contact.bot_paused_until > now)
        rows.append({'c': contact, 'paused': paused, 'in_window': messenger.in_window(contact, now),
                     'orders': contact.orders.count() if contact.pk else 0})
    return render(request, 'store/facebook/inbox.html', {
        'shop': shop, 'connection': connection, 'rows': rows, 'view': view, 'waiting': waiting,
        'total': contacts.count(),
        'inbox_url': f'https://business.facebook.com/latest/inbox/all?asset_id={connection.page_id}' if connection else '',
    })


@login_required(login_url='/accounts/login/')
@require_POST
def messenger_action(request, pk):
    shop, bounce = _guard(request)
    if bounce:
        return bounce
    contact = get_object_or_404(MessengerContact, pk=pk, shop=shop)
    action = request.POST.get('action')
    if action == 'done':
        contact.waiting_since = None
        contact.save(update_fields=['waiting_since'])
    elif action == 'resume':
        contact.bot_paused_until = None
        contact.save(update_fields=['bot_paused_until'])
        messages.success(request, f'{contact.name or "কাস্টমার"}-এর সাথে বট আবার চালু হয়েছে।')
    elif action == 'pause':
        contact.bot_paused_until = timezone.now() + timedelta(hours=24)
        contact.save(update_fields=['bot_paused_until'])
        messages.success(request, f'{contact.name or "কাস্টমার"}-এর সাথে বট ২৪ ঘণ্টা চুপ থাকবে।')
    return redirect(f"{reverse('messenger_inbox')}?view={request.POST.get('view') or 'all'}")
