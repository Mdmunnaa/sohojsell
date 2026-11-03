# store/themes.py
"""
দোকানের ওয়েবসাইটের রঙের থিম। লেআউট একই থাকে, প্রধান রঙটা বদলায়।
প্রতিটা থিমে: primary (বাটন, দাম), dark (hover), light (হালকা ব্যাকগ্রাউন্ড), second (গ্রেডিয়েন্টের দ্বিতীয় রঙ),
rgb (ছায়ার জন্য primary-র RGB)।
"""
DEFAULT_THEME = 'orange'

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


def theme_for(key):
    return THEMES.get(key) or THEMES[DEFAULT_THEME]
