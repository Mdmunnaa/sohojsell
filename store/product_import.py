"""
অন্য জায়গা থেকে SellPunch-এ আসা: প্রোডাক্ট আর কাস্টমারের ফাইল পড়া।

চেনে:
- Shopify-র প্রোডাক্ট CSV (Products → Export) — Handle ধরে একই প্রোডাক্টের সারি এক করে, Option1-3 থেকে সাইজ-রং।
- WooCommerce-এর প্রোডাক্ট CSV (Products → Export) — simple / variable / variation, Parent দিয়ে জোড়া।
- SellPunch-এর নিজের CSV Template।
- যেকোনো Excel (.xlsx) বা CSV — প্রথম সারির কলামের নাম (বাংলা বা ইংরেজি) দেখে নিজে মেলায়; না মিললে সেলার বেছে দেন।
- কাস্টমার: নাম, মোবাইল, ঠিকানা (Shopify-র কাস্টমার CSV-ও)।

এখানে শুধু পড়া আর সাজানো — ডাটাবেসে কিছু লেখে না (store/views_import.py লেখে)।
"""
import csv
import html
import io
import re
from decimal import Decimal, InvalidOperation

MAX_ROWS = 5000
MAX_BYTES = 8 * 1024 * 1024
MAX_VARIANTS = 60
BN_DIGITS = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')


class ImportError_(Exception):
    """ফাইলটা পড়াই গেল না — সেলারকে দেখানোর মতো বাংলা বার্তা।"""


