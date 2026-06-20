# User guide

End-user workflow for the Audit Dashboard (Arabic UI supported via language switcher).

## Before you start

You need:

- A valid account (username + password)
- Access to at least one **company** (tenant)
- An internal audit Excel register matching [EXCEL_SCHEMA.md](EXCEL_SCHEMA.md)

Optional: PowerPoint decks for audit committee slides (per company settings).

## 1. Sign in

1. Open http://127.0.0.1:8000/login/ (or your production URL).
2. Enter username and password.
3. If **two-factor authentication** is enabled on your account, enter the code sent to your email (SMTP must be configured on the server).
4. If your password has expired, you will be prompted to set a new one.

## 2. Select company

If you belong to more than one company, you are redirected to **Select company** (`/select-company/`).

- Choose the company whose data you will upload or review.
- Switch later via the company switcher in the top bar (`/switch-company/`).

The Excel file you upload must match the selected company (see **Company column** below).

## 3. Upload a dashboard

1. Go to **Upload** (`/`) — requires upload permission for the active company.
2. Fill in:
   - **Dashboard name** — display name in the list
   - **Description** (optional)
   - **Icon** — shown in the dashboard list
3. Attach the Excel file (`file1`; optional `file2`–`file4` for multi-workbook bundles).
4. Attach optional slide decks if your company enables them (audit committee, high risk, TGA violations, etc.).
5. Submit the form (`POST /analyze`).

The system stores row data in the database and creates a dashboard in **Draft** status. HTML is generated when you open the report, not at upload time.

## 4. View dashboards

1. Open **Dashboards** (`/dashboards/`).
2. Click a dashboard to open the detail page (`/dashboards/<id>/`).
3. The report loads in an iframe from `/dashboards/<id>/serve/`.

**AI template dashboards** (`template_type: ai`) always render the report content in **English**. The surrounding site (sidebar, toolbar) follows your UI language (Arabic or English).

To force regeneration after a server update:

```
/dashboards/<id>/serve/?nocache=1
```

## 5. Dashboard lifecycle (workflow)

| Status | Meaning |
|--------|---------|
| **Draft** | Saved by uploader; private to creator until submitted |
| **Under review** | Submitted; locked for editing; reviewers can approve or reject |
| **In workflow** | Approved; moving through configured acknowledgment steps |
| **Published** | Fully approved and visible to viewers |
| **Rejected** | Returned to creator with a reason (private until resubmitted) |

Typical flow (when **Use multi-step workflow** is enabled on the company):

1. **Upload** → **Draft** (creator only)
2. **Submit for review** → **Under review** (reviewers notified)
3. **Approve** → **In workflow** (each assignee clicks **Acknowledged**)
4. Last acknowledgment → **Published** (viewers notified)

Actions (depending on your permissions):

- **Submit for review** — uploader sends a draft to reviewers
- **Approve** — reviewer accepts (starts workflow or publishes if no steps configured)
- **Acknowledged** — workflow assignee confirms their step
- **Reject** — reviewer returns dashboard with mandatory feedback → **Rejected**
- **Edit draft / Resubmit** — uploader fixes data (draft or after rejection)
- **Delete** — remove draft (if allowed) or soft-delete (superuser)
- **Restore** — recover a deleted dashboard

Users with **view own only** see dashboards they created; viewers see published company dashboards; reviewers see submitted/workflow/published items (not others' private drafts or rejections).

List **filters** (chip bar) appear when you have multiple visibility buckets — e.g. **Needs my review**, **Published**, **My dashboards**.

## 6. Excel company matching

The upload validates the **Company** column in your Excel against the active tenant:

- Each `Company` in Django admin has `excel_company_names` — aliases that match Excel values.
- If the file names a company that does not match the selected tenant, upload fails with a clear error.

Configure companies and logos in Django admin (`/admin/`).

## 7. Sending observation email (optional)

From within the report iframe, users can email audit observations if SMTP is configured.

Server endpoints:

- `POST /api/send-obs-email`
- `POST /api/parse-audit-plan-pptx` — parse audit plan PowerPoint

Contact your administrator if email actions show “SMTP not configured”.

## 8. Language

- Use the language switcher to toggle **Arabic / English** for Django pages.
- Report iframe language follows template rules (AI = English only).

## 9. Profile and password

- **Profile** (`/profile/`) — update password, view job title
- Password complexity rules apply (see admin documentation)

## Common issues

| Problem | What to do |
|---------|------------|
| Cannot access upload | Ask admin for upload permission on your company membership |
| Wrong company after upload | Re-select company before uploading; Excel company must match |
| Empty report | Check Excel has required columns; see EXCEL_SCHEMA.md |
| Old charts after code update | Hard-refresh browser or open serve URL with `?nocache=1` |

For installation and admin tasks, see [SETUP.md](SETUP.md).
