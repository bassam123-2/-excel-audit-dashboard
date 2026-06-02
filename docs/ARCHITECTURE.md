# Architecture

## High-level flow

```mermaid
flowchart LR
  subgraph input
    XLSX[Excel / CSV file]
    PPTX[Optional audit plan PPTX]
  end

  subgraph python
    DJANGO[reports_app/mail_app]
    IO[data_io.read_input_file]
    CORE[ai_excel_dashboard]
    LOC[dashboard_locale]
    EXP[export_bundle]
  end

  subgraph output
    HTML[Interactive HTML report]
    ZIP[ZIP / PDF export]
    MAIL[SMTP email]
  end

  XLSX --> DJANGO --> IO --> CORE
  PPTX --> DJANGO --> CORE
  CORE --> LOC
  CORE --> HTML
  CORE --> EXP --> ZIP
  DJANGO --> MAIL
```

## Runtime mode

| Mode | Entry file | User action |
|------|------------|-------------|
| **Web (active)** | `manage.py` + `config/` | Browser upload at `/` → `/analyze` |
| **Desktop (legacy)** | `ai_excel_dashboard.py` | Kept only for transition |

Both call **`generate_finance_report()`** in `ai_excel_dashboard.py`, which:

1. Loads the dataframe (`data_io`)
2. Detects columns (`resolve_audit_observation_columns`, `detect_primary_columns`)
3. Builds JSON payloads (`build_audit_observation_payload`, finance KPIs, logos)
4. Embeds payloads into a single HTML page (large inline JavaScript)
5. Optionally injects API URLs for email / PPTX parse (via `reports_app.services.report_generation`)

## Important symbols in `ai_excel_dashboard.py`

| Symbol | Line area (approx.) | Role |
|--------|---------------------|------|
| `REPORT_VERSION` | top | Deploy tag; bump when report logic changes |
| `build_company_logo_catalog` | ~187 | Maps Company/Subcompany → logo images |
| `resolve_audit_observation_columns` | ~904 | Excel header → logical fields |
| `build_audit_observation_payload` | ~1035 | Rows + filters for audit UI |
| `_audit_observation_row_is_usable` | ~829 | Drops empty trailing Excel rows |
| `generate_finance_report` | ~1966 | Main HTML generator |
| `main` | ~12843 | Tk desktop entry |

Search the file for these names rather than reading top-to-bottom.

## Web-only pieces (Django)

- Upload form and analyze flow (`reports_app/views.py`)
- `GET /api/version` — confirm deployed build
- `POST /api/send-obs-email` (`mail_app/views.py`)
- `POST /api/parse-audit-plan-pptx` (`mail_app/views.py`)

## `exact_dashboard.py`

Separate code path that renders a **reference-style** dashboard from similar data. Used when integrating a fixed layout; not the main audit HTML most users see. Check `reports_app/services/report_generation.py` for when it runs.

## Future refactor (optional)

To make the repo easier long-term, consider splitting `ai_excel_dashboard.py` into:

- `audit_columns.py` — column resolution + payload
- `report_html/` — `.html` + `.js` templates
- `gui_app.py` — Tk only
- `smtp_helpers.py` — mail config

No refactor is required to run or deploy the current project.
