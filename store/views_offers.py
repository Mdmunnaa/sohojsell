"""সেলারের দিক: কুপন ও অফার, অসম্পূর্ণ অর্ডার, রিভিউ অনুমোদন।"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import offers, reviews
from .models import AbandonedCheckout, Coupon, ProductReview, Shop

LOGIN = '/accounts/login/'


# ---------------------------------------------------------------- কুপন
@login_required(login_url=LOGIN)
def coupon_list(request):
    shop = request.user.shop
    form = {'code': '', 'kind': 'percent', 'value': '', 'min_order': '', 'max_discount': '', 'usage_limit': '',
            'starts_on': '', 'ends_on': ''}
    if request.method == 'POST':
        form = {key: request.POST.get(key, '').strip() for key in form}
        if Coupon.objects.filter(shop=shop).count() >= offers.MAX_COUPONS:
            messages.error(request, f'সর্বোচ্চ {offers.MAX_COUPONS}টা কুপন রাখা যায়। পুরনোগুলো মুছে দিন।')
            return redirect('coupon_list')
        try:
            data = offers.clean_coupon(shop, request.POST)
        except offers.CouponError as exc:
            messages.error(request, str(exc))
        else:
            coupon = Coupon.objects.create(shop=shop, **data)
            messages.success(request, f'কুপন "{coupon.code}" চালু হয়েছে: {offers.describe(coupon)}।')
            return redirect('coupon_list')
    today = timezone.localdate()
    coupons = list(Coupon.objects.filter(shop=shop))
    for coupon in coupons:
        coupon.state, coupon.state_label = offers.status_of(coupon, today)
        coupon.text = offers.describe(coupon)
    live = [c for c in coupons if c.state == 'live']
    return render(request, 'store/coupons.html', {
        'shop': shop, 'coupons': coupons, 'form': form, 'kinds': Coupon.KIND_CHOICES, 'today': today,
        'live_count': len(live), 'used_total': sum(c.used_count for c in coupons),
        'storefront_url': shop.storefront_url,
    })


@login_required(login_url=LOGIN)
@require_POST
def coupon_action(request, coupon_id):
    coupon = get_object_or_404(Coupon, pk=coupon_id, shop=request.user.shop)
    action = request.POST.get('action')
    if action == 'toggle':
        coupon.is_active = not coupon.is_active
        coupon.save(update_fields=['is_active'])
        messages.success(request, f'কুপন "{coupon.code}" ' + ('চালু করা হয়েছে।' if coupon.is_active else 'বন্ধ করা হয়েছে।'))
    elif action == 'delete':
        coupon.delete()
        messages.success(request, f'কুপন "{coupon.code}" মুছে ফেলা হয়েছে।')
    return redirect('coupon_list')


# ---------------------------------------------------------------- অসম্পূর্ণ অর্ডার
@login_required(login_url=LOGIN)
def abandoned_list(request):
    shop = request.user.shop
    drafts = offers.open_drafts(shop)
    page = Paginator(drafts, 25).get_page(request.GET.get('page'))
    rows = list(page.object_list)
    from . import risk
    risk.attach(shop, rows, lambda d: d.phone)
    recovered = AbandonedCheckout.objects.filter(shop=shop, recovered_order__isnull=False).count()
    return render(request, 'store/abandoned.html', {
        'shop': shop, 'page_obj': page, 'rows': rows, 'open_count': drafts.count(), 'recovered': recovered,
        'open_value': sum((d.total for d in drafts), 0),
        'can_sms': not request.user.is_shop_staff or request.user.staff_profile.can_send_sms,
    })


@login_required(login_url=LOGIN)
@require_POST
def abandoned_action(request, draft_id):
    draft = get_object_or_404(AbandonedCheckout, pk=draft_id, shop=request.user.shop)
    action = request.POST.get('action')
    if action == 'contacted':
        draft.contacted = not draft.contacted
        draft.save(update_fields=['contacted'])
    elif action == 'delete':
        draft.delete()
        messages.success(request, 'মুছে ফেলা হয়েছে।')
    return redirect('abandoned_list')


# ---------------------------------------------------------------- রিভিউ
@login_required(login_url=LOGIN)
def review_list(request):
    shop = request.user.shop
    if request.method == 'POST' and request.POST.get('section') == 'settings':
        Shop.objects.filter(pk=shop.pk).update(reviews_enabled=request.POST.get('reviews_enabled') == 'on',
                                               reviews_auto_approve=request.POST.get('reviews_auto_approve') == 'on')
        messages.success(request, 'রিভিউর সেটিং সেভ হয়েছে।')
        return redirect('review_list')
    show = request.GET.get('show') if request.GET.get('show') in ('pending', 'approved') else 'pending'
    rows = ProductReview.objects.filter(shop=shop, is_approved=(show == 'approved')).select_related('product')
    page = Paginator(rows, 25).get_page(request.GET.get('page'))
    return render(request, 'store/reviews.html', {
        'shop': shop, 'page_obj': page, 'show': show,
        'pending_count': reviews.pending_count(shop),
        'approved_count': ProductReview.objects.filter(shop=shop, is_approved=True).count(),
    })


@login_required(login_url=LOGIN)
@require_POST
def review_action(request, review_id):
    review = get_object_or_404(ProductReview, pk=review_id, shop=request.user.shop)
    action = request.POST.get('action')
    if action == 'approve':
        review.is_approved = True
        review.save(update_fields=['is_approved'])
        messages.success(request, 'রিভিউটা ওয়েবসাইটে দেখানো হবে।')
    elif action == 'hide':
        review.is_approved = False
        review.save(update_fields=['is_approved'])
        messages.success(request, 'রিভিউটা ওয়েবসাইট থেকে সরানো হয়েছে।')
    elif action == 'delete':
        review.delete()
        messages.success(request, 'রিভিউটা মুছে ফেলা হয়েছে।')
    return redirect(request.POST.get('next') or 'review_list')
