#!/usr/bin/env python3
"""
SellPunch — ডাটাবেস ব্যাকআপ (Edumi-র scripts/db_backup.py থেকে) (প্রতিদিন GitHub Actions থেকে চলে) আর ফেরত আনা।

    python scripts/db_backup.py backup                     # ব্যাকআপ নিয়ে এনক্রিপ্ট করে R2-তে তোলা + পুরনো কপি মোছা
    python scripts/db_backup.py list                       # R2-তে কী কী ব্যাকআপ আছে
    python scripts/db_backup.py download <key> <file.dump> # একটা ব্যাকআপ নামিয়ে ডিক্রিপ্ট করা
    python scripts/db_backup.py restore <key> --target-url <postgres-url>   # নতুন/খালি ডাটাবেসে ফেরত আনা

পরিবেশ (env) -- GitHub → Settings → Secrets and variables → Actions:
    BACKUP_DATABASE_URL   Neon-এর লিংক (pooler লিংক দিলেও চলবে -- স্ক্রিপ্ট নিজেই সরাসরি লিংকে বদলে নেয়)
    BACKUP_PASSPHRASE     এনক্রিপশনের গোপন বাক্য -- হারালে ব্যাকআপ আর খোলা যাবে না
    R2_ENDPOINT_URL       https://<account-id>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
    R2_BACKUP_BUCKET      আলাদা PRIVATE বাকেট (মিডিয়ার পাবলিক বাকেট না!)

নিরাপত্তা: ফাইল R2-তে যায় AES-256 এনক্রিপ্ট হয়ে; গোপন বাক্য কখনো command line-এ বা লগে যায় না;
লিংক/পাসওয়ার্ড কখনো প্রিন্ট হয় না; restore উৎস-ডাটাবেসে চালাতে দেয় না (--allow-same-database ছাড়া)।
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

DHAKA = ZoneInfo('Asia/Dhaka')
DAILY_PREFIX = 'db/daily/'
MONTHLY_PREFIX = 'db/monthly/'
KEEP_DAILY_DAYS = 30
KEEP_MONTHLY_DAYS = 365
MIN_DUMP_BYTES = 1024
KEY_RE = re.compile(r'sellpunch-(\d{4})-(\d{2})-(\d{2})-(\d{4}|\d{6})\.dump\.gpg$')
REQUIRED_TABLES = ('store_shop', 'store_product', 'store_order')   # এগুলো ছাড়া ব্যাকআপ অসম্পূর্ণ


class BackupError(Exception):
    pass


# ---------------------------------------------------------------- ছোট খাঁটি ফাংশন (টেস্ট করা সহজ)
def direct_url(url):
    """Neon-এর pooler লিংক (…-pooler.…) থেকে সরাসরি লিংক -- pg_dump pooler দিয়ে নির্ভরযোগ্য না।"""
    parts = urlsplit(url)
    netloc = re.sub(r'-pooler(?=\.)', '', parts.netloc, count=1)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def safe_target(url):
    """লগে দেখানোর মতো: শুধু host/ডাটাবেস, পাসওয়ার্ড বাদ।"""
    parts = urlsplit(url)
    return f"{parts.hostname or '?'}{parts.path or ''}"


def same_database(a, b):
    pa, pb = urlsplit(direct_url(a)), urlsplit(direct_url(b))
    return (pa.hostname, pa.port or 5432, pa.path.strip('/')) == (pb.hostname, pb.port or 5432, pb.path.strip('/'))


def backup_key(now):
    """now (Dhaka) -> db/daily/sellpunch-2026-10-07-023015.dump.gpg (সেকেন্ডসহ -- একই মিনিটে দুবার চালালেও আগেরটা মোছে না)"""
    return f"{DAILY_PREFIX}sellpunch-{now:%Y-%m-%d-%H%M%S}.dump.gpg"


def key_date(key):
    m = KEY_RE.search(key)
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def keys_to_delete(keys, today, keep_days, newest_must_stay=True):
    """নামের তারিখ দেখে পুরনো কপি বাছাই। নাম না মিললে কখনো মোছে না; সবচেয়ে নতুনটা কখনো মোছে না।"""
    dated = sorted((key_date(k), k) for k in keys if key_date(k))
    if not dated:
        return []
    newest = dated[-1][1]
    cutoff = today - dt.timedelta(days=keep_days)
    return [k for d, k in dated if d < cutoff and not (newest_must_stay and k == newest)]


# ---------------------------------------------------------------- বাইরের কাজ
def env(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise BackupError(f'{name} সেট করা নেই (GitHub Secrets দেখুন)')
    return value


def s3_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        's3', endpoint_url=env('R2_ENDPOINT_URL'), region_name='auto',
        aws_access_key_id=env('R2_ACCESS_KEY_ID'), aws_secret_access_key=env('R2_SECRET_ACCESS_KEY'),
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                      request_checksum_calculation='when_required', response_checksum_validation='when_required',
                      retries={'max_attempts': 5, 'mode': 'standard'}))


def run(cmd, stdin_text=None, timeout=1200):
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        tool = os.path.basename(cmd[0])
        raise BackupError(f'{tool} ব্যর্থ ({result.returncode}): {result.stderr.strip()[-800:]}')
    return result.stdout


def pg_dump(url, out_path):
    cmd = ['pg_dump', '--format=custom', '--compress=6', '--no-owner', '--no-privileges', f'--file={out_path}', f'--dbname={url}']
    try:
        run(cmd)
    except BackupError:
        # Neon ঘুম থেকে জাগতে কয়েক সেকেন্ড নেয় -- একবার আবার চেষ্টা
        import time
        time.sleep(15)
        run(cmd)


def verify_dump(path):
    size = os.path.getsize(path)
    if size < MIN_DUMP_BYTES:
        raise BackupError(f'ব্যাকআপ ফাইল অস্বাভাবিক ছোট ({size} বাইট)')
    toc = run(['pg_restore', '--list', path])
    data_tables = set(re.findall(r'TABLE DATA \S+ (\S+) ', toc))
    missing = [t for t in REQUIRED_TABLES if t not in data_tables]
    if missing:
        raise BackupError(f'ব্যাকআপে জরুরি টেবিল নেই: {missing}')
    return size, len(data_tables)


def gpg(args, passphrase):
    run(['gpg', '--batch', '--yes', '--quiet', '--pinentry-mode', 'loopback', '--passphrase-fd', '0', *args],
        stdin_text=passphrase + '\n')


def encrypt(src, dst, passphrase):
    gpg(['--symmetric', '--cipher-algo', 'AES256', '--compress-algo', 'none', '--output', dst, src], passphrase)


def decrypt(src, dst, passphrase):
    gpg(['--decrypt', '--output', dst, src], passphrase)


def list_keys(client, bucket, prefix):
    keys, token = [], None
    while True:
        kwargs = {'Bucket': bucket, 'Prefix': prefix, **({'ContinuationToken': token} if token else {})}
        page = client.list_objects_v2(**kwargs)
        keys += [(o['Key'], o['Size']) for o in page.get('Contents', [])]
        if not page.get('IsTruncated'):
            return keys
        token = page['NextContinuationToken']


# ---------------------------------------------------------------- কমান্ড
def cmd_backup(_args):
    url = direct_url(env('BACKUP_DATABASE_URL'))
    passphrase, bucket = env('BACKUP_PASSPHRASE'), env('R2_BACKUP_BUCKET')
    if len(passphrase) < 16:
        raise BackupError('BACKUP_PASSPHRASE কমপক্ষে ১৬ অক্ষরের দিন')
    now = dt.datetime.now(DHAKA)
    key = backup_key(now)
    client = s3_client()
    with tempfile.TemporaryDirectory() as tmp:
        dump, enc = os.path.join(tmp, 'db.dump'), os.path.join(tmp, 'db.dump.gpg')
        print(f'ব্যাকআপ নেওয়া হচ্ছে: {safe_target(url)}')
        pg_dump(url, dump)
        size, tables = verify_dump(dump)
        print(f'যাচাই হয়েছে: {size / 1024:.0f} KB, {tables}টা টেবিলের তথ্য')
        encrypt(dump, enc, passphrase)
        decrypt(enc, os.path.join(tmp, 'check.dump'), passphrase)        # ফেরত খোলা যায় কিনা -- তবেই তোলা
        if os.path.getsize(os.path.join(tmp, 'check.dump')) != size:
            raise BackupError('এনক্রিপ্ট করা ফাইল ঠিকমতো খোলা যাচ্ছে না')
        client.upload_file(enc, bucket, key, ExtraArgs={'ContentType': 'application/octet-stream'})
        print(f'R2-তে তোলা হয়েছে: {key} ({os.path.getsize(enc) / 1024:.0f} KB)')
        if now.day == 1:
            monthly = key.replace(DAILY_PREFIX, MONTHLY_PREFIX, 1)
            client.copy_object(Bucket=bucket, Key=monthly, CopySource={'Bucket': bucket, 'Key': key})
            print(f'মাসিক কপি রাখা হলো: {monthly}')
    today = now.date()
    removed = 0
    for prefix, days in ((DAILY_PREFIX, KEEP_DAILY_DAYS), (MONTHLY_PREFIX, KEEP_MONTHLY_DAYS)):
        for old in keys_to_delete([k for k, _ in list_keys(client, bucket, prefix)], today, days):
            client.delete_object(Bucket=bucket, Key=old)
            removed += 1
    print(f'পুরনো কপি মোছা হলো: {removed}টা। ব্যাকআপ সম্পূর্ণ।')


def cmd_list(_args):
    client, bucket = s3_client(), env('R2_BACKUP_BUCKET')
    rows = list_keys(client, bucket, 'db/')
    for key, size in sorted(rows):
        print(f'{key}\t{size / 1024:.0f} KB')
    print(f'মোট {len(rows)}টা ব্যাকআপ')


def download(key_or_path, out_path):
    passphrase = env('BACKUP_PASSPHRASE')
    with tempfile.TemporaryDirectory() as tmp:
        enc = key_or_path
        if not os.path.exists(key_or_path):
            enc = os.path.join(tmp, 'db.dump.gpg')
            s3_client().download_file(env('R2_BACKUP_BUCKET'), key_or_path, enc)
        decrypt(enc, out_path, passphrase)
    verify_dump(out_path)


def cmd_download(args):
    download(args.key, args.out)
    print(f'নামানো ও ডিক্রিপ্ট হয়েছে: {args.out}')


def cmd_restore(args):
    source = os.environ.get('BACKUP_DATABASE_URL', '')
    if source and same_database(args.target_url, source) and not args.allow_same_database:
        raise BackupError('লক্ষ্য ডাটাবেস আর লাইভ ডাটাবেস একই! আগে নতুন/খালি ডাটাবেসে ফেরত আনুন। '
                          'সত্যিই লাইভে চাইলে --allow-same-database দিন (আগে রক্ষণাবেক্ষণ মোড চালু করুন)।')
    with tempfile.TemporaryDirectory() as tmp:
        dump = os.path.join(tmp, 'db.dump')
        download(args.key, dump)
        print(f'ফেরত আনা হচ্ছে: {safe_target(args.target_url)}')
        run(['pg_restore', '--clean', '--if-exists', '--no-owner', '--no-privileges', '--single-transaction',
             '--exit-on-error', f'--dbname={direct_url(args.target_url)}', dump], timeout=3600)
    print('ফেরত আনা সম্পূর্ণ।')


def main(argv=None):
    parser = argparse.ArgumentParser(description='SellPunch ডাটাবেস ব্যাকআপ')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('backup').set_defaults(func=cmd_backup)
    sub.add_parser('list').set_defaults(func=cmd_list)
    p = sub.add_parser('download'); p.add_argument('key'); p.add_argument('out'); p.set_defaults(func=cmd_download)
    p = sub.add_parser('restore'); p.add_argument('key'); p.add_argument('--target-url', required=True)
    p.add_argument('--allow-same-database', action='store_true'); p.set_defaults(func=cmd_restore)
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except BackupError as exc:
        print(f'ব্যর্থ: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
