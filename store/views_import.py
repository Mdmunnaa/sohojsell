"""
অন্য জায়গা থেকে আনুন — প্রোডাক্ট (Shopify, WooCommerce, যেকোনো Excel/CSV) আর কাস্টমারের তালিকা।

ধাপ: ফাইল তোলা → (দরকার হলে কলাম মেলানো) → দেখে নেওয়া: কয়টা আসবে, কোনগুলো কেন বাদ → নিশ্চিত করা →
প্রোডাক্ট সাথে সাথে তৈরি; ছবি লিংক থেকে পেছনে নামে (পাতায় অগ্রগতি দেখায়)। ফাইল পড়া store/product_import.py-তে।
"""
import ipaddress
import logging
import random
import socket
import string
import threading
from datetime import timedelta
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import product_import as pi
from .models import Category, Customer, ImportJob, Product, ProductVariant
from .plans import products_remaining

logger = logging.getLogger(__name__)
IMAGE_MAX_BYTES = 10 * 1024 * 1024
IMAGE_TIMEOUT = (6, 25)
STALE = timedelta(minutes=2)          # এতক্ষণ ছবির অগ্রগতি না হলে ধরে নেওয়া হয় কাজটা থেমে গেছে
KEEP_DAYS = 7

KINDS = {
    ImportJob.PRODUCTS: {'fields': pi.PRODUCT_FIELDS, 'job_url': 'product_import_job', 'start_url': 'product_import',
                         'list_url': 'product_list'},
    ImportJob.CUSTOMERS: {'fields': pi.CUSTOMER_FIELDS, 'job_url': 'customer_import_job', 'start_url': 'customer_import',
                          'list_url': 'customer_list'},
}


def _shop(request):
    return getattr(request.user, 'shop', None)


# ---------------------------------------------------------------- ফাইল তোলা
def _start(request, kind):
    shop = _shop(request)
    if shop is None:
        return redirect('setup_shop')
    if request.method == 'POST':
        upload = request.FILES.get('file')
        if not upload:
            messages.error(request, 'একটা ফাইল বেছে নিন (.xlsx বা .csv)।')
            return redirect(KINDS[kind]['start_url'])
        try:
            headers, rows = pi.read_table(upload)
        except pi.ImportError_ as exc:
            messages.error(request, str(exc))
            return redirect(KINDS[kind]['start_url'])
        if kind == ImportJob.PRODUCTS:
            source = pi.detect(headers)
            mapping = {} if source in ('shopify', 'woocommerce') else pi.guess_mapping(headers, pi.PRODUCT_FIELDS)
        else:
            source, mapping = 'generic', pi.customer_mapping(headers)
        job = ImportJob.objects.create(shop=shop, kind=kind, filename=upload.name[:200], source=source,
                                       headers=headers, rows=rows, mapping=mapping)
        return redirect(KINDS[kind]['job_url'], pk=job.pk)
    recent = ImportJob.objects.filter(shop=shop, kind=kind, status=ImportJob.DONE)[:5]
    return render(request, 'store/import/start.html', {'kind': kind, 'recent': recent,
                                                       'remaining': products_remaining(shop)})


@login_required(login_url='/accounts/login/')
def product_import(request):
    return _start(request, ImportJob.PRODUCTS)


@login_required(login_url='/accounts/login/')
def customer_import(request):
    return _start(request, ImportJob.CUSTOMERS)


# ---------------------------------------------------------------- দেখে নেওয়া আর নিশ্চিত করা
def _parse(job):
    if job.kind == ImportJob.PRODUCTS:
        mapping = {k: v for k, v in job.mapping.items()}
        return pi.parse_products(job.headers, job.rows, job.source, mapping)
    return pi.parse_customers(job.headers, job.rows, job.mapping)


def _missing(job):
    if job.kind == ImportJob.PRODUCTS and job.source in ('shopify', 'woocommerce'):
        return []
    return pi.missing_required(job.mapping, KINDS[job.kind]['fields'])


