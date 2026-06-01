# Start here (new developer)

Welcome. This project turns an **internal audit Excel register** into an **interactive HTML dashboard** (web or desktop).

## 1. Setup (once)

```powershell
cd "path\to\excel new"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Run the web app (easiest to test)

```powershell
.\scripts\run_web.ps1
```

Open http://127.0.0.1:5000 → upload a workbook → view the report.

Check version: http://127.0.0.1:5000/api/version

## 3. Read these docs (15 minutes)

| Doc | Content |
|-----|---------|
| [README.md](README.md) | Full setup, SMTP, deploy, APIs |
| [docs/FOLDER_MAP.md](docs/FOLDER_MAP.md) | What each file/folder is |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How data flows through the code |
| [docs/EXCEL_SCHEMA.md](docs/EXCEL_SCHEMA.md) | Required Excel columns |

## 4. Where the code lives

- **Most business logic + UI:** `ai_excel_dashboard.py` (very large — use search, not scroll)
- **Web server only:** `web_app.py`
- **Translations:** `dashboard_locale.py`

## 5. Optional: desktop .exe

```powershell
pip install -r requirements-dev.txt
.\scripts\build_exe.ps1
```

## 6. Before you push to GitHub

- Do **not** commit `smtp_config.json`, `.venv/`, `dist/`, or real audit Excel files with personal data
- Put a **small anonymized** sample in `examples/` if you add one

## 7. Common gotcha

After pulling new code on a server: **restart** the app, **re-upload** the Excel file, and **hard-refresh** the browser. Old HTML tabs do not pick up code changes.
