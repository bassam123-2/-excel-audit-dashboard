# Folder map

Use this as a map before opening `ai_excel_dashboard.py` (the largest file). Symbol index: **[CODE_MAP.md](CODE_MAP.md)**.

```
excel-audit-dashboard/
│
├── START_HERE.md                ← onboarding checklist for new developers
├── README.md                    ← overview, APIs, SMTP
├── requirements.txt             ← runtime Python packages
├── requirements-dev.txt         ← pytest, ruff, black
├── smtp_config.example.json     ← copy → smtp_config.json (never commit real config)
├── .env.example                 ← copy → .env (secrets, DB, SMTP)
│
├── manage.py                    ← ENTRY: Django commands / runserver
├── config/                      ← Django settings + urls (copy from config.example/)
├── config.example/              ← settings template — copy to config/ before first run
│
├── accounts_app/                ← login, 2FA, password expiry, company selection
├── audit_app/                   ← models, admin, company access, persistence
├── reports_app/                 ← upload, dashboards, version API
├── mail_app/                    ← email + audit-plan parse APIs
├── exports_app/                 ← export health endpoint
│
├── ai_excel_dashboard.py        ← report engine (monolith)
├── data_io.py                   ← read Excel / CSV
├── dashboard_locale.py          ← English / Arabic report strings
├── web_strings.py               ← Django shell UI strings
│
├── templates/                   ← Django HTML templates
├── locale/                      ← Django i18n files
├── assets/
│   ├── app_icon.ico
│   └── logos/                   ← company logos (company_a.png, _default.png, …)
│
├── docs/
│   ├── SETUP.md                 ← install from clone
│   ├── USER_GUIDE.md            ← end-user workflow
│   ├── CODE_MAP.md              ← symbol index for monolith
│   ├── FOLDER_MAP.md            ← this file
│   ├── ARCHITECTURE.md          ← data flow
│   ├── EXCEL_SCHEMA.md          ← required Excel columns
│   └── MYSQL_SETUP.md           ← database setup
│
├── scripts/
│   ├── run_web.ps1
│   ├── migrate.ps1
│   └── db_health.ps1
│
├── legacy/
│   └── README.md                ← removed legacy files log
│
└── examples/                    ← optional anonymized sample .xlsx
    └── README.md
```

## Not in Git (local only)

| Path | Why |
|------|-----|
| `config/` | Copied from `config.example/` per environment |
| `.env` | Secrets |
| `.venv/` | Python virtual environment |
| `smtp_config.json` | SMTP secrets |
| `media/` | Uploads, generated HTML cache, decks |

## If you need to change…

| Goal | Start here |
|------|------------|
| Login / 2FA / company selection | `accounts_app/views.py`, `accounts_app/middleware.py` |
| Upload page / Django routes | `reports_app/views.py`, `reports_app/urls.py` |
| Store upload / generate report | `reports_app/services/report_generation.py` |
| Approve / reject / delete | `reports_app/dashboard_workflow.py` |
| Audit charts, filters, logos in report | `ai_excel_dashboard.py` → `generate_finance_report` |
| Persisted data models | `audit_app/models.py` |
| Company tenant rules | `audit_app/company_access.py` |
| SMTP/PPTX APIs | `mail_app/views.py` |
| Excel column matching | `resolve_audit_observation_columns` in `ai_excel_dashboard.py` |
| Translations (report) | `dashboard_locale.py` |
| Translations (Django shell) | `web_strings.py`, `templates/` |
| How Excel is loaded | `data_io.py` |
| Build version string | `REPORT_VERSION` in `ai_excel_dashboard.py` |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full flow diagram.
