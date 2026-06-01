# Excel workbook schema (audit register)

The dashboard expects an **internal audit observation register** (one main sheet is read; see `data_io.read_input_file`).

Column headers are matched flexibly (case/spacing ignored). See `AUDIT_OBS_ALIASES` in `ai_excel_dashboard.py` for the full alias list.

## Required columns

| Logical field | Example header names |
|---------------|----------------------|
| Audit year | `Audit Year`, `Year`, `FY` |
| Department | `Department`, `Dept`, `Business Unit` |
| Audit cycle | `Audit Cycle/ Department`, `Audit Cycle` |
| IA status | `IA Status`, `Status` |
| Observation name | `Observation Name`, `Observation`, `Finding` |

**Optional:** `Function` / `Business Function` — if missing, the file can still load.

## Recommended columns

| Logical field | Example header names |
|---------------|----------------------|
| Company | `Company` |
| Subcompany | `Subcompany`, `Sub Company` |
| Rating | `Rating` |
| Observation type | `Observation Type` |
| Summary | `Summary of Observation` |
| Recommendation | `Recommendation` |
| Implementation due | `Implementation Due Date` |
| Target date | `Target Date` |
| Revised date | `Revised Date` |
| Observation ID | `Observation ID`, `Observation No` |
| Email | `Email` (for send-from-dashboard) |

## Row filtering

Rows are included in the audit observation chart when they have **either**:

- a non-empty **Audit Year**, or  
- a non-empty **Observation name**

Rows that only have **IA Status** (e.g. `Closed`) with no year and no observation title are **excluded**. That avoids a `(blank)` bucket in the Audit Year strip when Excel has trailing placeholder rows.

## Company logos

PNG files under `assets/logos/` map to filters:

- `nat.png`, `aum.png`, `saco.png`, `autostar.png`, `btc.png`
- `_default.png` — fallback logo

Subcompany logos can live in subfolders under `assets/logos/` (see `build_company_logo_catalog()`).

## Finance sheets

If the workbook also contains finance metrics (revenue, periods, etc.), the same file may drive finance KPIs and trends. Column detection is automatic (`detect_primary_columns`, `build_detected_profile`).
