"""
অন্য প্ল্যাটফর্মে চলে যেতে চাইলে: প্রোডাক্টের CSV — Shopify আর WooCommerce-এর Import যেভাবে চায়।

সেটিংস → ডাটা ও ব্যাকআপ থেকে মালিক নামান (মেয়াদ শেষে লক থাকলেও — subscription_middleware)। ছবি যায় পুরো লিংক হিসেবে;
দুটো প্ল্যাটফর্মই Import-এর সময় লিংক থেকে ছবি নিজে নামিয়ে নেয়। সাইজ-রং থাকলে প্রতিটা আলাদা ভ্যারিয়েন্ট।

- Shopify: https://help.shopify.com/en/manual/products/import-export/using-csv
- WooCommerce: Products → Import (built-in CSV importer)
"""
import csv
import io
import re
from decimal import Decimal

from django.utils.html import escape
from django.utils.text import slugify

SHOPIFY_COLUMNS = [
    'Handle', 'Title', 'Body (HTML)', 'Vendor', 'Type', 'Tags', 'Published', 'Option1 Name', 'Option1 Value',
    'Variant SKU', 'Variant Grams', 'Variant Inventory Tracker', 'Variant Inventory Qty', 'Variant Inventory Policy',
    'Variant Fulfillment Service', 'Variant Price', 'Variant Compare At Price', 'Variant Requires Shipping',
    'Variant Taxable', 'Variant Barcode', 'Image Src', 'Image Position', 'Image Alt Text', 'Gift Card',
    'Cost per item', 'Status',
]
WOO_COLUMNS = [
    'ID', 'Type', 'SKU', 'Name', 'Published', 'Is featured?', 'Visibility in catalog', 'Short description',
    'Description', 'Tax status', 'In stock?', 'Stock', 'Regular price', 'Sale price', 'Categories', 'Images',
    'Parent', 'Attribute 1 name', 'Attribute 1 value(s)', 'Attribute 1 visible', 'Attribute 1 global',
]


def _money(value):
    if value in (None, ''):
        return ''
    return f'{Decimal(value):.2f}'


def _handle(product):
    """URL-এর নাম: ইংরেজি অক্ষর থাকলে সেটা, সাথে আইডি (বাংলা নামেও ফাঁকা হয় না, দুটো এক হয় না)।"""
    slug = slugify(product.name)[:60].strip('-')
    return f'{slug}-{product.id}' if slug else f'product-{product.id}'


def _html(text):
    text = (text or '').strip()
    if not text:
        return ''
    return '<p>' + '<br>'.join(escape(line) for line in text.splitlines()) + '</p>'


def _products(shop):
    return (shop.products.select_related('category').prefetch_related('variants').order_by('id'))


def _csv(columns, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def shopify_csv(shop, absolute):
    rows = []
    for product in _products(shop):
        handle = _handle(product)
        image = absolute(product.image.url) if product.image else ''
        base = {
            'Handle': handle, 'Title': product.name, 'Body (HTML)': _html(product.description), 'Vendor': shop.name,
            'Type': product.category.name if product.category else '', 'Tags': '',
            'Published': 'TRUE' if product.is_active else 'FALSE', 'Gift Card': 'FALSE',
            'Image Src': image, 'Image Position': '1' if image else '', 'Image Alt Text': product.name if image else '',
            'Status': 'active' if product.is_active else 'draft',
        }
        common = {
            'Variant Grams': '0', 'Variant Inventory Tracker': 'shopify', 'Variant Inventory Policy': 'deny',
            'Variant Fulfillment Service': 'manual', 'Variant Requires Shipping': 'TRUE', 'Variant Taxable': 'FALSE',
            'Variant Compare At Price': _money(product.compare_price), 'Cost per item': _money(product.cost_price),
        }
        variants = list(product.variants.all())
        if not variants:
            rows.append({**base, **common, 'Option1 Name': 'Title', 'Option1 Value': 'Default Title',
                         'Variant SKU': product.barcode or '', 'Variant Barcode': product.barcode or '',
                         'Variant Inventory Qty': product.stock_quantity, 'Variant Price': _money(product.price)})
            continue
        for index, variant in enumerate(variants):
            row = dict(base) if index == 0 else {'Handle': handle}
            row.update(common)
            row.update({'Option1 Name': 'Option' if index == 0 else '', 'Option1 Value': variant.name,
                        'Variant SKU': variant.barcode, 'Variant Barcode': variant.barcode,
                        'Variant Inventory Qty': variant.stock_quantity,
                        'Variant Price': _money(variant.price if variant.price is not None else product.price)})
            rows.append(row)
    return _csv(SHOPIFY_COLUMNS, rows)


def _woo_prices(price, compare):
    """WooCommerce-এ Regular = আগের (বেশি) দাম, Sale = এখনকার দাম — ছাড় থাকলে।"""
    if compare and Decimal(compare) > Decimal(price):
        return _money(compare), _money(price)
    return _money(price), ''


def woocommerce_csv(shop, absolute):
    rows = []
    for product in _products(shop):
        sku = product.barcode or _handle(product)
        image = absolute(product.image.url) if product.image else ''
        variants = list(product.variants.all())
        base = {
            'Name': product.name, 'Published': '1' if product.is_active else '0', 'Is featured?': '0',
            'Visibility in catalog': 'visible', 'Description': _html(product.description), 'Tax status': 'none',
            'Categories': product.category.name if product.category else '', 'Images': image, 'SKU': sku,
        }
        if not variants:
            regular, sale = _woo_prices(product.price, product.compare_price)
            rows.append({**base, 'Type': 'simple', 'In stock?': '1' if product.stock_quantity else '0',
                         'Stock': product.stock_quantity, 'Regular price': regular, 'Sale price': sale})
            continue
        names = [re.sub(r'\s*,\s*', ' / ', v.name) for v in variants]   # WooCommerce-এ কমা মানে আলাদা মান
        rows.append({**base, 'Type': 'variable', 'Attribute 1 name': 'Option',
                     'Attribute 1 value(s)': ', '.join(names), 'Attribute 1 visible': '1', 'Attribute 1 global': '0'})
        for variant, name in zip(variants, names):
            price = variant.price if variant.price is not None else product.price
            regular, sale = _woo_prices(price, product.compare_price)
            rows.append({'Type': 'variation', 'SKU': variant.barcode or f'{sku}-{variant.id}', 'Name': f'{product.name} - {name}',
                         'Published': '1', 'Tax status': 'none', 'In stock?': '1' if variant.stock_quantity else '0',
                         'Stock': variant.stock_quantity, 'Regular price': regular, 'Sale price': sale, 'Parent': sku,
                         'Attribute 1 name': 'Option', 'Attribute 1 value(s)': name, 'Attribute 1 visible': '1',
                         'Attribute 1 global': '0'})
    return _csv(WOO_COLUMNS, rows)
