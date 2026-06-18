# Regression Test Catalog

Run after every change:

```powershell
pytest -m regression -q
python scripts/run_tests.py
```

## Auth (AUTH)

| ID | Scenario | Test file | Status |
|----|----------|-----------|--------|
| AUTH-01 | Invalid login | `tests/regression/test_auth_regression.py` | planned |
| AUTH-08 | must_change_password redirect | `accounts_app/tests/test_must_change_password.py` | covered |
| AUTH-04 | Open redirect blocked | `accounts_app/tests/test_login_next_redirect.py` | covered |

## Validation (VAL)

| ID | Scenario | Test file | Status |
|----|----------|-----------|--------|
| VAL-01 | Duplicate email on create | `tests/regression/test_validation_regression.py` | covered |
| VAL-02 | Duplicate email on change | `tests/regression/test_validation_regression.py` | covered |
| VAL-03 | Required fields empty | `tests/regression/test_validation_regression.py` | covered |
| VAL-04 | Username with spaces | `tests/regression/test_validation_regression.py` | covered |

## OTP (OTP)

| ID | Scenario | Test file | Status |
|----|----------|-----------|--------|
| OTP-04 | Resend cooldown matches OTP TTL | `accounts_app/tests/test_otp_resend_cooldown.py` | covered |

## Schema / Migrations (DB)

| ID | Scenario | Test file | Status |
|----|----------|-----------|--------|
| DB-10 | All accounts_app migrations applied | `tests/regression/test_schema_migrations.py` | covered |
| DB-11 | UserProfile.must_change_password_on_login column exists | `tests/regression/test_schema_migrations.py` | covered |
| DB-12 | Login GET/POST without OperationalError | `tests/regression/test_schema_migrations.py` | covered |
| DB-13 | Password middleware reads profile | `tests/regression/test_schema_migrations.py` | covered |

## Admin (ADM)

| ID | Scenario | Test file | Status |
|----|----------|-----------|--------|
| ADM-01 | Admin add user with required fields | `audit_app/tests/test_admin_user_forms.py` | covered |
| ADM-12 | Password generator | `accounts_app/tests/test_password_generator.py` | covered |
| ADM-19 | Admin set-password POST (no gettext shadow bug) | `audit_app/tests/test_admin_user_forms.py` | covered |

## Maintenance

| Command | Purpose |
|---------|---------|
| `python manage.py check_duplicate_emails` | Detect duplicate emails before deploy |
