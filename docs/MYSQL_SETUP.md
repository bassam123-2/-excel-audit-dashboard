# MySQL local setup for Django

## 1) Install and start MySQL service
- Install MySQL Server 8.x.
- Ensure service is running on `127.0.0.1:3306`.

## 2) Create database and app user
Run in MySQL shell:

```sql
CREATE DATABASE excel_dashboard CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'excel_dashboard_user'@'localhost' IDENTIFIED BY 'change-me';
GRANT ALL PRIVILEGES ON excel_dashboard.* TO 'excel_dashboard_user'@'localhost';
FLUSH PRIVILEGES;
```

## 3) Configure Django env
Copy `.env.example` to `.env` and set:
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST=127.0.0.1`
- `DB_PORT=3306`

## 4) Apply migrations
```powershell
.\scripts\migrate.ps1
```

## 5) Verify DB connection
```powershell
.\scripts\db_health.ps1
```

Expected output includes `MySQL connection OK`.

## Troubleshooting
- `Access denied`: check username/password and host in `.env`.
- `Can't connect to MySQL server`: verify MySQL service is running and listening on `3306`.
- Charset issues: keep DB/table charset as `utf8mb4`.
