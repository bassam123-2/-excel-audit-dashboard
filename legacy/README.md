# Legacy runtime notes

This folder documents deprecated runtime paths kept only for migration safety.

## Deprecated entrypoints

- `web_app.py` Flask server path is deprecated; it now redirects execution to Django.
- Direct desktop execution via `python ai_excel_dashboard.py` is deprecated for team workflow.

## Active runtime

Use Django web runtime:

```powershell
.\scripts\run_web.ps1
```

or:

```powershell
python manage.py runserver 127.0.0.1:8000
```
