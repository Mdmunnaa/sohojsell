#!/bin/sh
# Cloudflare কন্টেইনার চালু হওয়ার সময় (Dockerfile-এর CMD):
# ১) ডাটাবেসে নতুন পরিবর্তন থাকলে বসায় (migrate) — নতুন কোড deploy হলে নতুন কন্টেইনার চালু হয়, তখনই হয়।
#    তাই Cloudflare-এর Build variables-এ DATABASE_URL দেওয়ার দরকার নেই।
# ২) তারপর সাইট চালু (gunicorn)। migrate কোনো কারণে না হলেও সাইট চালু হয় — বেশিরভাগ কাজ চলে, কারণ লগে থাকে।
python manage.py migrate --no-input || echo "migrate হয়নি — উপরের লগ দেখুন"

exec gunicorn sohojsell.wsgi:application \
    --bind 0.0.0.0:8080 \
    --preload \
    --workers 3 --threads 4 --worker-class gthread \
    --timeout 60 --graceful-timeout 20 \
    --forwarded-allow-ips "*" \
    --access-logfile -
