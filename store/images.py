# store/images.py
"""
আপলোড করা ছবি ছোট করা — মোবাইল ডেটায় দোকানের ওয়েবসাইট যেন তাড়াতাড়ি খোলে।

- প্রোডাক্টের মূল ছবি: লম্বা দিক সর্বোচ্চ ১২০০px, JPEG (Facebook/WhatsApp প্রিভিউতেও চলে)
- প্রোডাক্টের ছোট ছবি (thumbnail): ৪৮০px, লিস্ট আর কার্টে দেখানোর জন্য
- ব্যানার: চওড়া সর্বোচ্চ ১৬০০px
- লোগো: ৫১২px; স্বচ্ছ (PNG) হলে PNG-ই থাকে

ফোনে তোলা ছবি অনেক সময় কাত হয়ে থাকে (EXIF), সেটাও সোজা করা হয়।
কোনো কারণে ছবি খোলা না গেলে আসলটাই রেখে দেওয়া হয়; ছবি ছোট করতে না পারায় সেভ আটকাবে না।
"""
import io
import logging
import os

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

PRODUCT_MAX = 1200
THUMB_MAX = 480
BANNER_MAX = 1600
LOGO_MAX = 512


def _open(file_field):
    from PIL import Image, ImageOps
    file_field.open('rb')
    try:
        file_field.seek(0)
    except Exception:
        pass
    image = Image.open(file_field)
    image.load()
    return ImageOps.exif_transpose(image)


def _has_alpha(image):
    return image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info)


def _flatten(image):
    """স্বচ্ছ অংশ সাদা করে RGB (JPEG-এ স্বচ্ছতা থাকে না, নাহলে কালো হয়ে যায়)।"""
    from PIL import Image
    if _has_alpha(image):
        image = image.convert('RGBA')
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        return background
    return image.convert('RGB')


def _resize(image, max_side):
    from PIL import Image
    image = image.copy()
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    return image


def _jpeg(image, quality):
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()


def _base_name(file_field):
    name = os.path.splitext(os.path.basename(file_field.name or 'image'))[0][:60]
    return name or 'image'


def product_versions(file_field):
    """
    (মূল ছবি, ছোট ছবি, (চওড়া, উঁচু)) — ছবি দুটো ContentFile; না পারলে (None, None, None)।
    মাপটা Facebook-কে আগেই বলে দিলে প্রথমবার শেয়ারেই ছবি দেখায়।
    """
    try:
        image = _flatten(_open(file_field))
    except Exception:
        logger.warning('Could not process product image %s', getattr(file_field, 'name', ''), exc_info=True)
        return None, None, None
    base = _base_name(file_field)
    big = _resize(image, PRODUCT_MAX)
    main = ContentFile(_jpeg(big, 82), name=f'{base}.jpg')
    thumb = ContentFile(_jpeg(_resize(image, THUMB_MAX), 78), name=f'{base}-thumb.jpg')
    return main, thumb, big.size


def banner_version(file_field):
    try:
        image = _flatten(_open(file_field))
    except Exception:
        logger.warning('Could not process banner %s', getattr(file_field, 'name', ''), exc_info=True)
        return None
    from PIL import Image
    if image.width > BANNER_MAX:
        image = image.resize((BANNER_MAX, round(image.height * BANNER_MAX / image.width)), Image.LANCZOS)
    return ContentFile(_jpeg(image, 82), name=f'{_base_name(file_field)}.jpg')


def logo_version(file_field):
    try:
        image = _open(file_field)
    except Exception:
        logger.warning('Could not process logo %s', getattr(file_field, 'name', ''), exc_info=True)
        return None
    base = _base_name(file_field)
    if _has_alpha(image):
        return ContentFile(_png(_resize(image.convert('RGBA'), LOGO_MAX)), name=f'{base}.png')
    return ContentFile(_jpeg(_resize(image.convert('RGB'), LOGO_MAX), 88), name=f'{base}.jpg')


def is_new_upload(file_field):
    """ফর্ম থেকে নতুন ছবি এসেছে, এখনো স্টোরেজে যায়নি।"""
    return bool(file_field) and not getattr(file_field, '_committed', True)
