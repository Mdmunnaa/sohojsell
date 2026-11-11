"""পাতা দ্রুত খোলার ছোট সাহায্য।"""
from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.utils.safestring import mark_safe

register = template.Library()


@lru_cache(maxsize=16)
def _read(path):
    found = finders.find(path)
    if not found:
        return ''
    with open(found, encoding='utf-8') as handle:
        return handle.read()


@register.simple_tag
def inline_static(path):
    """
    ছোট CSS পাতার ভেতরেই বসানো — আলাদা ফাইল নামার অপেক্ষায় পাতা আটকে থাকে না (PageSpeed-এর "render-blocking")।
    শুধু নিজের লেখা/বানানো ফাইলের জন্য, যেখানে relative url() নেই।
    """
    return mark_safe(_read(path))


@lru_cache(maxsize=256)
def _srcset(path, width):
    from django.templatetags.static import static
    stem, dot, ext = path.rpartition('.')
    parts = [f'{static(f"{stem}-{w}w.{ext}")} {w}w' for w in (390, 600, 900, 1200)
             if w < width and finders.find(f'{stem}-{w}w.{ext}')]
    parts.append(f'{static(path)} {width}w')
    return ', '.join(parts)


@register.simple_tag
def img_srcset(path, width):
    """
    ফোনে ছোট ছবি নামুক: 'landing/x.webp' আর তার ছোট সংস্করণগুলো (x-390w.webp ...) → srcset।
    ছোটগুলো বানায় tools/build_landing_images.py।
    """
    return _srcset(path, int(width))
