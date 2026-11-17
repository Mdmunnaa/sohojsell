"""নিজের মডেল-ফিল্ড।"""
from django.db import models


class QtyField(models.DecimalField):
    """
    পরিমাণ আর স্টক: দশমিক (১২ ঘর, ৩ দশমিক) যাতে ওজনে বিক্রি (১.৫ কেজি) চলে। ডাটাবেস থেকে পড়ার সময় অপ্রয়োজনীয় শূন্য বাদ
    (5.000 → 5, 1.500 → 1.5) — তাই পিসের প্রোডাক্ট আগের মতোই "5" দেখায়।
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_digits', 12)
        kwargs.setdefault('decimal_places', 3)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        from .units import clean
        return clean(value)
