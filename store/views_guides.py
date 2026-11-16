"""
গাইড সেন্টার: /guide/ (সব গাইড, খোঁজার ঘরসহ) আর /guide/<slug>/ (একটা গাইড)। লেখা store/guide_content/*.md, ইঞ্জিন store/guides.py।
চেহারা SEO পাতার মতো (store/marketing/base.html) — একই ন্যাভ, ফুটার, ফন্ট। শুধু বাংলায়।
"""
import json
from datetime import date

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from . import guides, seo
from .views_marketing import UI, _cards, _min_price
from . import marketing


def _ld(graph):
    return json.dumps({'@context': 'https://schema.org', '@graph': graph}, ensure_ascii=False)


def _context(request, *, path, title, description, crumbs, graph):
    base = seo.main_site_url(request)
    canonical = base + path
    graph = [
        {'@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': i, 'name': name, 'item': base + url}
            for i, (name, url) in enumerate(crumbs, start=1)]},
    ] + graph
    return {
        'lang': 'bn', 'ui': UI['bn'], 'title': title, 'description': description, 'crumbs': crumbs,
        'mk_seo': {'canonical': canonical, 'url_bn': canonical, 'url_en': '', 'base': base, 'other_url': '', 'ld': _ld(graph)},
        'home_url': '/', 'index_url': reverse('mk_index'), 'min_price': _min_price(),
        'feature_links': _cards(marketing.FEATURES, 'feature', 'bn'),
        'industry_links': _cards(marketing.INDUSTRIES, 'industry', 'bn'),
        'guide_index_url': reverse('guide_index'),
    }


POPULAR = [('getting-started', 'দোকান খোলা'), ('products', 'প্রোডাক্ট যোগ'), ('pos', 'POS-এ বিক্রি'),
           ('courier', 'কুরিয়ারে পাঠানো'), ('website', 'ওয়েবসাইট')]

INDEX_TITLE = 'SellPunch গাইড সেন্টার — ছবিসহ ধাপে ধাপে সব নিয়ম'
INDEX_DESCRIPTION = ('অনলাইন দোকান খোলা, প্রোডাক্ট যোগ, POS-এ বিক্রি, অর্ডার, Steadfast/Pathao/RedX কুরিয়ার, ওয়েবসাইট, '
                     'ল্যান্ডিং পেজ, বাকির খাতা আর হিসাব — SellPunch-এর প্রতিটা অপশন ছবিসহ বাংলায়।')


def guide_index(request):
    path = reverse('guide_index')
    all_guides = guides.all_guides()
    base = seo.main_site_url(request)
    graph = [
        {'@type': 'CollectionPage', '@id': base + path + '#page', 'url': base + path, 'name': INDEX_TITLE,
         'description': INDEX_DESCRIPTION, 'inLanguage': 'bn', 'isPartOf': {'@id': base + '/#website'},
         'about': {'@id': base + '/#software'}, 'publisher': {'@id': base + '/#org'},
         'mainEntity': {'@type': 'ItemList', 'itemListElement': [
             {'@type': 'ListItem', 'position': i, 'name': g['title'],
              'url': base + reverse('guide_detail', args=[g['slug']])} for i, g in enumerate(all_guides, start=1)]}},
    ]
    context = _context(request, path=path, title=INDEX_TITLE, description=INDEX_DESCRIPTION,
                       crumbs=[('হোম', '/'), ('গাইড সেন্টার', path)], graph=graph)
    seller_guides = [g for g in all_guides if g['category'] != guides.BUYER_CATEGORY]
    context.update({
        'seller_guides': seller_guides,
        'seller_categories': list(dict.fromkeys(g['category'] for g in seller_guides)),
        'buyer_guides': [g for g in all_guides if g['category'] == guides.BUYER_CATEGORY],
        'guide_count': len(all_guides),
        'shot_count': sum(g['shots'] for g in all_guides),
        # </script> যেন লেখার ভেতর থেকে স্ক্রিপ্ট বন্ধ করতে না পারে
        'search_json': json.dumps(guides.search_index(), ensure_ascii=False).replace('<', '\\u003c'),
        'popular': [dict(guides.get_guide(slug), label=label) for slug, label in POPULAR],
    })
    return render(request, 'store/guides/index.html', context)


def guide_detail(request, slug):
    guide = guides.get_guide(slug)
    if guide is None:
        raise Http404('গাইড পাওয়া যায়নি')
    path = reverse('guide_detail', args=[slug])
    base = seo.main_site_url(request)
    url = base + path
    images = [base + guides.shot_url(shot_id) for shot_id, _alt in guides.guide_images(guide)]
    article = {
        '@type': 'TechArticle', '@id': url + '#article', 'headline': guide['title'], 'url': url, 'inLanguage': 'bn',
        'description': guide['summary'], 'dateModified': guides.GUIDES_UPDATED,
        'author': {'@id': base + '/#org'}, 'publisher': {'@id': base + '/#org'},
        'about': {'@id': base + '/#software'}, 'isPartOf': {'@id': base + '/#website'},
    }
    if images:
        article['image'] = images
    graph = [article]
    faq = guides.guide_faq(guide)
    if faq:
        graph.append({'@type': 'FAQPage', 'mainEntity': [
            {'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in faq]})
    context = _context(request, path=path, title=guide['seo_title'], description=guide['summary'],
                       crumbs=[('হোম', '/'), ('গাইড সেন্টার', reverse('guide_index')), (guide['title'], path)], graph=graph)
    ordered = guides.all_guides()
    index = next(i for i, g in enumerate(ordered) if g['slug'] == slug)
    others = [g for g in ordered if g['slug'] != slug]
    same = [g for g in others if g['category'] == guide['category']]
    from .marketing import facebook_live
    context.update({
        'guide': guide, 'fb_pending': slug == 'facebook-automation' and not facebook_live(),
        'content_html': guides.render_guide_html(guide),
        'guide_toc': guides.guide_toc(guide),
        'guides_updated': guides.GUIDES_UPDATED,
        'guides_updated_date': date.fromisoformat(guides.GUIDES_UPDATED),
        'prev_guide': ordered[index - 1] if index > 0 else None,
        'next_guide': ordered[index + 1] if index + 1 < len(ordered) else None,
        'related_guides': (same + [g for g in others if g not in same])[:3],
    })
    return render(request, 'store/guides/detail.html', context)
