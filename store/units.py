"""
প্রোডাক্টের একক: পিসে বিক্রি (পূর্ণ সংখ্যা) নাকি ওজন/মাপে (কেজি, লিটার, মিটার, গজ — ভাঙা পরিমাণ, যেমন ১.৫ কেজি)।

পরিমাণ আর স্টক ডাটাবেসে দশমিক (৩ ঘর, store/fields.QtyField) — পিসের প্রোডাক্টে সবসময় পূর্ণ সংখ্যা থাকে, তাই আগের মতোই দেখায়।
ভাঙা পরিমাণ শুধু ওজন/মাপের প্রোডাক্টে চলে; parse() সেটা যাচাই করে।
"""
from decimal import Decimal, InvalidOperation

PCS = 'pcs'
UNITS = (
    (PCS, 'পিস'),
    ('kg', 'কেজি'),
    ('litre', 'লিটার'),
    ('metre', 'মিটার'),
    ('gauge', 'গজ'),
)
LABELS = dict(UNITS)
# পরিমাণের পরে কী লেখা হবে: "৩টা", "১.৫ কেজি"
SUFFIX = {PCS: 'টা', 'kg': ' কেজি', 'litre': ' লিটার', 'metre': ' মিটার', 'gauge': ' গজ'}
SUFFIX_EN = {PCS: '', 'kg': ' kg', 'litre': ' L', 'metre': ' m', 'gauge': ' yd'}      # ইংরেজি ওয়েবসাইট/ইনভয়েস
MAX_QTY = Decimal('99999')
STEP = Decimal('0.001')
_BN = str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789')
_EN = str.maketrans('0123456789', '০১২৩৪৫৬৭৮৯')


class QtyError(ValueError):
    """সেলারকে দেখানোর মতো বাংলা বার্তা।"""


def is_loose(unit):
    """ওজন/মাপে বিক্রি — ভাঙা পরিমাণ চলে।"""
    return bool(unit) and unit != PCS


def clean(value):
    """Decimal('5.000') → Decimal('5'), Decimal('1.500') → Decimal('1.5') — দেখাতে আর JSON-এ সুন্দর।"""
    if value is None:
        return value
    value = Decimal(value)
    return value.quantize(Decimal(1)) if value == value.to_integral_value() else value.normalize()


def num(value):
    """JSON/JS-এর জন্য: পূর্ণ হলে int, নাহলে float।"""
    if value is None:
        return 0
    value = clean(value)
    return int(value) if value == value.to_integral_value() else float(value)


def parse(raw, unit=PCS, *, label='পরিমাণ', allow_zero=False, maximum=MAX_QTY):
    """
    ফর্ম/কার্টের পরিমাণ → Decimal। বাংলা অঙ্ক চলে। পিসে পূর্ণ সংখ্যা লাগবে; কেজি/লিটারে ৩ দশমিক পর্যন্ত।
    ভুল হলে QtyError।
    """
    text = str(raw if raw is not None else '').strip().translate(_BN).replace(',', '')
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise QtyError(f'{label} সংখ্যায় লিখুন।')
    if not value.is_finite():
        raise QtyError(f'{label} ঠিক নেই।')
    if not is_loose(unit) and value != value.to_integral_value():
        raise QtyError(f'{label} পূর্ণ সংখ্যায় লিখুন (এই প্রোডাক্ট পিসে বিক্রি হয়)।')
    value = value.quantize(STEP)
    if value < 0 or (value == 0 and not allow_zero) or value > maximum:
        raise QtyError(f'{label} ঠিক নেই।')
    return clean(value)


def fits(qty, unit):
    """পরিমাণটা এই এককে চলে কিনা: পিসে শুধু পূর্ণ সংখ্যা।"""
    return is_loose(unit) or Decimal(qty) == Decimal(qty).to_integral_value()


def whole_msg(name):
    return f'"{name}" পিসে বিক্রি হয় — পরিমাণ পূর্ণ সংখ্যায় দিন।'


def money(value):
    """দাম × ভাঙা পরিমাণ (১.২৫ কেজি) → পয়সায় গোল।"""
    from decimal import ROUND_HALF_UP
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def show(qty, unit=PCS, *, bangla=True):
    """"৩টা", "১.৫ কেজি"; bangla=False হলে ইংরেজিতে: "3", "1.5 kg"।"""
    text = f'{abs(clean(qty or 0)):f}'
    if clean(qty or 0) < 0:
        text = '−' + text                  # মাইনাস স্টক (অফলাইনে স্টকের চেয়ে বেশি বিক্রি)
    if not bangla:
        return f'{text}{SUFFIX_EN.get(unit or PCS, "")}'
    return f'{text.translate(_EN)}{SUFFIX.get(unit or PCS, "টা")}'
