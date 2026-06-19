# Removed legacy components (2025–2026 cleanup)

The following files were **removed** from the repository. Django is the only supported runtime.

| File | Was | Removed because |
|------|-----|----------------|
| `web_app.py` | Flask upload/analyze server | Replaced by Django `reports_app` |
| `export_bundle.py` | ZIP/PPTX export helpers | Only used by Flask path |
| `exact_dashboard.py` | Reference-layout renderer | Unused (`mode=exact` path dead) |
| `scripts/run_desktop.ps1` | Desktop launcher stub | Deprecated |
| `scripts/stop_port_5000.ps1` | Kill Flask port 5000 | Django uses port 8000 |
| `audit_app/services/audit_processing.py` | Thin wrapper | Tests import `ai_excel_dashboard` directly |
| `ai_excel_dashboard_v3_update.spec` | PyInstaller spec | Web-only deployment |
| `scripts/build_exe.ps1` | PyInstaller build script | Web-only deployment |
| Tkinter GUI in `ai_excel_dashboard.py` | Desktop file-picker UI | Web-only deployment |

## Active runtime

```powershell
.\scripts\run_web.ps1
```

or:

```powershell
python manage.py runserver 127.0.0.1:8000
```

Running `python ai_excel_dashboard.py` redirects to the Django dev server.
