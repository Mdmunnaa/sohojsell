"""
স্টকের হিসাব: কোন প্রোডাক্টের স্টক কবে, কেন, কত বাড়ল/কমল, কে করল (StockMovement, store/stock_log.py লেখে)।
"১০টা ছিল, ৭টা কেন?" — এই প্রশ্নের উত্তর এখানে।
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from . import units
from .models import Product, StockMovement
from .stock_log import low_stock_q

PER_PAGE = 50
REASON_LABELS = dict(StockMovement.REASONS)
# কোন কারণে কোন রং: বিক্রি = সাধারণ, ফেরত/কেনা = সবুজ, হাতে বদল = নীল, মোছা/বাতিল = কমলা
REASON_TONE = {
    'pos_sale': 'sale', 'order': 'sale', 'order_edit': 'edit',
    'pos_return': 'in', 'order_cancel': 'in', 'purchase': 'in', 'order_restore': 'sale',
    'manual': 'edit', 'new': 'edit', 'import': 'edit',
    'order_delete': 'warn', 'purchase_delete': 'warn', 'other': 'edit',
}


def _order_link(move):
    if not move.order_id:
        return None
    try:
        if move.reason.startswith('pos'):
            return reverse('pos_receipt', args=[move.order_id])
        return reverse('order_edit', args=[move.order_id])
    except NoReverseMatch:
        return None


@login_required(login_url='/accounts/login/')
def stock_history(request):
    shop = request.user.shop
    moves = (StockMovement.objects.filter(shop=shop)
             .select_related('product', 'user').order_by('-created_at', '-id'))

    product = None
    raw_product = request.GET.get('product', '')
    if raw_product.isdigit():
        product = Product.objects.filter(shop=shop, pk=int(raw_product)).first()
        if product is not None:
            moves = moves.filter(product=product)
    reason = request.GET.get('reason', '')
    if reason in REASON_LABELS:
        moves = moves.filter(reason=reason)
    direction = request.GET.get('dir', '')
    if direction == 'in':
        moves = moves.filter(change__gt=0)
    elif direction == 'out':
        moves = moves.filter(change__lt=0)

    page_obj = Paginator(moves, PER_PAGE)
    try:
        page_obj = page_obj.page(request.GET.get('page', 1))
    except (EmptyPage, PageNotAnInteger):
        page_obj = page_obj.page(1)

    for move in page_obj:
        unit = move.product.unit if move.product_id else units.PCS
        move.change_label = ('+' if move.change > 0 else '−') + units.show(abs(move.change), unit)
        move.after_label = units.show(move.stock_after, unit) if move.stock_after is not None else ''
        move.reason_label = REASON_LABELS.get(move.reason, move.reason)
        move.tone = REASON_TONE.get(move.reason, 'edit')
        move.link = _order_link(move)
        move.who = (move.user.name or move.user.phone_number) if move.user_id else ''

    keep = request.GET.copy()
    keep.pop('page', None)
    low = Product.objects.filter(low_stock_q(), shop=shop, is_active=True).count()
    return render(request, 'store/stock_history.html', {
        'page_obj': page_obj, 'product': product, 'reason': reason, 'direction': direction,
        'reasons': StockMovement.REASONS, 'query': keep.urlencode(), 'low_count': low,
        'filtered': bool(product or reason in REASON_LABELS or direction in ('in', 'out')),
    })
