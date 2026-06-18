# Setup guide

Complete installation from clone to first dashboard. For day-to-day use after setup, see [USER_GUIDE.md](USER_GUIDE.md).

## Prerequisites

- Python 3.11+
- MySQL 8.x (local or remote)
- Git

## 1. Clone and virtual environment

```powershell
cd path\to\excel-audit-dashboard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional dev tools (tests, lint):

```powershell
pip install -r requirements-dev.txt
```

## اختبار النظام بالكامل

بعد أي تعديل على الكود، شغّل مجموعة الاختبارات كاملة:

```powershell
python scripts/run_tests.py
```

أو مباشرة:

```powershell
pytest
```

اختبارات سريعة (بدون `slow`):

```powershell
pytest -m "not slow" -q
```

Smoke tests للتحسينات الأخيرة:

```powershell
pytest -m regression -q
```

كتالوج الاختبارات الانحدارية: راجع [REGRESSION_CATALOG.md](REGRESSION_CATALOG.md).

بعد سحب تحديثات جديدة (migrations):

```powershell
python manage.py migrate
```

## 2. Bootstrap configuration (required)

The repo ships templates only. Copy them before first run:

```powershell
# Django project package (settings, urls, wsgi)
Copy-Item -Recurse config.example config

# Environment variables
Copy-Item .env.example .env
```

Edit `.env` with your values. Use placeholders in development; never commit real secrets.

| Variable | Local dev example | Production |
|----------|-------------------|------------|
| `DJANGO_SECRET_KEY` | `your-secret-key-here` | Long random string |
| `DJANGO_DEBUG` | `true` | `false` |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | `YourDomain.com,www.YourDomain.com` |
| `DB_NAME` | `excel_dashboard` | Your database name |
| `DB_USER` | `root` or dedicated user | Dedicated app user |
| `DB_PASSWORD` | Your password | Strong password |
| `DB_HOST` | `127.0.0.1` | `your-db-host` |
| `DB_PORT` | `3306` | `3306` |

SMTP (optional — needed for observation email and 2FA):

| Variable | Example |
|----------|---------|
| `AI_EXCEL_SMTP_HOST` | `smtp.gmail.com` |
| `AI_EXCEL_SMTP_PORT` | `587` |
| `AI_EXCEL_SMTP_USER` | `noreply@YourDomain.com` |
| `AI_EXCEL_SMTP_PASSWORD` | `your-smtp-password` |
| `AI_EXCEL_SMTP_FROM` | `noreply@YourDomain.com` |
| `AI_EXCEL_SMTP_FROM_NAME` | `Audit Dashboard` |
| `AI_EXCEL_SMTP_USE_TLS` | `true` |

All SMTP settings live in **`.env`** only. Restart Django after editing.

Verify: `python manage.py test_smtp`

## 2b. Redis (required for email OTP / shared cache)

OTP codes and rate limits are stored in **Redis** so every app worker sees the same data.

| Variable | Example |
|----------|---------|
| `REDIS_URL` | `redis://127.0.0.1:6379/1` |

**Full guide (local Windows/Laragon + VPS):** [REDIS_SETUP.md](REDIS_SETUP.md)

After `REDIS_URL` is set, restart Django. Tests use in-memory cache automatically.

**OTP validity** (default 10 minutes, including resend cooldown) can be changed in Django admin under **Project security settings**.

## 3. MySQL database

See [MYSQL_SETUP.md](MYSQL_SETUP.md) for creating the database and user.

Quick check after `.env` is configured:

```powershell
.\scripts\migrate.ps1
.\scripts\db_health.ps1
```

## 4. Django migrations and bootstrap data

```powershell
python manage.py migrate
python manage.py create_default_admin
python manage.py setup_groups
python manage.py setup_companies
```

- **create_default_admin** — first superuser (prompts for username/password).
- **setup_groups** — permission groups (upload, review, etc.).
- **setup_companies** — tenant companies and logo placeholders; edit in Django admin.

## 5. Run the server

```powershell
.\scripts\run_web.ps1
# or: python manage.py runserver 127.0.0.1:8000
```

Open http://127.0.0.1:8000

Verify build:

```powershell
curl http://127.0.0.1:8000/api/version
```

## 6. First login checklist

1. Go to `/login/` and sign in with the admin account.
2. If you belong to multiple companies, choose one at `/select-company/`.
3. Upload an Excel register at `/` (see [EXCEL_SCHEMA.md](EXCEL_SCHEMA.md)).
4. Open `/dashboards/` and view a report via `/dashboards/<id>/serve/`.

## Production notes

- Set `DJANGO_SETTINGS_MODULE=config.settings.production` in `.env`.
- Set `DJANGO_DEBUG=false` and `ERROR_LOGGING_ENABLED=true`.
- Use HTTPS and update `ALLOWED_HOSTS`.
- Serve static/media via your web server or object storage as appropriate.
- Run `python manage.py collectstatic` before deploy.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: config` | Copy `config.example` → `config` |
| MySQL access denied | Check `.env` DB credentials |
| Redirect loop at login | Ensure at least one active `Company` exists |
| Excel company mismatch | Match Excel `Company` column to `Company.excel_company_names` in admin |
| Report shows old HTML | Use `/dashboards/<id>/ serve/?nocache=1` or re-upload |