def _preview(job, shop):
    items, skipped = _parse(job)
    info = {'items': items, 'skipped': skipped}
    if job.kind == ImportJob.PRODUCTS:
        existing = set(Product.objects.filter(shop=shop).exclude(barcode=None).values_list('barcode', flat=True))
        dupes = [p for p in items if p['barcode'] and p['barcode'] in existing]
        fresh = [p for p in items if not (p['barcode'] and p['barcode'] in existing)]
        remaining = products_remaining(shop)
        will = fresh if remaining is None else fresh[:remaining]
        info.update({
            'dupes': dupes, 'will': len(will), 'over_limit': len(fresh) - len(will), 'remaining': remaining,
            'with_variants': sum(1 for p in will if p['variants']), 'images': sum(1 for p in will if p['image']),
            'stock_missing': sum(1 for p in will if not p['stock_known']),
            'inactive': sum(1 for p in will if not p['active']),
            'sample': will[:12],
        })
    else:
        existing = set(Customer.objects.filter(shop=shop).values_list('phone', flat=True))
        fresh = [c for c in items if c['phone'] not in existing]
        info.update({'dupes': [c for c in items if c['phone'] in existing], 'will': len(fresh), 'sample': fresh[:12]})
    return info


def _variant_barcode(sku, taken):
    if sku and sku not in taken:
        taken.add(sku)
        return sku
    while True:
        code = ''.join(random.choices(string.digits, k=12))
        if code not in taken:
            taken.add(code)
            return code


def _new_code(taken):
    while True:
        code = ''.join(random.choices(string.digits, k=12))
        if code not in taken:
            taken.add(code)
            return code


@transaction.atomic
def _create_products(job, shop):
    """একসাথে কয়েকটা query-তে (bulk) — হাজার প্রোডাক্টেও কয়েক সেকেন্ড; Product.save()-এর কাজ (বারকোড) এখানেই।"""
    items, skipped = _parse(job)
    existing = set(Product.objects.filter(shop=shop).exclude(barcode=None).values_list('barcode', flat=True))
    skus = [v['barcode'] for p in items for v in p['variants'] if v['barcode']]
    taken = set(ProductVariant.objects.filter(barcode__in=skus).values_list('barcode', flat=True))
    remaining = products_remaining(shop)
    categories = {c.name.lower(): c for c in Category.objects.filter(shop=shop)}
    over_limit = 0
    chosen, in_file, skipped = [], set(), [list(s) for s in skipped]
    for item in items:
        code = item['barcode']
        if code and code in existing:
            reason = 'একই বারকোড/SKU ফাইলে আগেও আছে' if code in in_file else 'এই বারকোড/SKU-র প্রোডাক্ট দোকানে আগে থেকে আছে'
            skipped.append([item['row'], item['name'], reason])
            continue
        if remaining is not None and len(chosen) >= remaining:
            over_limit += 1
            continue
        if code:
            existing.add(code)
            in_file.add(code)
        chosen.append(item)
    # বারকোড: ফাইলেরটা, না থাকলে নতুন (দোকানে একটাও মেলে না)
    for item in chosen:
        if not item['barcode']:
            item['barcode'] = _new_code(existing)
    for name in {i['category'] for i in chosen if i['category']}:
        if name.lower() not in categories:
            categories[name.lower()] = Category.objects.create(shop=shop, name=name)
    products = [Product(shop=shop, category=categories.get(i['category'].lower()) if i['category'] else None,
                        name=i['name'], description=i['description'], price=i['price'], cost_price=i['cost_price'] or 0,
                        compare_price=i['compare_price'], stock_quantity=i['stock'], barcode=i['barcode'],
                        is_active=i['active'], has_variants=bool(i['variants'])) for i in chosen]
    Product.objects.bulk_create(products, batch_size=500)
    variants, queue = [], []
    for item, product in zip(chosen, products):
        seen = set()
        for position, variant in enumerate(item['variants']):
            name = variant['name'] or f'#{position + 1}'
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            variants.append(ProductVariant(product=product, name=name, price=variant['price'],
                                           stock_quantity=variant['stock'], position=position,
                                           barcode=_variant_barcode(variant['barcode'], taken)))
        if item['image']:
            queue.append([product.pk, item['image']])
    ProductVariant.objects.bulk_create(variants, batch_size=1000)
    job.result = {'created': len(products), 'variants': len(variants), 'over_limit': over_limit,
                  'skipped_count': len(skipped), 'skipped': skipped[:100]}
    job.image_queue, job.images_total = queue, len(queue)
    job.status, job.finished_at = ImportJob.DONE, timezone.now()
    job.rows = []                     # ফাইলের সারি আর লাগে না
    job.save()


