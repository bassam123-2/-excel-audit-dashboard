# Excel Audit Dashboard (Django + MySQL)

This project now runs on **Django** with **MySQL** and is structured for multi-developer collaboration.

Legacy logic from `ai_excel_dashboard.py` is reused through Django service modules to preserve report behavior while moving runtime execution to Django web-only flow.

Start with **[START_HERE.md](START_HERE.md)**, then **[docs/FOLDER_MAP.md](docs/FOLDER_MAP.md)** and **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### Web server

```bash
python manage.py runserver
# or: .\scripts\run_web.ps1
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), upload your `.xlsx` / `.csv`, and open the generated report.

Verify deploy:

```bash
curl http://127.0.0.1:8000/api/version
```

Response includes the report version and module file. Every HTML response also sends `X-Dashboard-Version`.

### Windows executable

```bash
pip install -r requirements-dev.txt
pyinstaller ai_excel_dashboard_v3_update.spec
```

Output: `dist/ai_excel_dashboard_v3_update.exe`. Place `smtp_config.json` next to the exe if you use email (see below).

## Django project layout

Full tree and “where to change what”: **[docs/FOLDER_MAP.md](docs/FOLDER_MAP.md)** · Data flow: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

| File / folder | Role |
|---------------|------|
| `START_HERE.md` | Onboarding checklist for new developers |
| `manage.py` | Django command entrypoint |
| `config/` | Django settings/urls/wsgi/asgi |
| `audit_app/` | Models, admin, extracted audit services |
| `reports_app/` | Upload/analyze/version views and report orchestration |
| `mail_app/` | `/api/send-obs-email`, `/api/parse-audit-plan-pptx` |
| `exports_app/` | Export-related endpoints/services |
| `scripts/` | `run_web.ps1`, `migrate.ps1`, `db_health.ps1`, `build_exe.ps1` |
| `ai_excel_dashboard.py` | Legacy monolith (reused logic during migration) |
| `web_app.py` | Deprecated Flask entrypoint shim |
| `data_io.py` | Read Excel/CSV into pandas |
| `dashboard_locale.py` | EN/AR UI strings |
| `export_bundle.py` | ZIP export (HTML, JSON, CSV summary, PDF) |
| `exact_dashboard.py` | Alternate reference-style dashboard renderer |
| `assets/logos/` | Company/subcompany logos for the header |
| `examples/` | Optional anonymized sample `.xlsx` for testing |
| `ai_excel_dashboard_v3_update.spec` | PyInstaller one-file build |
| `docs/EXCEL_SCHEMA.md` | Expected Excel columns and row rules |

## SMTP (optional — send observation email)

1. Copy `smtp_config.example.json` → `smtp_config.json` in the project root (or next to the `.exe`).
2. **Do not commit** `smtp_config.json` (it is in `.gitignore`).

Alternatively set environment variables (see `_smtp_config_from_env()` in `ai_excel_dashboard.py`), e.g. `AI_EXCEL_SMTP_HOST`, `AI_EXCEL_SMTP_USER`, `AI_EXCEL_SMTP_PASSWORD`.

## Web API (Django)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Upload form |
| `/analyze` | GET/POST | Analyze uploads and render report |
| `/api/version` | GET | JSON build version + module path |
| `/api/send-obs-email` | POST | Send observation email (needs SMTP config) |
| `/api/parse-audit-plan-pptx` | POST | Parse audit plan PowerPoint |

## Excel format

See **[docs/EXCEL_SCHEMA.md](docs/EXCEL_SCHEMA.md)** for required columns, optional fields, and how empty rows are filtered.

## MySQL setup

Use **[docs/MYSQL_SETUP.md](docs/MYSQL_SETUP.md)** for local service setup, DB/user creation, migrations, and health checks.

## Dependencies

Runtime (`requirements.txt`): Django, mysqlclient, pandas, openpyxl, fpdf2, python-pptx, Pillow.

Development build: `requirements-dev.txt` (adds PyInstaller).

## Contributor workflow

- Install dev tools: `pip install -r requirements-dev.txt`
- Run tests: `pytest`
- Lint/format: `ruff check .` and `black .`
- Optional hooks: `pre-commit install`
