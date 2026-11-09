#!/usr/bin/env bash
# ============================================================
# Cloudflare Workers Builds-এর "Build command": bash build.sh
# প্রতিটা push-এ নতুন কোড চালুর আগে ডাটাবেস migrate করে।
# (Render-ও নিজের build.sh-এ একই কাজ করে; দুবার চললেও কোনো ক্ষতি নেই)
# এর জন্য Build variables-এ DATABASE_URL (Secret) দিতে হয় — README.md দেখুন।
# ============================================================
set -euo pipefail

if [ -z "${DATABASE_URL:-}" ]; then
  echo "Build variables-এ DATABASE_URL নেই, তাই migrate বাদ দেওয়া হলো।"
  exit 0
fi

cd ..
python3 -m venv /tmp/sellpunch-build-venv
. /tmp/sellpunch-build-venv/bin/activate
pip install --quiet --disable-pip-version-check -r requirements.txt
DEBUG=0 SECRET_KEY=build-only-migrate python manage.py migrate --no-input