@transaction.atomic
def _create_customers(job, shop):
    items, skipped = _parse(job)
    existing = set(Customer.objects.filter(shop=shop).values_list('phone', flat=True))
    fresh = [c for c in items if c['phone'] not in existing]
    Customer.objects.bulk_create([Customer(shop=shop, name=c['name'], phone=c['phone'], address=c['address'])
                                  for c in fresh])
    job.result = {'created': len(fresh), 'exists': len(items) - len(fresh), 'skipped_count': len(skipped),
                  'skipped': [list(s) for s in skipped[:100]]}
    job.status, job.finished_at, job.rows = ImportJob.DONE, timezone.now(), []
    job.save()


@login_required(login_url='/accounts/login/')
def import_job(request, pk):
    shop = _shop(request)
    if shop is None:
        return redirect('setup_shop')
    kind = ImportJob.CUSTOMERS if request.resolver_match.url_name == 'customer_import_job' else ImportJob.PRODUCTS
    job = get_object_or_404(ImportJob, pk=pk, shop=shop, kind=kind)
    conf = KINDS[kind]
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'map' and job.status == ImportJob.NEW:
            mapping = {}
            for field, _label, _req, _aliases in conf['fields']:
                raw = request.POST.get(f'map_{field}', '')
                if raw.isdigit() and int(raw) < len(job.headers):
                    mapping[field] = int(raw)
            if kind == ImportJob.CUSTOMERS:
                for field in ('name', 'address'):      # Shopify-র জোড়া কলাম আগের মতো থাকুক, যদি বদলানো না হয়
                    if field not in mapping and isinstance(job.mapping.get(field), str) and request.POST.get(f'map_{field}') == 'auto':
                        mapping[field] = job.mapping[field]
            job.mapping = mapping
            if job.kind == ImportJob.PRODUCTS and job.source in ('shopify', 'woocommerce', 'sellpunch'):
                job.source = 'generic'
            job.save(update_fields=['mapping', 'source'])
            return redirect(conf['job_url'], pk=job.pk)
        if action == 'confirm' and job.status == ImportJob.NEW and not _missing(job):
            if kind == ImportJob.PRODUCTS:
                _create_products(job, shop)
                start_images(job.pk)
            else:
                _create_customers(job, shop)
            return redirect(conf['job_url'], pk=job.pk)
        if action == 'images' and job.status == ImportJob.DONE and job.images_left:
            start_images(job.pk)
            return redirect(conf['job_url'], pk=job.pk)
        return redirect(conf['job_url'], pk=job.pk)

    context = {'job': job, 'kind': kind, 'conf': conf, 'source_label': pi.SOURCE_LABELS.get(job.source, ''),
               'fields': conf['fields']}
    if job.status == ImportJob.NEW:
        missing = _missing(job)
        context['missing'] = missing
        context['columns'] = list(enumerate(job.headers))
        context['field_rows'] = [
            {'field': f, 'label': label, 'required': req, 'current': job.mapping.get(f)} for f, label, req, _a in conf['fields']]
        if not missing:
            context['info'] = _preview(job, shop)
    else:
        context['stalled'] = bool(job.images_left) and (
            job.images_started_at is None or timezone.now() - job.images_started_at > STALE)
    return render(request, 'store/import/job.html', context)


@login_required(login_url='/accounts/login/')
def import_status(request, pk):
    shop = _shop(request)
    job = get_object_or_404(ImportJob, pk=pk, shop=shop)
    return JsonResponse({'total': job.images_total, 'done': job.images_done, 'failed': job.images_failed,
                         'left': job.images_left})


