# store/themes.py
"""
দোকানের ওয়েবসাইটের চেহারা: ডিজাইন (লেআউটের ধরন) আর রঙ — দুটো আলাদা করে বাছা যায়।

রঙ: প্রতিটা থিমে primary (বাটন, দাম), dark (hover), light (হালকা ব্যাকগ্রাউন্ড), second (গ্রেডিয়েন্টের
দ্বিতীয় রঙ), rgb (ছায়ার জন্য primary-র RGB)। সেলার নিজের রঙ (#RRGGBB) দিলে বাকিগুলো সেখান থেকে বানানো হয়।
ডিজাইন: একই HTML, আলাদা CSS (store/templates/store/storefront/_theme.html)।
"""
import re

DEFAULT_THEME = 'orange'
DEFAULT_DESIGN = 'classic'

THEMES = {
    'orange': {'label': 'কমলা', 'hint': 'সব ধরনের দোকান',
               'primary': '#F57224', 'dark': '#D85C14', 'light': '#FFF3EB', 'second': '#FF8C42', 'rgb': '245,114,36'},
    'green':  {'label': 'সবুজ', 'hint': 'গ্রোসারি, অর্গানিক, খাবার',
               'primary': '#16A34A', 'dark': '#15803D', 'light': '#ECFDF5', 'second': '#22C55E', 'rgb': '22,163,74'},
    'blue':   {'label': 'নীল', 'hint': 'ইলেকট্রনিক্স, গ্যাজেট',
               'primary': '#2563EB', 'dark': '#1D4ED8', 'light': '#EFF6FF', 'second': '#3B82F6', 'rgb': '37,99,235'},
    'pink':   {'label': 'গোলাপি', 'hint': 'ফ্যাশন, কসমেটিকস',
               'primary': '#DB2777', 'dark': '#BE185D', 'light': '#FDF2F8', 'second': '#EC4899', 'rgb': '219,39,119'},
    'purple': {'label': 'বেগুনি', 'hint': 'গিফট, হ্যান্ডমেড',
               'primary': '#7C3AED', 'dark': '#6D28D9', 'light': '#F5F3FF', 'second': '#8B5CF6', 'rgb': '124,58,237'},
    'black':  {'label': 'কালো', 'hint': 'প্রিমিয়াম, মিনিমাল',
               'primary': '#111827', 'dark': '#000000', 'light': '#F3F4F6', 'second': '#374151', 'rgb': '17,24,39'},
}

THEME_CHOICES = [(key, value['label']) for key, value in THEMES.items()]

DESIGNS = {
    'classic': {'label': 'ক্লাসিক', 'hint': 'পরিচিত অনলাইন শপের মতো, সব ধরনের দোকানে মানায়'},
    'minimal': {'label': 'মিনিমাল', 'hint': 'সাদা, ছিমছাম, বড় ছবি। ফ্যাশন আর বুটিকের জন্য'},
    'bold':    {'label': 'বোল্ড', 'hint': 'রঙিন হেডার, বড় বাটন। অফার আর গ্যাজেটের দোকানে'},
    'soft':    {'label': 'সফট', 'hint': 'হালকা রঙের পটভূমি, গোল কার্ড। কসমেটিকস, গিফট, খাবার'},
}
DESIGN_CHOICES = [(key, value['label']) for key, value in DESIGNS.items()]

HEX_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
MIN_CONTRAST_ON_WHITE = 3.0     # বাটনের সাদা লেখা পড়া যেতে হবে


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(c))):02X}' for c in rgb)


def _mix(rgb, other, amount):
    """rgb থেকে other-এর দিকে amount (০–১) ভাগ সরানো।"""
    return tuple(a + (b - a) * amount for a, b in zip(rgb, other))


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_on_white(rgb):
    return 1.05 / (_luminance(rgb) + 0.05)


def clean_hex(value):
    """'#f57224' বা 'F57224' → '#F57224'; ভুল হলে ''।"""
    value = (value or '').strip()
    if value and not value.startswith('#'):
        value = '#' + value
    return value.upper() if HEX_RE.match(value) else ''


def palette_from_hex(hex_color):
    """সেলারের দেওয়া একটা রঙ থেকে পুরো থিম। খুব হালকা রঙ হলে সাদা লেখা পড়ার মতো গাঢ় করে নেওয়া হয়।"""
    rgb = _rgb(hex_color)
    for _ in range(40):
        if contrast_on_white(rgb) >= MIN_CONTRAST_ON_WHITE:
            break
        rgb = _mix(rgb, (0, 0, 0), 0.06)
    rgb = tuple(round(c) for c in rgb)
    return {'label': 'নিজের রঙ', 'hint': '', 'primary': _hex(rgb), 'dark': _hex(_mix(rgb, (0, 0, 0), 0.16)),
            'light': _hex(_mix(rgb, (255, 255, 255), 0.92)), 'second': _hex(_mix(rgb, (255, 255, 255), 0.16)),
            'rgb': ','.join(str(c) for c in rgb)}


def theme_for(key, custom_color=''):
    custom = clean_hex(custom_color)
    if custom:
        return palette_from_hex(custom)
    return THEMES.get(key) or THEMES[DEFAULT_THEME]
