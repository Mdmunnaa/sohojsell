"""ল্যান্ডিং পেজ: এক প্রোডাক্টের এক পাতার বিক্রির পেজ (Facebook বিজ্ঞাপনের জন্য)।"""
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import reviews, seo
from .links import storefront_link
from .models import LandingPage, Product, Shop

LOGIN = '/accounts/login/'
MAX_PAGES = 30
FIELDS = ('headline', 'subheadline', 'bullets', 'offer_text', 'cta_text', 'slug')
DEFAULT_BULLETS = ['ক্যাশ অন ডেলিভারি — পণ্য হাতে পেয়ে টাকা দিন', 'সারা বাংলাদেশে ডেলিভারি', 'পণ্যে সমস্যা থাকলে ফেরত নেওয়া হয়']


class LandingError(ValueError):
    pass


def _clean(shop, post, exclude_id=None):
    product = Product.objects.filter(shop=shop, pk=post.get('product') or 0, is_active=True).first()
    if product is None:
        raise LandingError('প্রোডাক্ট বেছে নিন।')
    headline = ' '.join(str(post.get('headline', '')).split())[:120]
    if len(headline) < 3:
        raise LandingError('শিরোনাম লিখুন (যেমন: "ঘরে বসে পান আসল টাঙ্গাইল শাড়ি")।')
    slug = slugify(str(post.get('slug') or headline), allow_unicode=True)[:60].strip('-')
    if not slug:
        slug = f'page-{product.id}'
    same = LandingPage.objects.filter(shop=shop, slug=slug)
    if exclude_id:
        same = same.exclude(pk=exclude_id)
    if same.exists():
        raise LandingError(f'"{slug}" লিংকটা আগেই আছে, অন্য লিংক দিন।')
    return {
        'product': product, 'headline': headline, 'slug': slug,
        'subheadline': ' '.join(str(post.get('subheadline', '')).split())[:200],
        'bullets': '\n'.join(line.strip() for line in str(post.get('bullets', '')).splitlines() if line.strip())[:2000],
        'offer_text': ' '.join(str(post.get('offer_text', '')).split())[:120],
        'cta_text': (' '.join(str(post.get('cta_text', '')).split())[:40] or 'এখনই অর্ডার করুন'),
        'show_reviews': post.get('show_reviews') == 'on',
        'show_stock': post.get('show_stock') == 'on',
        'is_active': post.get('is_active', 'on') == 'on',
    }


def _form_from(page=None, post=None):
    if post is not None:
        return {key: post.get(key, '') for key in FIELDS} | {
            'product': post.get('product', ''), 'show_reviews': post.get('show_reviews') == 'on',
            'show_stock': post.get('show_stock') == 'on', 'is_active': post.get('is_active', 'on') == 'on'}
    if page is None:
        return {'product': '', 'headline': '', 'subheadline': '', 'bullets': '\n'.join(DEFAULT_BULLETS),
                'offer_text': '', 'cta_text': 'এখনই অর্ডার করুন', 'slug': '', 'show_reviews': True,
                'show_stock': True, 'is_active': True}
    return {key: getattr(page, key) for key in FIELDS} | {
        'product': page.product_id, 'show_reviews': page.show_reviews, 'show_stock': page.show_stock,
        'is_active': page.is_active}


@login_required(login_url=LOGIN)
def landing_list(request):
    shop = request.user.shop
    pages = list(LandingPage.objects.filter(shop=shop).select_related('product'))
    for page in pages:
        page.url = storefront_link(shop, 'storefront_landing', page.slug)
        page.order_count = page.orders.exclude(status__in=('Cancelled', 'Returned')).count()
    return render(request, 'store/landing_list.html', {
        'shop': shop, 'pages': pages, 'total_views': sum(p.views for p in pages),
        'total_orders': sum(p.order_count for p in pages), 'max_pages': MAX_PAGES,
    })