# ---------------------------------------------------------------- ছবি নামানো (পেছনে)
def _public_host(host):
    """লিংকের ঠিকানা ইন্টারনেটের সাধারণ ঠিকানা কিনা — সার্ভারের ভেতরের বা লোকাল জায়গায় যেন না যায়।"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a.split('%')[0]).is_global for a in addresses)


def fetch_image(url):
    """(bytes, content_type) — শুধু http(s), সাধারণ ইন্টারনেটের ঠিকানা, ১০ MB পর্যন্ত, ছবি হলে।"""
    for _hop in range(4):
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or not _public_host(parsed.hostname):
            raise ValueError('লিংকটা খোলা যায় না')
        response = requests.get(url, timeout=IMAGE_TIMEOUT, stream=True, allow_redirects=False,
                                headers={'User-Agent': 'SellPunch-Importer/1.0'})
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get('Location'):
            url = urljoin(url, response.headers['Location'])
            response.close()
            continue
        if response.status_code != 200:
            raise ValueError(f'HTTP {response.status_code}')
        kind = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if kind and not kind.startswith('image/'):
            raise ValueError('ছবি নয়')
        data = b''
        for chunk in response.iter_content(64 * 1024):
            data += chunk
            if len(data) > IMAGE_MAX_BYTES:
                raise ValueError('ছবি অনেক বড়')
        return data, kind or 'image/jpeg'
    raise ValueError('অনেকবার অন্য জায়গায় পাঠাচ্ছে')


def run_images(job_id, own_thread=True):
    """সারির ক্রম ধরে ছবি নামিয়ে প্রোডাক্টে বসায়; থেমে গেলে আবার চালালে যেখানে থেমেছিল সেখান থেকে।"""
    try:
        job = ImportJob.objects.get(pk=job_id)
        queue = job.image_queue
        start = job.images_done + job.images_failed
        failed = list(job.result.get('image_failed', []))
        for product_id, url in queue[start:]:
            ok = False
            try:
                data, kind = fetch_image(url)
                product = Product.objects.filter(pk=product_id, shop_id=job.shop_id).first()
                if product is not None and not product.image:
                    extension = {'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif'}.get(kind, 'jpg')
                    product.image = SimpleUploadedFile(f'import-{product_id}.{extension}', data, content_type=kind)
                    product.save()
                    ok = bool(product.image)
                else:
                    ok = product is not None
            except Exception as exc:    # noqa: BLE001 — একটা ছবি না এলে বাকিগুলো থামবে না
                logger.info('import image %s failed: %s', url, exc)
            if ok:
                ImportJob.objects.filter(pk=job_id).update(images_done=F('images_done') + 1,
                                                           images_started_at=timezone.now())
            else:
                if len(failed) < 50:
                    failed.append(url)
                    ImportJob.objects.filter(pk=job_id).update(
                        images_failed=F('images_failed') + 1, images_started_at=timezone.now(),
                        result=_with(job.result, image_failed=failed))
                else:
                    ImportJob.objects.filter(pk=job_id).update(images_failed=F('images_failed') + 1,
                                                               images_started_at=timezone.now())
    except Exception:    # noqa: BLE001
        logger.exception('import images job %s stopped', job_id)
    finally:
        if own_thread:                    # নিজের thread-এর সংযোগ বন্ধ; অনুরোধের ভেতরে চললে ছুঁই না
            close_old_connections()


def _with(result, **extra):
    merged = dict(result)
    merged.update(extra)
    return merged


def start_images(job_id):
    """একই কাজ দুবার একসাথে না চলে — ২ মিনিট অগ্রগতি না থাকলে তবেই নতুন করে ধরে।"""
    now = timezone.now()
    claimed = ImportJob.objects.filter(pk=job_id).filter(
        Q(images_started_at__isnull=True) | Q(images_started_at__lt=now - STALE)).update(images_started_at=now)
    if not claimed:
        return False
    if getattr(settings, 'IMPORT_BACKGROUND', True):
        threading.Thread(target=run_images, args=(job_id,), daemon=True).start()
    else:
        run_images(job_id, own_thread=False)
    return True


def daily_cleanup():
    """রোজের cron: থেমে যাওয়া ছবির কাজ আবার চালানো, আর ৭ দিনের পুরনো কাজ মোছা।"""
    old = ImportJob.objects.filter(created_at__lt=timezone.now() - timedelta(days=KEEP_DAYS)).delete()[0]
    resumed = 0
    for job in ImportJob.objects.filter(status=ImportJob.DONE).only('id', 'images_total', 'images_done', 'images_failed')[:200]:
        if job.images_left and start_images(job.pk):
            resumed += 1
    return {'deleted': old, 'resumed': resumed}


def job_url(job):
    return reverse(KINDS[job.kind]['job_url'], args=[job.pk])
