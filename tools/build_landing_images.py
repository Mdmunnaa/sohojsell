"""
হোমপেজের স্ক্রিনশটের ছোট সংস্করণ (ফোনের জন্য) — store/static/landing/<নাম>-<প্রস্থ>w.webp
নতুন ছবি যোগ/বদল করলে চালান: python tools/build_landing_images.py   (Pillow লাগে)
টেমপ্লেটে: <img src="{% static 'landing/x.webp' %}" srcset="{% img_srcset 'landing/x.webp' 1800 %}" sizes="...">
"""
import re
from pathlib import Path

from PIL import Image

FOLDER = Path(__file__).resolve().parent.parent / 'store' / 'static' / 'landing'
WIDTHS = (390, 600, 900, 1200)


def main():
    for path in sorted(FOLDER.glob('*.webp')):
        if re.search(r'-\d+w\.webp$', path.name):
            continue
        with Image.open(path) as image:
            image = image.convert('RGB')
            for width in WIDTHS:
                if width >= image.width:
                    continue
                out = path.with_name(f'{path.stem}-{width}w.webp')
                height = round(image.height * width / image.width)
                image.resize((width, height), Image.LANCZOS).save(out, 'WEBP', quality=78, method=6)
                print(out.name, out.stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
