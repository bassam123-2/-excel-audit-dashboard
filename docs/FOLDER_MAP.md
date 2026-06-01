# Folder map

Use this as a map before opening `ai_excel_dashboard.py` (the largest file).

```
excel-dashboard/                 ← rename repo on GitHub if possible (no spaces)
│
├── START_HERE.md                ← onboarding checklist for new developers
├── README.md                    ← install, run, deploy
├── requirements.txt             ← runtime Python packages
├── requirements-dev.txt         ← + PyInstaller for .exe build
├── smtp_config.example.json     ← copy → smtp_config.json (never commit real config)
│
├── web_app.py                   ← ENTRY: Flask web server (port 5000)
├── ai_excel_dashboard.py        ← ENTRY: desktop GUI + report engine + HTML/JS
├── data_io.py                   ← read Excel / CSV
├── dashboard_locale.py          ← English / Arabic UI strings
├── export_bundle.py             ← ZIP / PDF export
├── exact_dashboard.py           ← alternate “reference layout” renderer (optional path)
│
├── ai_excel_dashboard_v3_update.spec   ← PyInstaller → dist/*.exe
│
├── assets/
│   ├── app_icon.ico
│   ├── aagh_logo.png
│   └── logos/                   ← company logos (nat, aum, saco, …)
│
├── docs/
│   ├── FOLDER_MAP.md            ← this file
│   ├── ARCHITECTURE.md          ← data flow + “where to change what”
│   └── EXCEL_SCHEMA.md          ← required Excel columns
│
├── scripts/                     ← double-click or run from terminal
│   ├── run_web.ps1
│   ├── run_desktop.ps1
│   ├── build_exe.ps1
│   └── stop_port_5000.ps1
│
└── examples/                    ← put a small sample .xlsx here for testing
    └── README.md
```

## Not in Git (local only)

| Path | Why |
|------|-----|
| `.venv/` | Python virtual environment |
| `dist/`, `build/` | PyInstaller output |
| `smtp_config.json` | Secrets |
| `audit_logs/*.json` | Runtime upload logs |
| `*.html` | Generated reports (re-create by upload) |

## If you need to change…

| Goal | Start here |
|------|------------|
| Upload page / Flask routes | `web_app.py` |
| Audit charts, filters, logos in report | `ai_excel_dashboard.py` → search `build_audit_observation_payload`, `syncBrandLogo` |
| Excel column matching | `ai_excel_dashboard.py` → `AUDIT_OBS_ALIASES`, `resolve_audit_observation_columns` |
| Translations | `dashboard_locale.py` |
| How Excel is loaded | `data_io.py` |
| Export ZIP/PDF | `export_bundle.py` |
| Build version string | `REPORT_VERSION` in `ai_excel_dashboard.py` |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full flow diagram.
