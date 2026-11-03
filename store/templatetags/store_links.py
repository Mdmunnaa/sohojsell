from django import template

from store.links import storefront_link

register = template.Library()


@register.simple_tag(takes_context=True)
def shop_url(context, name, shop, *args):
    """{% shop_url 'storefront_product_detail' shop product.id %} → দোকানের সাবডোমেইনের লিংক।"""
    return storefront_link(shop, name, *args, request=context.get('request'))
