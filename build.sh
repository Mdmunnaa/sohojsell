#!/usr/bin/env bash
# Render প্রতিটা deploy-এ এই স্ক্রিপ্ট চালায়
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# DJANGO_SUPERUSER_PHONE_NUMBER আর DJANGO_SUPERUSER_PASSWORD দেওয়া থাকলে
# প্রথমবার admin অ্যাকাউন্ট বানাবে (আগে থেকে থাকলে কিছু করবে না)
if [ -n "$DJANGO_SUPERUSER_PHONE_NUMBER" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py createsuperuser --no-input || echo "Superuser আগে থেকেই আছে, বাদ দেওয়া হলো।"
fi
