# ============================================================
# SellPunch — Cloudflare Containers-এর জন্য ইমেজ
# (Render এটা ব্যবহার করে না; Render চলে build.sh দিয়ে)
# Cloudflare-এ deploy: cloudflare/README.md দেখুন
# ============================================================
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# আগে শুধু requirements — কোড বদলালেও এই ধাপ cache থেকে আসে, তাই deploy দ্রুত হয়
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# CSS/JS/ছবি এক জায়গায় জড়ো করা (whitenoise এগুলো দেয়)। ডাটাবেস লাগে না।
RUN DEBUG=0 SECRET_KEY=collectstatic-only python manage.py collectstatic --no-input \
    && useradd --create-home --uid 10001 app \
    && chown -R app:app /app

USER app
EXPOSE 8080

# চালু হওয়ার সময় আগে migrate (নতুন কিছু না থাকলে ২–৩ সেকেন্ড), তারপর gunicorn — deploy/container-start.sh।
# KEEP_WARM থাকায় কন্টেইনার ঘুমায় না, তাই এটা শুধু নতুন deploy বা Secret বদলালে হয়।
CMD ["sh", "deploy/container-start.sh"]
