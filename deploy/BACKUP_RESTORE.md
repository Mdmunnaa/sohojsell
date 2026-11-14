# SellPunch — ডাটাবেস ব্যাকআপ ও ফেরত আনা

Edumi-র ব্যবস্থাই, SellPunch-এর জন্য (`scripts/db_backup.py`, `scripts/backup_restore_check.py`)।

## কীভাবে কাজ করে
- প্রতিদিন **রাত ২:১৫ (ঢাকা)** GitHub Actions (`.github/workflows/db-backup.yml`) চলে:
  ডাটাবেসের পুরো কপি → যাচাই (দোকান, প্রোডাক্ট, অর্ডারের টেবিল আছে কিনা) → **AES-256 এনক্রিপ্ট** → আবার খুলে মিলিয়ে দেখা → Cloudflare R2-এর **private** বাকেটে তোলা।
- রাখা হয়: শেষ **৩০ দিনের** দৈনিক কপি (`db/daily/`) + প্রতি মাসের ১ তারিখের কপি **১২ মাস** (`db/monthly/`)। পুরনোগুলো নিজে থেকে মোছে।
  সবচেয়ে নতুন কপিটা কখনো মোছে না।
- প্রতি **শুক্রবার ভোর ৩:০০** (`.github/workflows/backup-restore-check.yml`): সর্বশেষ ব্যাকআপ GitHub-এর মেশিনে একটা **ফাঁকা, অস্থায়ী** ডাটাবেসে
  পুরো ফেরত এনে ১২টা জরুরি টেবিলের সারি মিলিয়ে দেখা হয়, SellPunch-এর কোড দিয়ে পড়ে দেখা হয়। ফল লাইভ ডাটাবেসের `store_backupcheck`-এ এক লাইন।
- ব্যর্থ হলে GitHub আপনাকে **ইমেইল** দেয়, আর Master HQ-র "এখন যা করতে হবে"-তে লাল লাইন আসে।
- "নিরাপত্তা ও ডাটা" পাতা (`/security/`) আর সেটিংস → ডাটা ও ব্যাকআপ: ব্যাকআপের কথা আর "শেষ সফল পরীক্ষা: তারিখ" দেখায়
  **শুধু ১৪ দিনের মধ্যে সফল পরীক্ষা থাকলে** — না থাকলে লাইনটাই লুকায়, পুরনো দাবি কখনো দেখায় না।

---

## একবারের সেটআপ (~১৫ মিনিট)

### ১. R2-তে আলাদা PRIVATE বাকেট
Cloudflare → **R2** → **Create bucket** → নাম `sellpunch-backups` → Create।
এই বাকেটে **Public access / r2.dev URL চালু করবেন না।** ছবির বাকেট পাবলিক — ব্যাকআপ সেখানে রাখা যাবে না।

### ২. শুধু এই বাকেটের চাবি
R2 → **Manage API tokens** → **Create API token**:
- Permissions: **Object Read & Write**
- Specify bucket: **শুধু `sellpunch-backups`**
- Create → দেখানো **Access Key ID**, **Secret Access Key** আর **S3 endpoint** (`https://<account-id>.r2.cloudflarestorage.com`) কপি করুন।
  Secret একবারই দেখায়।

### ৩. গোপন বাক্য (passphrase)
কমপক্ষে ১৬ অক্ষরের একটা বাক্য (যেমন চারটা এলোমেলো শব্দ আর সংখ্যা)। Edumi-রটা থেকে **আলাদা** রাখুন।
**দুই জায়গায় লিখে রাখুন** (পাসওয়ার্ড ম্যানেজার + কাগজে)। এটা হারালে কোনো ব্যাকআপই আর খোলা যাবে না — কেউই পারবে না।

### ৪. GitHub Secrets
GitHub → রিপো **sohojsell** → **Settings → Secrets and variables → Actions → New repository secret** — ৬টা:

