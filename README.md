# Audit Dashboard (Django + MySQL)

This project now runs on **Django** with **MySQL** and is structured for multi-developer collaboration.

Legacy logic from `ai_excel_dashboard.py` is reused through Django service modules to preserve report behavior while moving runtime execution to Django web-only flow.

Start with **[START_HERE.md](START_HERE.md)**, then **[docs/SETUP.md](docs/SETUP.md)**, **[docs/FOLDER_MAP.md](docs/FOLDER_MAP.md)**, and **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Password storage (admin / auth users)

User passwords are **never stored in plain text**. Django’s auth system hashes each password before it is written to the database. In this project the default hasher is **PBKDF2 with SHA-256** (`pbkdf2_sha256`), with **1,000,000 iterations**, plus a per-user random **salt** and the resulting **hash** stored in the `auth_user.password` field.

That technical detail is intentionally **not shown** in the admin user edit screen. Admins change passwords via the inline **Password** / **Password confirmation** fields on the user form (or via the site profile page for their own account). The hash algorithm, iteration count, salt, and hash value are implementation details only and belong in this documentation—not in the UI.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
Copy-Item -Recurse config.example config   # Windows; see docs/SETUP.md
Copy-Item .env.example .env
```

Configure `.env` and MySQL, then migrate (see **[docs/SETUP.md](docs/SETUP.md)**).

### Web server

```bash
python manage.py runserver
# or: .\scripts\run_web.ps1
```

Open [http://127.0.0.1:8000/login/](http://127.0.0.1:8000/login/), select a company if prompted, upload at `/`, and open dashboards from `/dashboards/`.

Verify deploy:

```bash
curl http://127.0.0.1:8000/api/version
```

Response includes the report version and module file. Every HTML response also sends `X-Dashboard-Version`.

## Django project layout

Full tree and “where to change what”: **[docs/FOLDER_MAP.md](docs/FOLDER_MAP.md)** · Data flow: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**


| File / folder           | Role                                                    |
| ----------------------- | ------------------------------------------------------- |
| `START_HERE.md`         | Onboarding checklist for new developers                 |
| `docs/SETUP.md`         | Full install: config, .env, MySQL, admin bootstrap      |
| `docs/USER_GUIDE.md`    | End-user workflow (upload, review, Arabic UI)           |
| `docs/CODE_MAP.md`      | Symbol index for `ai_excel_dashboard.py`                |
| `manage.py`             | Django command entrypoint                               |
| `config/`               | Django settings/urls/wsgi/asgi (from `config.example/`) |
| `accounts_app/`         | Login, 2FA, password expiry, company selection          |
| `audit_app/`            | Models, admin, company access, persistence              |
| `reports_app/`          | Upload, dashboards, version API                         |
| `mail_app/`             | `/api/send-obs-email`, `/api/parse-audit-plan-pptx`     |
| `exports_app/`          | `/api/exports/health` monitoring endpoint               |
| `scripts/`              | `run_web.ps1`, `migrate.ps1`, `db_health.ps1`           |
| `ai_excel_dashboard.py` | Report engine (monolith)                                |
| `data_io.py`            | Read Excel/CSV into pandas                              |
| `dashboard_locale.py`   | EN/AR report UI strings                                 |
| `web_strings.py`        | EN/AR Django shell strings                              |
| `assets/logos/`         | Company/subcompany logos for the header                 |
| `examples/`             | Optional anonymized sample `.xlsx` for testing          |
| `docs/EXCEL_SCHEMA.md`  | Expected Excel columns and row rules                    |


## SMTP (optional — send observation email and 2FA)

Set SMTP variables in `**.env`** in the project root (copy from `.env.example`). Restart the server after changes.


| Variable                  | Example                  |
| ------------------------- | ------------------------ |
| `AI_EXCEL_SMTP_HOST`      | `smtp.gmail.com`         |
| `AI_EXCEL_SMTP_PORT`      | `587`                    |
| `AI_EXCEL_SMTP_USER`      | `noreply@YourDomain.com` |
| `AI_EXCEL_SMTP_PASSWORD`  | `your-smtp-password`     |
| `AI_EXCEL_SMTP_FROM`      | `noreply@YourDomain.com` |
| `AI_EXCEL_SMTP_FROM_NAME` | `Audit Dashboard`        |
| `AI_EXCEL_SMTP_USE_TLS`   | `true`                   |


Verify: `python manage.py test_smtp` (add `--send --to you@example.com` to send a probe message).

## Web API (Django)


| Endpoint                     | Method   | Purpose                                    |
| ---------------------------- | -------- | ------------------------------------------ |
| `/login/`                    | GET/POST | Authentication                             |
| `/select-company/`           | GET/POST | Choose active tenant                       |
| `/`                          | GET      | Upload form (login required)               |
| `/analyze`                   | POST     | Process upload → create dashboard draft    |
| `/dashboards/`               | GET      | List dashboards                            |
| `/dashboards/<id>/serve/`    | GET      | Generated report HTML                      |
| `/api/version`               | GET      | JSON build version + module path           |
| `/api/send-obs-email`        | POST     | Send observation email (needs SMTP config) |
| `/api/parse-audit-plan-pptx` | POST     | Parse audit plan PowerPoint                |
| `/api/exports/health`        | GET      | Health check for external monitoring       |


## Excel format

See **[docs/EXCEL_SCHEMA.md](docs/EXCEL_SCHEMA.md)** for required columns, optional fields, and how empty rows are filtered.

## AI dashboard templates (`template_type: ai`)

Dashboards created from the upload form (e.g. `/dashboards/2/`) use template code `**ai`**. The report inside the iframe is **English-only** regardless of site UI language. The surrounding Django pages (sidebar, toolbar) still follow the session language.

### Request flow

```
/dashboards/<id>/          → dashboard_detail view  → Django wrapper + iframe
/dashboards/<id>/serve/    → dashboard_serve view   → generated HTML (cached)
```

### Django templates (site shell around the report)


| Path                                          | Role                                                           |
| --------------------------------------------- | -------------------------------------------------------------- |
| `templates/reports_app/dashboard_detail.html` | Dashboard page: toolbar + `<iframe src="…/serve/">`            |
| `templates/reports_app/dashboard_list.html`   | List of saved dashboards                                       |
| `templates/reports_app/upload.html`           | Upload form (`/`)                                              |
| `templates/base.html`                         | Shared layout: sidebar, topbar, messages                       |
| `web_strings.py`                              | Bilingual strings for the Django shell (not the report iframe) |


### Report HTML generator (iframe content — not Django templates)

The audit dashboard HTML/CSS/JS is built in Python, not as `.html` files under `templates/`:


| Path                                                          | Role                                                                               |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `ai_excel_dashboard.py` → `generate_finance_report()`         | Main report builder; inline HTML template starts ~line 2245                        |
| `ai_excel_dashboard.py` → `build_audit_observation_payload()` | Audit observations table, filters, charts data                                     |
| `ai_excel_dashboard.py` → `build_multi_dashboard_shell()`     | Multi-workbook tab shell (legacy multi-file uploads)                               |
| `dashboard_locale.py`                                         | Report UI strings (`tr(loc, "…")`) — EN/AR keys                                    |
| `data_io.py`                                                  | Read Excel/CSV into pandas                                                         |
| `reports_app/services/report_generation.py`                   | `store_upload_to_db()`, `generate_from_db_data()`, `report_locale_for_dashboard()` |


Locale for `ai` dashboards is forced to `**en**` in:

- `reports_app/views.py` → `dashboard_serve()` (cache key + generation)
- `reports_app/services/report_generation.py` → `store_upload_to_db()`, `generate_from_db_data()`

### Cached report files


| Path                                           | Role                                                            |
| ---------------------------------------------- | --------------------------------------------------------------- |
| `media/dashboards/<id>_en.html`                | Cached English report for dashboard `<id>` (used for `ai` type) |
| `media/dashboards/<id>_ar.html`                | Arabic cache (only for non-`ai` template types, if added later) |
| `media/decks/<report_id>/deck*.pptx`           | Optional audit committee slide decks                            |
| `media/decks/<report_id>/high_risk_deck*.pptx` | Optional high-risk slide decks                                  |


Force regeneration after editing `ai_excel_dashboard.py`:

```
/dashboards/<id>/serve/?nocache=1
```

### Quick edit checklist

1. **Toolbar / breadcrumb / “Open in new tab”** → `templates/reports_app/dashboard_detail.html`, `web_strings.py`
2. **Chart labels, audit table, deck viewer, report layout** → `ai_excel_dashboard.py` (`generate_finance_report`)
3. **Report button/chart text (English)** → `dashboard_locale.py` (keys prefixed `audit_`, `metric_`, `ft_`, etc.)
4. **Upload form** → `templates/reports_app/upload.html`, `web_strings.py`
5. **When report is built / which locale** → `reports_app/services/report_generation.py`, `reports_app/views.py`

## MySQL setup

Use **[docs/MYSQL_SETUP.md](docs/MYSQL_SETUP.md)** for local service setup, DB/user creation, migrations, and health checks.

## Dependencies

Runtime (`requirements.txt`): Django, mysqlclient, pandas, openpyxl, fpdf2, python-pptx, Pillow.

Development build: `requirements-dev.txt` (pytest, ruff, black).

## Contributor workflow

- Install dev tools: `pip install -r requirements-dev.txt`
- Run tests: `pytest`
- Lint/format: `ruff check .` and `black .`
- Optional hooks: `pre-commit install`

