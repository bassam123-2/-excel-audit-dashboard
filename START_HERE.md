# Start here (new developer)

Welcome. This project turns an **internal audit Excel register** into an **interactive HTML dashboard** (Django web + MySQL).

## 1. Setup (once)

```powershell
cd "path\to\excel-audit-dashboard"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy required config (see [docs/SETUP.md](docs/SETUP.md)):

```powershell
Copy-Item -Recurse config.example config
Copy-Item .env.example .env
# Edit .env with your DB and secret key
```

## 2. Database and first admin

```powershell
.\scripts\migrate.ps1
python manage.py create_default_admin
python manage.py setup_groups
python manage.py setup_companies
```

See [docs/MYSQL_SETUP.md](docs/MYSQL_SETUP.md) for MySQL details.

## 3. Run the web app

```powershell
.\scripts\run_web.ps1
```

**Correct user flow** (auth required):

1. http://127.0.0.1:8000/login/
2. http://127.0.0.1:8000/select-company/ (if multiple companies)
3. http://127.0.0.1:8000/ — upload Excel
4. http://127.0.0.1:8000/dashboards/ — list dashboards
5. Open a report via `/dashboards/<id>/serve/`

Check version: http://127.0.0.1:8000/api/version

## 4. Read these docs (~20 minutes)

| Doc | Content |
|-----|---------|
| [README.md](README.md) | Overview, APIs, SMTP |
| [docs/SETUP.md](docs/SETUP.md) | Full install from clone |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | End-user workflow |
| [docs/FOLDER_MAP.md](docs/FOLDER_MAP.md) | What each file/folder is |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Data flow |
| [docs/CODE_MAP.md](docs/CODE_MAP.md) | Symbol index for the monolith |
| [docs/EXCEL_SCHEMA.md](docs/EXCEL_SCHEMA.md) | Required Excel columns |

## 5. Where the code lives

- **Django runtime:** `manage.py`, `config/`, `accounts_app/`, `reports_app/`, `mail_app/`, `audit_app/`, `exports_app/`
- **Report engine:** `ai_excel_dashboard.py` (very large — use [docs/CODE_MAP.md](docs/CODE_MAP.md))
- **Translations:** `dashboard_locale.py`, `web_strings.py`
- **Removed legacy paths:** see [legacy/README.md](legacy/README.md)

## 6. Before you push to GitHub

- Do **not** commit `.env`, `.venv/`, `dist/`, or real audit Excel with personal data
- Put a **small anonymized** sample in `examples/` if you add one

## 7. Common gotcha

After pulling new code on a server: run migrations, restart Django, **re-upload** or use `?nocache=1` on serve URLs. Cached HTML under `media/dashboards/` does not pick up code changes automatically.