| নাম | মান |
|---|---|
| `BACKUP_DATABASE_URL` | SellPunch-এর লাইভ ডাটাবেসের লিংক: Neon → প্রজেক্ট → **Connect** → connection string (`postgresql://…`; pooler লিংক হলেও চলবে) — Render-এর `DATABASE_URL`-এর সাথে একই |
| `BACKUP_PASSPHRASE` | ধাপ ৩-এর গোপন বাক্য |
| `R2_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | ধাপ ২ |
| `R2_SECRET_ACCESS_KEY` | ধাপ ২ |
| `R2_BACKUP_BUCKET` | `sellpunch-backups` |

### ৫. প্রথমবার হাতে চালিয়ে দেখা
1. GitHub → **Actions** → বামে **db-backup** → **Run workflow** → ১-২ মিনিট পর সবুজ টিক।
   Cloudflare → R2 → `sellpunch-backups` → `db/daily/`-এ `sellpunch-…dump.gpg` ফাইল দেখা যাবে।
2. তারপর **backup-restore-check** → **Run workflow** (৫-১০ মিনিট)। সবুজ হলে "নিরাপত্তা ও ডাটা" পাতায় ব্যাকআপের অংশ নিজে থেকে চালু হয়ে যাবে।

---

## ব্যর্থ হলে
Actions → লাল দাগ → শেষ ধাপের লগ। সাধারণ কারণ:
- `… সেট করা নেই` → ঐ নামের Secret নেই বা বানান ভুল।
- `pg_dump ব্যর্থ … password authentication failed` → `BACKUP_DATABASE_URL` পুরনো (Neon-এর পাসওয়ার্ড বদলালে এটাও বদলাতে হবে)।
- `AccessDenied` / `NoSuchBucket` → R2 চাবি বা বাকেটের নাম ভুল।

---

## ফেরত আনা (কখনো দরকার হলে)

**নিয়ম: আগে সবসময় আলাদা জায়গায় (নতুন Neon branch) ফেরত আনুন, মিলিয়ে দেখুন — তারপর সিদ্ধান্ত।** লাইভ ডাটাবেসের ওপর সরাসরি ফেরত আনলে
ব্যাকআপের পরের সব তথ্য (নতুন অর্ডার, বিক্রি) মুছে যায়।

### প্রস্তুতি (কম্পিউটারে একবার)
- Python 3, PostgreSQL client (`pg_restore`) আর `gpg`; `pip install boto3`।
- Neon → **Branches → Create branch** → তার লিংক কপি করুন। কাজ শেষে branch মুছে দিন।

### কমান্ড (Windows PowerShell, প্রজেক্ট ফোল্ডার থেকে)
```powershell
$env:BACKUP_DATABASE_URL  = "<লাইভ ডাটাবেসের লিংক -- ভুল করে লাইভে ফেরত আনা আটকাতে>"
$env:BACKUP_PASSPHRASE    = "<গোপন বাক্য>"
$env:R2_ENDPOINT_URL      = "https://<account-id>.r2.cloudflarestorage.com"
$env:R2_ACCESS_KEY_ID     = "<…>"
$env:R2_SECRET_ACCESS_KEY = "<…>"
$env:R2_BACKUP_BUCKET     = "sellpunch-backups"

python scripts/db_backup.py list
python scripts/db_backup.py restore db/daily/sellpunch-2026-11-15-021503.dump.gpg --target-url "<নতুন branch-এর লিংক>"
```
শুধু ফাইলটা নামিয়ে খুলতে: `python scripts/db_backup.py download <key> sellpunch.dump`

### তারপর
- **পুরো ডাটাবেস ফেরত চাইলে:** Render/Cloudflare-এ `DATABASE_URL` নতুন branch-এর লিংকে বদলান → সাইট ঠিক আছে দেখুন।
- **শুধু কিছু মুছে যাওয়া তথ্য চাইলে** (যেমন একটা দোকানের প্রোডাক্ট): নতুন branch থেকে শুধু ঐ সারিগুলো লাইভে কপি করতে হয় — সাবধানে করার কাজ, Claude-কে সাথে নিয়ে করুন।
- লাইভের ওপরেই ফেরত আনা স্ক্রিপ্ট নিজে আটকায়; সত্যিই দরকার হলে `--allow-same-database` দিতে হয়।

### ছবি
প্রোডাক্টের ছবি ডাটাবেসে থাকে না, Cloudflare R2-এর ছবির বাকেটে থাকে। সেলাররা "সব ডাটা নামান" Excel-এ প্রতিটা ছবির লিংক পায়।
