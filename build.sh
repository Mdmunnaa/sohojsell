#!/usr/bin/env bash
# Render প্রতিটা deploy-এ এই স্ক্রিপ্ট চালায়
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
# লাইভ ডেমো দোকান (হোমপেজের "লাইভ ডেমো" বাটন) — প্রতি deploy-এ আবার সাজানো হয়
python manage.py seed_demo || echo "ডেমো দোকান সাজানো যায়নি, প্রথম /demo/ ভিজিটে আবার চেষ্টা হবে।"
# আগে আপলোড হওয়া প্রোডাক্টের ছবি ছোট করা (না পারলেও deploy থামবে না)
python manage.py optimize_images --limit 300 || echo "ছবি ছোট করা যায়নি, পরের deploy-এ আবার চেষ্টা হবে।"

# DJANGO_SUPERUSER_PHONE_NUMBER আর DJANGO_SUPERUSER_PASSWORD দেওয়া থাকলে
# প্রথমবার admin অ্যাকাউন্ট বানাবে (আগে থেকে থাকলে কিছু করবে না)
if [ -n "$DJANGO_SUPERUSER_PHONE_NUMBER" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py createsuperuser --no-input || echo "Superuser আগে থেকেই আছে, বাদ দেওয়া হলো।"
fi
