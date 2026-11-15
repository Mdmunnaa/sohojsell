"""
ছবি রাখার জায়গা (Cloudflare R2)।

django-storages প্রতিটা ফাইল তোলার আগে R2-কে জিজ্ঞেস করে "এই নামে কিছু আছে?" (HEAD) — নাম মিললে নতুন নাম বানায়।
store/images.py প্রতিটা ছবির নামে আগেই একটা এলোমেলো চিহ্ন বসায় (-u + ১০ অক্ষর), তাই সেসব নামের জন্য প্রশ্নটা লাগে না —
প্রতি ছবিতে R2-তে একটা কম যাতায়াত, প্রোডাক্ট সেভ একটু দ্রুত। অন্য সব ফাইলে আগের মতোই যাচাই হয় (কিছু মুছে যায় না)।
"""
import re

from storages.backends.s3 import S3Storage
from storages.utils import clean_name, get_available_overwrite_name

UNIQUE_NAME = re.compile(r'-u[0-9a-f]{10}(-thumb)?\.[a-z0-9]+$')


class R2Storage(S3Storage):
    def get_available_name(self, name, max_length=None):
        name = clean_name(name)
        if UNIQUE_NAME.search(name):
            return get_available_overwrite_name(name, max_length)
        return super().get_available_name(name, max_length)
