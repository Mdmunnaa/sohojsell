#!/usr/bin/env python3
"""
SellPunch — সাপ্তাহিক "ব্যাকআপ থেকে ফেরত আনা" পরীক্ষা (GitHub Actions: .github/workflows/backup-restore-check.yml)।

    python scripts/backup_restore_check.py --target-url postgresql://postgres:postgres@localhost:5432/restore_check

ধাপ:
  ১. R2 থেকে সর্বশেষ দৈনিক ব্যাকআপ নামানো, গোপন বাক্যে খোলা (scripts/db_backup.py -- যাচাইসহ)
  ২. ব্যাকআপের ভেতরেই জরুরি টেবিলগুলোতে কত সারি আছে গোনা (pg_restore --data-only)
  ৩. একদম ফাঁকা, অস্থায়ী ডাটাবেসে পুরোটা ফেরত আনা -- সময় মাপা (নামানো + খোলা + ফেরত আনা)
  ৪. ফেরত আনা ডাটাবেসে আবার গোনা -- ব্যাকআপের সংখ্যার সাথে হুবহু মিলতে হবে
  ৫. SellPunch-এর নিজের কোড দিয়ে: নতুন মাইগ্রেশন চালানো, আর প্রতিটা জরুরি টেবিলের সারি পড়ে দেখা (manage.py backup_read_check)
  ৬. ফল লাইভ ডাটাবেসের store_backupcheck টেবিলে এক লাইন (--no-report দিলে না) -- "নিরাপত্তা ও বিশ্বাস" পাতা আর Master HQ এখান থেকে দেখায়

লাইভ ডাটাবেসে শুধু ৬ নম্বরের একটা লাইন লেখা হয় -- আর কিছু ছোঁয়া হয় না। ব্যর্থ হলে exit 1 (GitHub ইমেইল দেয়)।
লিংক/পাসওয়ার্ড কখনো লগে যায় না।
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_backup  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK_TABLES = (
    'store_shop', 'accounts_user', 'store_product', 'store_productvariant', 'store_category', 'store_customer',
    'store_order', 'store_orderitem', 'store_salepayment', 'store_onlinepayment', 'store_expense', 'store_purchase',
)
MAX_PROBLEM_CHARS = 2000


# ---------------------------------------------------------------- ছোট খাঁটি ফাংশন (টেস্ট করা সহজ)
def latest_key(keys):
    """[(key, size)] থেকে সবচেয়ে নতুন দৈনিক ব্যাকআপ -- নামেই তারিখ-সময় (sellpunch-YYYY-MM-DD-HHMMSS), তাই নামের ক্রমই সময়ের ক্রম।"""
    named = [key for key, _size in keys if db_backup.KEY_RE.search(key)]
    return max(named, key=lambda key: db_backup.KEY_RE.search(key).groups()) if named else None


def count_copy_rows(text):
    """`pg_restore --data-only -f -`-এর লেখা থেকে COPY-র সারি গোনা (COPY ... FROM stdin; থেকে \\. পর্যন্ত, এক লাইনে এক সারি)।"""
    rows, inside = 0, False
    for line in text.splitlines():
        if inside:
            if line == '\\.':
                inside = False
            else:
                rows += 1
        elif line.startswith('COPY ') and line.rstrip().endswith('FROM stdin;'):
            inside = True
    return rows


def tables_in_toc(toc):
    """`pg_restore --list`-এর লেখা থেকে যে টেবিলগুলোর ডেটা আছে।"""
    found = set()
    for line in toc.splitlines():
        parts = line.split()
        if 'TABLE' in parts and 'DATA' in parts:
            index = parts.index('DATA')
            if index + 2 < len(parts):
                found.add(parts[index + 2])
    return found


def compare(dump_counts, restored_counts):
    """দুই গোনা মিলিয়ে সমস্যার তালিকা (খালি = সব মিলেছে)।"""
    problems = []
    for table in CHECK_TABLES:
        a, b = dump_counts.get(table), restored_counts.get(table)
        if a is None:
            problems.append(f'{table}: ব্যাকআপে টেবিলটাই নেই')
        elif b is None:
            problems.append(f'{table}: ফেরত আনা ডাটাবেসে গোনা যায়নি')
        elif a != b:
            problems.append(f'{table}: ব্যাকআপে {a} সারি, ফেরত এসেছে {b}')
    return problems


def merge_counts(dump_counts, restored_counts, read_counts):
    tables = sorted(set(dump_counts) | set(restored_counts))
    merged = {table: {'dump': dump_counts.get(table), 'restored': restored_counts.get(table)} for table in tables}
    if read_counts:
        merged['_app_read'] = read_counts
    return merged


# ---------------------------------------------------------------- আসল কাজ
def dump_counts(dump):
    present = tables_in_toc(db_backup.run(['pg_restore', '--list', dump]))
    counts = {}
    for table in CHECK_TABLES:
        if table in present:
            counts[table] = count_copy_rows(db_backup.run(['pg_restore', '--data-only', f'--table={table}', '-f', '-', dump],
                                                          timeout=1800))
    return counts


def restored_counts(target):
    counts = {}
    for table in CHECK_TABLES:
        try:
            out = db_backup.run(['psql', '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', f'--dbname={target}', '-c',
                                 f'SELECT count(*) FROM "{table}"'])
            counts[table] = int(out.strip())
        except (db_backup.BackupError, ValueError):
            pass
    return counts


def django_checks(target):
    """SellPunch-এর কোড দিয়ে ফেরত আনা ডাটাবেস: মাইগ্রেশন (নতুন কোডের) চলে কিনা, আর প্রতিটা টেবিলের সারি পড়া যায় কিনা।"""
    env = {**os.environ, 'DATABASE_URL': target, 'DEBUG': '0'}
    env.pop('BACKUP_DATABASE_URL', None)
    for cmd in (['migrate', '--noinput'], ['backup_read_check']):
        result = subprocess.run([sys.executable, 'manage.py', *cmd], cwd=ROOT, env=env, capture_output=True, text=True,
                                timeout=1800)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-6:]
            raise db_backup.BackupError(f'manage.py {cmd[0]} ব্যর্থ: ' + ' | '.join(tail))
    return json.loads(result.stdout.strip().splitlines()[-1])


def report(result):
    """লাইভ ডাটাবেসে এক লাইন -- psql-এর :'নাম' দিয়ে, তাই কোনো মান SQL হিসেবে চলে না।"""
    sql = ("INSERT INTO store_backupcheck (checked_at, backup_key, backup_date, ok, restore_seconds, counts, problems) "
           "VALUES (now(), :'key', NULLIF(:'bdate', '')::date, :'ok'::boolean, NULLIF(:'secs', '')::integer, "
           ":'counts'::jsonb, :'problems');\n")
    url = db_backup.direct_url(db_backup.env('BACKUP_DATABASE_URL'))
    values = {'key': result['key'] or '', 'bdate': result['backup_date'] or '', 'ok': 'true' if result['ok'] else 'false',
              'secs': '' if result['seconds'] is None else str(result['seconds']),
              'counts': json.dumps(result['counts'], ensure_ascii=False), 'problems': result['problems'][:MAX_PROBLEM_CHARS]}
    args = ['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', f'--dbname={url}']
    for name, value in values.items():
        args += ['-v', f'{name}={value}']
    db_backup.run(args, stdin_text=sql)


def check(target):
    result = {'key': None, 'backup_date': None, 'ok': False, 'seconds': None, 'counts': {}, 'problems': ''}
    problems = []
    started = time.monotonic()
    try:
        client = db_backup.s3_client()
        key = latest_key(db_backup.list_keys(client, db_backup.env('R2_BACKUP_BUCKET'), db_backup.DAILY_PREFIX))
        if not key:
            raise db_backup.BackupError('R2-তে কোনো দৈনিক ব্যাকআপ পাওয়া যায়নি')
        result['key'] = key
        result['backup_date'] = db_backup.key_date(key).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            dump = os.path.join(tmp, 'db.dump')
            db_backup.download(key, dump)                       # নামানো + গোপন বাক্যে খোলা + জরুরি টেবিল আছে কিনা
            before = dump_counts(dump)
            db_backup.run(['pg_restore', '--no-owner', '--no-privileges', '--single-transaction', '--exit-on-error',
                           f'--dbname={target}', dump], timeout=3600)
            result['seconds'] = int(round(time.monotonic() - started))
        after = restored_counts(target)
        problems += compare(before, after)
        read = {}
        try:
            read = django_checks(target)
        except (db_backup.BackupError, subprocess.TimeoutExpired, ValueError) as exc:
            problems.append(str(exc))
        result['counts'] = merge_counts(before, after, read)
    except (db_backup.BackupError, subprocess.TimeoutExpired) as exc:
        problems.append(str(exc))
    result['problems'] = '\n'.join(problems)
    result['ok'] = not problems
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='SellPunch ব্যাকআপ ফেরত আনার পরীক্ষা')
    parser.add_argument('--target-url', required=True, help='একদম ফাঁকা, অস্থায়ী ডাটাবেস -- কখনো লাইভ নয়')
    parser.add_argument('--no-report', action='store_true', help='লাইভ ডাটাবেসে ফল না লেখা')
    args = parser.parse_args(argv)
    source = os.environ.get('BACKUP_DATABASE_URL', '')
    if source and db_backup.same_database(args.target_url, source):
        print('ব্যর্থ: লক্ষ্য ডাটাবেস আর লাইভ ডাটাবেস একই! পরীক্ষা শুধু ফাঁকা, অস্থায়ী ডাটাবেসে।', file=sys.stderr)
        return 1
    result = check(args.target_url)
    when = dt.datetime.now(db_backup.DHAKA).strftime('%Y-%m-%d %H:%M')
    print(f"{'সফল' if result['ok'] else 'ব্যর্থ'} {when} -- {result['key'] or '(কোনো ব্যাকআপ নেই)'} -- "
          f"সময় {result['seconds'] if result['seconds'] is not None else '?'} সেকেন্ড")
    for table, row in sorted(result['counts'].items()):
        if not table.startswith('_'):
            print(f"   {table}: ব্যাকআপে {row['dump']}, ফেরত {row['restored']}")
    if result['problems']:
        print('সমস্যা:\n' + result['problems'], file=sys.stderr)
    if not args.no_report:
        try:
            report(result)
            print('ফল SellPunch-এ জমা হয়েছে (Master HQ ও নিরাপত্তা পাতা)')
        except db_backup.BackupError as exc:
            print(f'ব্যর্থ: ফল জমা দেওয়া যায়নি: {exc}', file=sys.stderr)
            return 1
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