@login_required(login_url=LOGIN)
def landing_edit(request, page_id=None):
    shop = request.user.shop
    page = get_object_or_404(LandingPage, pk=page_id, shop=shop) if page_id else None
    if request.method == 'POST':
        if page is None and LandingPage.objects.filter(shop=shop).count() >= MAX_PAGES:
            messages.error(request, f'সর্বোচ্চ {MAX_PAGES}টা ল্যান্ডিং পেজ রাখা যায়।')
            return redirect('landing_list')
        try:
            data = _clean(shop, request.POST, exclude_id=page.id if page else None)
        except LandingError as exc:
            messages.error(request, str(exc))
            form = _form_from(post=request.POST)
        else:
            if page is None:
                page = LandingPage.objects.create(shop=shop, **data)
                messages.success(request, 'ল্যান্ডিং পেজ তৈরি হয়েছে। লিংকটা Facebook বিজ্ঞাপনে দিন।')
            else:
                for key, value in data.items():
                    setattr(page, key, value)
                page.save()
                messages.success(request, 'ল্যান্ডিং পেজ সেভ হয়েছে।')
            return redirect('landing_list')
    else:
        form = _form_from(page)
        if page is None and request.GET.get('product', '').isdigit():
            form['product'] = int(request.GET['product'])
    return render(request, 'store/landing_edit.html', {
        'shop': shop, 'page': page, 'form': form,
        'products': Product.objects.filter(shop=shop, is_active=True).order_by('name'),
        'page_url': storefront_link(shop, 'storefront_landing', page.slug) if page else '',
    })


@login_required(login_url=LOGIN)
@require_POST
def landing_action(request, page_id):
    page = get_object_or_404(LandingPage, pk=page_id, shop=request.user.shop)
    action = request.POST.get('action')
    if action == 'toggle':
        page.is_active = not page.is_active
        page.save(update_fields=['is_active'])
        messages.success(request, 'পেজটা ' + ('চালু করা হয়েছে।' if page.is_active else 'বন্ধ করা হয়েছে — লিংকে গেলে দোকানের হোম দেখাবে।'))
    elif action == 'delete':
        page.delete()
        messages.success(request, 'ল্যান্ডিং পেজ মুছে ফেলা হয়েছে।')
    return redirect('landing_list')


# ---------------------------------------------------------------- কাস্টমারের দিক
@ensure_csrf_cookie
def storefront_landing(request, shop_slug, slug):
    from . import delivery, shop_payments
    shop = get_object_or_404(Shop, slug=shop_slug)
    page = LandingPage.objects.filter(shop=shop, slug=slug).select_related('product').first()
    if page is None:
        raise Http404
    product = page.product
    if not page.is_active or not product.is_active:
        return redirect(storefront_link(shop, request=request))
    LandingPage.objects.filter(pk=page.pk).update(views=F('views') + 1)
    reviews.attach([product])
    description = page.subheadline or (product.description or '')[:160] or page.headline
    meta = seo.storefront_meta(request, shop, title=f'{page.headline} — {shop.name}', description=description,
                               image=product.image if product.image else None, og_type='product',
                               price=product.price, link_name='storefront_landing', link_args=(page.slug,))
    variant_list = [{'id': -v.id, 'name': v.name, 'price': float(v.sell_price), 'stock': v.stock_quantity}
                    for v in product.variants.all()] if product.has_variants else []
    zones = delivery.zones_for(shop)
    return render(request, 'store/storefront/landing.html', {
        'shop': shop, 'page': page, 'product': product, 'meta': meta,
        'bullets': page.bullet_list, 'variant_list': variant_list, 'zones': zones,
        'free_delivery_min': shop.free_delivery_min,
        'review_list': reviews.approved_for(product, limit=6) if page.show_reviews else [],
        'payment_choices': shop_payments.checkout_choices(shop),
        'place_order_url': storefront_link(shop, 'storefront_place_order', request=request),
        'product_ld': seo.product_ld(request, shop, product, meta, product.rating),
        'wa_text': f'আসসালামু আলাইকুম, আমি "{product.name}" অর্ডার করতে চাই।',
    })
