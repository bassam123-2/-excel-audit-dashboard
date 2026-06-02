# Contributing Guide

## Local setup
1. Create venv and install dependencies:
   - `python -m venv .venv`
   - `.\.venv\Scripts\Activate.ps1`
   - `pip install -r requirements-dev.txt`
2. Copy `.env.example` to `.env` and fill DB credentials.
3. Run migrations: `.\scripts\migrate.ps1`
4. Start app: `.\scripts\run_web.ps1`

## Branching
- Create feature branches from `main`.
- Keep PRs focused (single concern).
- Include test updates when touching behavior.

## Quality checks
- Run tests: `pytest`
- Lint: `ruff check .`
- Format: `black .`
- Optional hooks: `pre-commit install`

## Ownership boundaries
- `audit_app`: schema/models and persistence services
- `reports_app`: upload/analyze/version web flow
- `mail_app`: email and PPTX parse endpoints
- `exports_app`: export endpoints/services
- `ai_excel_dashboard.py`: legacy report engine logic reused by services
