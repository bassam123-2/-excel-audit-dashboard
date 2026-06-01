# Excel Audit Dashboard

Turn an internal-audit Excel register (and optional finance data) into an interactive HTML dashboard. Supports **desktop (Tk)** and **web (Flask)** modes, English/Arabic UI, company logos, email actions, and export (ZIP / PDF / PPTX).

Current report build: **`dashboard-v1.0.3`** (see `REPORT_VERSION` in `ai_excel_dashboard.py`).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
```

### Web server (recommended for shared use)

```bash
python web_app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), upload your `.xlsx` / `.csv`, and open the generated report.

Verify deploy:

```bash
curl http://127.0.0.1:5000/api/version
```

Response should include `"report_version": "dashboard-v1.0.3"`. Every HTML response also sends header `X-Dashboard-Version`.

### Desktop app

```bash
python ai_excel_dashboard.py
```

Pick a file in the GUI. The same report engine runs as on the web.

### Windows executable

```bash
pip install -r requirements-dev.txt
pyinstaller ai_excel_dashboard_v3_update.spec
```

Output: `dist/ai_excel_dashboard_v3_update.exe`. Place `smtp_config.json` next to the exe if you use email (see below).

## Project layout

| File / folder | Role |
|---------------|------|
| `ai_excel_dashboard.py` | Core logic, audit payload, HTML/JS report template, Tk GUI, SMTP helpers (~12k lines) |
| `web_app.py` | Flask upload UI and APIs |
| `data_io.py` | Read Excel/CSV into pandas |
| `dashboard_locale.py` | EN/AR UI strings |
| `export_bundle.py` | ZIP export (HTML, JSON, CSV summary, PDF) |
| `exact_dashboard.py` | Alternate reference-style dashboard renderer |
| `assets/logos/` | Company/subcompany logos for the header |
| `ai_excel_dashboard_v3_update.spec` | PyInstaller one-file build |
| `docs/EXCEL_SCHEMA.md` | Expected Excel columns and row rules |

## SMTP (optional — send observation email)

1. Copy `smtp_config.example.json` → `smtp_config.json` in the project root (or next to the `.exe`).
2. **Do not commit** `smtp_config.json` (it is in `.gitignore`).

Alternatively set environment variables (see `_smtp_config_from_env()` in `ai_excel_dashboard.py`), e.g. `AI_EXCEL_SMTP_HOST`, `AI_EXCEL_SMTP_USER`, `AI_EXCEL_SMTP_PASSWORD`.

## Web API (Flask)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Upload form |
| `/analyze` | POST | Upload file(s), returns HTML report |
| `/api/version` | GET | JSON build version + module path |
| `/api/send-obs-email` | POST | Send observation email (needs SMTP config) |
| `/api/parse-audit-plan-pptx` | POST | Parse audit plan PowerPoint |

## Excel format

See **[docs/EXCEL_SCHEMA.md](docs/EXCEL_SCHEMA.md)** for required columns, optional fields, and how empty rows are filtered.

## Deploying updates

1. Pull latest code on the server.
2. Restart the Python process (only **one** listener on port `5000`).
3. Confirm `/api/version` shows the expected `report_version`.
4. **Re-upload** the workbook and hard-refresh the browser — do not reuse an old saved HTML tab.

## Dependencies

Runtime (`requirements.txt`): Flask, pandas, openpyxl, fpdf2, python-pptx, Pillow.

Development build: `requirements-dev.txt` (adds PyInstaller).

## Notes for contributors

- Most UI changes live inside the large HTML/JS string in `ai_excel_dashboard.py` (search for `generate_finance_report` and audit observation JS).
- Logo switching uses `build_company_logo_catalog()` and filter IDs `brand-filter-co` / `brand-filter-sc` in the report.
- Audit year colors use a gray gradient (`auditYearGradientAt`); version bumps should update `REPORT_VERSION` when behavior changes.