# ---------------------------------------------------------------- ফাইল পড়া
def read_table(uploaded):
    """(headers, rows) — rows হলো তালিকার তালিকা (সব লেখা)। .csv আর .xlsx চলে।"""
    name = (getattr(uploaded, 'name', '') or '').lower()
    if getattr(uploaded, 'size', 0) and uploaded.size > MAX_BYTES:
        raise ImportError_('ফাইলটা অনেক বড় (৮ MB-র বেশি)। ছোট ছোট ভাগে তুলুন।')
    data = uploaded.read()
    if name.endswith('.xls'):
        raise ImportError_('পুরনো .xls ফাইল চলে না। Excel-এ খুলে Save As → "Excel Workbook (.xlsx)" বা CSV করে তুলুন।')
    if name.endswith('.xlsx') or data[:2] == b'PK':
        table = _read_xlsx(data)
    else:
        table = _read_csv(data)
    table = [[_clean(cell) for cell in row] for row in table]
    table = [row for row in table if any(row)]
    if len(table) < 2:
        raise ImportError_('ফাইলে কোনো সারি পাওয়া যায়নি। প্রথম সারিতে কলামের নাম, তার নিচে প্রতিটা সারিতে একটা করে জিনিস থাকতে হবে।')
    headers = table[0]
    width = len(headers)
    rows = [(row + [''] * width)[:width] for row in table[1:MAX_ROWS + 1]]
    if len(table) - 1 > MAX_ROWS:
        raise ImportError_(f'একবারে {MAX_ROWS:,}টা সারি পর্যন্ত তোলা যায় — ফাইলটা ভাগ করে তুলুন।'.translate(
            str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')))
    return headers, rows


def _clean(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace('﻿', '').strip()


def _read_csv(data):
    for encoding in ('utf-8-sig', 'utf-16', 'cp1252'):
        try:
            text = data.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:
        raise ImportError_('ফাইলের লেখা পড়া গেল না। Excel-এ Save As → "CSV UTF-8" করে আবার তুলুন।')
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _read_xlsx(data):
    from openpyxl import load_workbook
    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:    # noqa: BLE001 — ভাঙা বা অন্য ধরনের ফাইল
        raise ImportError_('Excel ফাইলটা খোলা গেল না। .xlsx বা .csv ফাইল দিন।')
    sheet = book.worksheets[0]
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append(list(row))
        if len(rows) > MAX_ROWS + 1:
            break
    book.close()
    return rows


# ---------------------------------------------------------------- কলাম চেনা
def _key(header):
    """'Variant Price' → 'variant price', 'Body (HTML)' → 'body html', 'দাম*' → 'দাম'।"""
    return re.sub(r'[\s_\-()*.:/#\[\]]+', ' ', header.lower()).strip()


PRODUCT_FIELDS = [
    # (ঘর, বাংলা নাম, দরকারি?, যে নামগুলো চেনে)
    ('name', 'প্রোডাক্টের নাম', True, ['name', 'product name', 'title', 'product title', 'product', 'item', 'item name',
                                       'নাম', 'প্রোডাক্টের নাম', 'প্রোডাক্ট', 'পণ্যের নাম', 'পণ্য']),
    ('price', 'বিক্রির দাম', True, ['selling price', 'price', 'sale price', 'sell price', 'unit price', 'variant price',
                                   'retail price', 'rate', 'unit rate', 'বিক্রয় মূল্য', 'বিক্রির দাম', 'দাম', 'মূল্য',
                                   'বিক্রয়মূল্য', 'রেট']),
    ('compare_price', 'আগের দাম (ছাড়ের আগে)', False, ['compare at price', 'compare price', 'variant compare at price',
                                                      'old price', 'regular price', 'mrp', 'আগের দাম', 'এমআরপি']),
    ('cost_price', 'কেনা দাম', False, ['cost price', 'cost', 'cost per item', 'buying price', 'purchase price',
                                       'কেনা দাম', 'ক্রয় মূল্য', 'ক্রয়মূল্য', 'কেনার দাম']),
    ('stock', 'স্টক', False, ['stock quantity', 'stock', 'qty', 'quantity', 'inventory', 'variant inventory qty',
                              'স্টক', 'পরিমাণ', 'মজুদ', 'মজুত']),
    ('barcode', 'বারকোড / SKU', False, ['barcode', 'sku', 'variant sku', 'variant barcode', 'code', 'product code',
                                         'item code', 'বারকোড', 'কোড']),
    ('category', 'ক্যাটাগরি', False, ['category', 'categories', 'type', 'product type', 'product category',
                                      'ক্যাটাগরি', 'ধরন', 'বিভাগ']),
    ('description', 'বিবরণ', False, ['description', 'body html', 'body', 'details', 'short description',
                                     'বিবরণ', 'বর্ণনা']),
    ('image', 'ছবির লিংক', False, ['image', 'image url', 'image src', 'images', 'photo', 'picture', 'image link',
                                   'ছবি', 'ছবির লিংক']),
    ('option1', 'সাইজ', False, ['size', 'option1 value', 'variant', 'option', 'সাইজ', 'মাপ']),
    ('option2', 'রং', False, ['color', 'colour', 'option2 value', 'রং', 'রঙ', 'কালার']),
]

CUSTOMER_FIELDS = [
    ('name', 'নাম', True, ['name', 'customer name', 'full name', 'customer', 'নাম', 'কাস্টমারের নাম', 'ক্রেতার নাম']),
    ('phone', 'মোবাইল', True, ['phone', 'mobile', 'phone number', 'mobile number', 'contact', 'contact number',
                               'default address phone', 'cell', 'মোবাইল', 'ফোন', 'মোবাইল নম্বর', 'ফোন নম্বর', 'নম্বর']),
    ('address', 'ঠিকানা', False, ['address', 'full address', 'shipping address', 'default address address1', 'address1',
                                   'ঠিকানা']),
]


def guess_mapping(headers, fields):
    """{ঘর: কলামের ক্রম} — প্রতিটা ঘরের জন্য তালিকার আগের নামটা আগে খোঁজে, একটা কলাম একবারই।"""
    keys = [_key(h) for h in headers]
    used, mapping = set(), {}
    for field, _label, _required, aliases in fields:
        for alias in aliases:
            hit = next((i for i, k in enumerate(keys) if k == _key(alias) and i not in used), None)
            if hit is not None:
                mapping[field] = hit
                used.add(hit)
                break
    if fields is PRODUCT_FIELDS and 'price' not in mapping and 'compare_price' in mapping:
        mapping['price'] = mapping.pop('compare_price')      # শুধু "Regular price" থাকলে সেটাই বিক্রির দাম
    return mapping


def detect(headers):
    keys = {_key(h) for h in headers}
    if {'handle', 'title', 'variant price'} <= keys:
        return 'shopify'
    if {'type', 'name', 'regular price'} <= keys:
        return 'woocommerce'
    if {'name', 'selling price'} <= keys:
        return 'sellpunch'
    return 'generic'


SOURCE_LABELS = {'shopify': 'Shopify', 'woocommerce': 'WooCommerce', 'sellpunch': 'SellPunch-এর টেমপ্লেট',
                 'generic': 'Excel / CSV'}


def missing_required(mapping, fields):
    return [label for field, label, required, _a in fields if required and field not in mapping]


# ---------------------------------------------------------------- মান পরিষ্কার
def money(text):
    """'৳ 1,450.00' / 'Tk. ১৪৫০' / '1450 BDT' → Decimal; খালি বা ভুল হলে None।"""
    text = (text or '').translate(BN_DIGITS)
    text = re.sub(r'(?i)\b(bdt|tk|taka)\b|[৳$,\s]|টাকা', '', text).strip('.')
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value.quantize(Decimal('0.01')) if value >= 0 else None


def whole(text):
    value = money(text)
    return int(value) if value is not None else None


def plain_text(value):
    """HTML (Shopify/WooCommerce-এর বিবরণ) → সাধারণ লেখা, লাইন ভেঙে।"""
    if not value:
        return ''
    text = re.sub(r'(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>', '\n', value)
    text = re.sub(r'(?i)<li[^>]*>', '• ', text)
    text = html.unescape(re.sub(r'<[^>]+>', '', text))
    text = text.replace('\\n', '\n')
    lines = [' '.join(line.split()) for line in text.splitlines()]
    return '\n'.join(line for line in lines if line).strip()[:5000]


def first_url(value):
    for part in re.split(r'[,\s|]+', value or ''):
        if re.match(r'(?i)^https?://\S+$', part):
            return part[:500]
    return ''


def category_name(value):
    """'Clothing > Shirts, Sale' → 'Shirts'।"""
    first = (value or '').split(',')[0]
    return first.split('>')[-1].strip()[:100]


def phone_number(value):
    """+880 1712-345678 / 8801712345678 / ০১৭১২৩৪৫৬৭৮ → 01712345678; না হলে ''।"""
    digits = re.sub(r'\D', '', (value or '').translate(BN_DIGITS))
    if digits.startswith('00'):
        digits = digits[2:]
    if digits.startswith('880'):
        digits = digits[2:]
    elif digits.startswith('88') and len(digits) == 13:
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith('1'):
        digits = '0' + digits
    return digits if re.fullmatch(r'01[3-9]\d{8}', digits) else ''


def _new(name):
    return {'name': name[:200], 'price': None, 'compare_price': None, 'cost_price': None, 'stock': 0, 'barcode': '',
            'category': '', 'description': '', 'image': '', 'active': True, 'variants': [], 'row': 0,
            'stock_known': True}


def _finish(product, skipped):
    """দাম ঠিক না থাকলে বাদ; ভ্যারিয়েন্ট থাকলে মোট স্টক আর প্রোডাক্টের দাম ভ্যারিয়েন্ট থেকে।"""
    variants = product['variants']
    if len(variants) > MAX_VARIANTS:
        product['variants'] = variants = variants[:MAX_VARIANTS]
    if variants:
        prices = [v['price'] for v in variants if v['price'] is not None]
        if product['price'] is None and prices:
            product['price'] = min(prices)
        product['stock'] = sum(v['stock'] or 0 for v in variants)
        if len(variants) == 1 and variants[0]['name'].lower() in ('default title', 'default', ''):
            only = variants[0]
            product['price'] = only['price'] if only['price'] is not None else product['price']
            product['barcode'] = product['barcode'] or only['barcode']
            product['variants'] = []
    if product['price'] is None:
        skipped.append((product['row'], product['name'] or '—', 'দাম নেই বা দাম সংখ্যায় লেখা নেই'))
        return None
    if product['compare_price'] is not None and product['compare_price'] <= product['price']:
        product['compare_price'] = None
    for variant in product['variants']:
        if variant['price'] == product['price']:
            variant['price'] = None          # প্রোডাক্টের দামই — আলাদা করে রাখার দরকার নেই
    return product


# ---------------------------------------------------------------- প্রোডাক্ট: প্রতিটা ফরম্যাট
def parse_products(headers, rows, source, mapping=None):
    """(products, skipped) — skipped: [(সারি নং, নাম, কারণ)]।"""
    if source == 'shopify':
        return _shopify(headers, rows)
    if source == 'woocommerce':
        return _woocommerce(headers, rows)
    return _generic(headers, rows, mapping if mapping is not None else guess_mapping(headers, PRODUCT_FIELDS))


def _col(headers):
    index = {}
    for i, header in enumerate(headers):
        index.setdefault(_key(header), i)
    return lambda row, *names: next((row[index[_key(n)]] for n in names if _key(n) in index and row[index[_key(n)]]), '')


def _shopify(headers, rows):
    get = _col(headers)
    products, order, skipped = {}, [], []
    for number, row in enumerate(rows, start=2):
        handle = get(row, 'Handle')
        if not handle:
            continue
        product = products.get(handle)
        if product is None:
            product = products[handle] = _new(get(row, 'Title') or handle)
            product['row'] = number
            order.append(handle)
        if get(row, 'Title') and not product['description']:
            product.update({
                'name': get(row, 'Title')[:200], 'description': plain_text(get(row, 'Body (HTML)', 'Body HTML')),
                'category': category_name(get(row, 'Type') or get(row, 'Product Category')),
                'active': get(row, 'Status').lower() not in ('draft', 'archived') and
                get(row, 'Published').upper() not in ('FALSE', '0', 'NO'),
            })
        if not product['image']:
            product['image'] = first_url(get(row, 'Image Src', 'Variant Image'))
        options = [get(row, f'Option{i} Value') for i in (1, 2, 3)]
        if any(options) or get(row, 'Variant Price'):
            price = money(get(row, 'Variant Price'))
            compare = money(get(row, 'Variant Compare At Price'))
            if compare and (product['compare_price'] is None or compare > product['compare_price']):
                product['compare_price'] = compare
            cost = money(get(row, 'Cost per item'))
            if cost is not None and product['cost_price'] is None:
                product['cost_price'] = cost
            qty = whole(get(row, 'Variant Inventory Qty', 'Inventory Qty'))
            if qty is None:
                product['stock_known'] = False
            product['variants'].append({
                'name': ' / '.join(o for o in options if o)[:80], 'price': price, 'stock': qty or 0,
                'barcode': (get(row, 'Variant Barcode') or get(row, 'Variant SKU'))[:50],
            })
    result = []
    for handle in order:
        product = _finish(products[handle], skipped)
        if product:
            result.append(product)
    return result, skipped


def _woocommerce(headers, rows):
    get = _col(headers)
    keys = [_key(h) for h in headers]
    attr_cols = sorted(i for i, k in enumerate(keys) if re.fullmatch(r'attribute \d+ value s', k))
    parents, by_ref, result_order, skipped = {}, {}, [], []
    for number, row in enumerate(rows, start=2):
        kind = get(row, 'Type').lower()
        name = get(row, 'Name')
        if 'variation' in kind:
            parent_ref = get(row, 'Parent')
            parent = by_ref.get(parent_ref) or by_ref.get(parent_ref.replace('id:', ''))
            if parent is None:
                skipped.append((number, name or '—', 'কোন প্রোডাক্টের সাইজ-রং, তা মেলেনি (Parent)'))
                continue
            regular, sale = money(get(row, 'Regular price')), money(get(row, 'Sale price'))
            values = [row[i] for i in attr_cols if row[i]]
            qty = whole(get(row, 'Stock'))
            if qty is None:
                parent['stock_known'] = False
            parent['variants'].append({
                'name': (' / '.join(values) or name)[:80], 'price': sale or regular,
                'stock': qty or 0, 'barcode': get(row, 'SKU')[:50]})
            if sale and regular and regular > sale and (parent['compare_price'] is None or regular > parent['compare_price']):
                parent['compare_price'] = regular
            continue
        if kind and not any(t in kind for t in ('simple', 'variable')):
            skipped.append((number, name or '—', f'এই ধরনের প্রোডাক্ট ({kind}) আনা যায় না'))
            continue
        if not name:
            skipped.append((number, '—', 'নাম নেই'))
            continue
        product = _new(name)
        product['row'] = number
        regular, sale = money(get(row, 'Regular price')), money(get(row, 'Sale price'))
        stock = whole(get(row, 'Stock'))
        product.update({
            'price': sale or regular, 'compare_price': regular if sale and regular and regular > sale else None,
            'stock': stock or 0, 'stock_known': stock is not None or 'variable' in kind, 'barcode': get(row, 'SKU')[:50], 'category': category_name(get(row, 'Categories')),
            'description': plain_text(get(row, 'Description') or get(row, 'Short description')),
            'image': first_url(get(row, 'Images')), 'active': get(row, 'Published') not in ('0', '-1'),
        })
        result_order.append(product)
        for ref in (get(row, 'ID'), get(row, 'SKU')):
            if ref:
                by_ref[ref] = product
                by_ref[f'id:{ref}'] = product
        parents[number] = product
    result = []
    for product in result_order:
        product = _finish(product, skipped)
        if product:
            result.append(product)
    return result, skipped


def _generic(headers, rows, mapping):
    def value(row, field):
        index = mapping.get(field)
        return row[index] if index is not None and index < len(row) else ''
    grouped = 'option1' in mapping or 'option2' in mapping
    products, by_name, skipped = [], {}, []
    for number, row in enumerate(rows, start=2):
        name = value(row, 'name')[:200]
        if not name:
            skipped.append((number, '—', 'নাম নেই'))
            continue
        price = money(value(row, 'price'))
        options = [value(row, 'option1'), value(row, 'option2')]
        if grouped and any(options):
            product = by_name.get(name.lower())
            if product is None:
                product = by_name[name.lower()] = _base_from(row, value, name, number)
                product['price'] = None
                products.append(product)
            qty = whole(value(row, 'stock'))
            if qty is None:
                product['stock_known'] = False
            product['variants'].append({'name': ' / '.join(o for o in options if o)[:80], 'price': price,
                                        'stock': qty or 0, 'barcode': value(row, 'barcode')[:50]})
            continue
        product = _base_from(row, value, name, number)
        product['price'] = price
        products.append(product)
    result = []
    for product in products:
        product = _finish(product, skipped)
        if product:
            result.append(product)
    return result, skipped


def _base_from(row, value, name, number):
    product = _new(name)
    stock = whole(value(row, 'stock'))
    product.update({
        'row': number, 'compare_price': money(value(row, 'compare_price')), 'cost_price': money(value(row, 'cost_price')),
        'stock': stock or 0, 'stock_known': stock is not None, 'barcode': value(row, 'barcode')[:50],
        'category': category_name(value(row, 'category')), 'description': plain_text(value(row, 'description')),
        'image': first_url(value(row, 'image')),
    })
    return product


# ---------------------------------------------------------------- কাস্টমার
def customer_mapping(headers):
    """Shopify-র কাস্টমার CSV হলে নামের দুই কলাম আর ঠিকানার কয়েক কলাম জোড়া লাগে — তাই আলাদা চিহ্ন।"""
    keys = [_key(h) for h in headers]
    mapping = guess_mapping(headers, CUSTOMER_FIELDS)
    if 'name' not in mapping and 'first name' in keys:
        mapping['name'] = 'first+last'
    if 'phone' not in mapping and 'default address phone' in keys:
        mapping['phone'] = keys.index('default address phone')
    if any(k in keys for k in ('default address address1', 'address1')):
        mapping['address'] = 'shopify'
    return mapping


def parse_customers(headers, rows, mapping):
    """(customers, skipped) — একই ফাইলে একই নম্বর দুবার হলে প্রথমটা থাকে।"""
    keys = [_key(h) for h in headers]

    def column(row, key):
        return row[keys.index(key)] if key in keys else ''

    def value(row, field):
        index = mapping.get(field)
        if index == 'first+last':
            return ' '.join(p for p in (column(row, 'first name'), column(row, 'last name')) if p)
        if index == 'shopify':
            prefix = 'default address ' if 'default address address1' in keys else ''
            parts = [column(row, prefix + k) for k in ('address1', 'address2', 'city')]
            return ', '.join(p for p in parts if p)
        return row[index] if isinstance(index, int) and index < len(row) else ''

    customers, seen, skipped = [], set(), []
    for number, row in enumerate(rows, start=2):
        name = ' '.join(value(row, 'name').split())[:150]
        raw_phone = value(row, 'phone')
        phone = phone_number(raw_phone)
        if not phone:
            skipped.append((number, name or '—', f'মোবাইল নম্বর ঠিক নেই ({raw_phone[:20] or "খালি"})'))
            continue
        if phone in seen:
            skipped.append((number, name or phone, 'একই নম্বর ফাইলে আগেও আছে'))
            continue
        seen.add(phone)
        customers.append({'row': number, 'name': name or phone, 'phone': phone,
                          'address': ' '.join(value(row, 'address').split())[:500]})
    return customers, skipped
