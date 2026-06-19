# Redis setup — local (Windows/Laragon) and VPS

Redis is **required** for email OTP and shared cache in this project.  
OTP codes, resend cooldowns, and login rate limits are stored in Redis so **every Django worker** reads the same data.

Without Redis (or with `LocMemCache` only), OTP may fail on the first attempt and work only after resend — especially when multiple app processes are running.

Related docs: [SETUP.md](SETUP.md) · [MYSQL_SETUP.md](MYSQL_SETUP.md)

---

## 1) Why Redis?


| Without shared cache                                | With Redis                  |
| --------------------------------------------------- | --------------------------- |
| Each Gunicorn/runserver worker has its own memory   | All workers share one cache |
| OTP stored on Worker A, verify hits Worker B → fail | OTP visible from any worker |
| Resend may accidentally “fix” the issue             | First OTP works reliably    |


The project reads `REDIS_URL` from `.env` and configures Django `CACHES` automatically (`config/settings/base.py`).

---

## 2) Environment variable (both local and VPS)

Add to `.env`:

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

With password (recommended on VPS if you enable `requirepass`):

```env
REDIS_URL=redis://:YOUR_STRONG_REDIS_PASSWORD@127.0.0.1:6379/1
```


| Part        | Meaning                             |
| ----------- | ----------------------------------- |
| `127.0.0.1` | Redis on the same machine as Django |
| `6379`      | Default Redis port                  |
| `/1`        | Redis database number (0–15)        |


After changing `.env`, restart Django / Gunicorn.

Install Python package (once per environment):

```powershell
pip install redis
```

Or from project root:

```powershell
pip install -r requirements.txt
```

### 2.1 `REDIS_PROTOCOL` — when to set it (local vs VPS)

The Python client (`redis` 5.x) may use **RESP3** and send the `HELLO` command. **Redis older than 6.0** does not understand `HELLO` and login fails with:

```text
ResponseError: unknown command 'HELLO'
```

The project reads optional `REDIS_PROTOCOL` from `.env` only when you set it (`config/settings/base.py`). If unset, the client uses its default (fine for Redis 6+).

| Redis version | `REDIS_PROTOCOL=2` in `.env` |
| ------------- | ---------------------------- |
| **6.0 or newer** (typical VPS with `apt` / `dnf`) | **No** — omit the variable |
| **Older than 6.0** (e.g. Laragon 3.2 on Windows) | **Yes** — add `REDIS_PROTOCOL=2` |

**Rule of thumb**

- **VPS (production):** usually **do not** set `REDIS_PROTOCOL`.
- **Local Laragon:** add `REDIS_PROTOCOL=2` if you see the `HELLO` error.

#### Check installed Redis version (VPS or server)

Run any of:

```bash
redis-server --version
redis-cli --version
redis-cli INFO server | grep redis_version
```

Example output:

```text
redis_version:7.2.4
```

or:

```text
Redis server v=6.2.14
```

If the major version is **6** or **7**, leave `REDIS_PROTOCOL` unset.

#### Example `.env` files

**VPS (production)** — no `REDIS_PROTOCOL`:

```env
REDIS_URL=redis://127.0.0.1:6379/1
# REDIS_URL=redis://:YOUR_STRONG_REDIS_PASSWORD@127.0.0.1:6379/1
```

**Local Laragon only** (if `HELLO` error):

```env
REDIS_URL=redis://127.0.0.1:6379/1
REDIS_PROTOCOL=2
```

#### Verify Django can use the cache

From the project directory:

```bash
source .venv/bin/activate
python manage.py shell -c "from django.core.cache import cache; cache.set('t',1,10); print(cache.get('t'))"
```

Expected: `1`. If login with 2FA works on the **first** OTP attempt, Redis is configured correctly.

---

## 3) Local setup — Windows + Laragon

Choose **one** of the options below.

### Option A — Memurai (recommended on Windows)

Memurai is Redis-compatible and runs natively on Windows.

1. Download and install: [https://www.memurai.com/](https://www.memurai.com/)
2. Start the Memurai service (usually starts automatically).
3. Verify in PowerShell:

```powershell
memurai-cli ping
```

Expected: `PONG`

1. Set in `.env`:

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

1. Restart Django:

```powershell
.\scripts\run_web.ps1
```

---

### Option B — WSL2 (Ubuntu on Windows)

1. Install WSL2 and Ubuntu from Microsoft Store.
2. Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y redis-server
sudo service redis-server start
redis-cli ping
```

1. Ensure Redis listens on all interfaces inside WSL (if Django runs on Windows host, you may need WSL IP — simpler: run Django inside WSL too).
2. `.env` on Windows host (if Redis port is forwarded):

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

> **Tip:** For Laragon, Option A (Memurai) is usually simpler than WSL networking.

---

### Option D — Laragon built-in Redis (full install)

If you use the **full** Laragon package (not Laragon Lite), Redis is already bundled — typically Redis **3.2.x** for Windows.  
This Django project only needs the **Redis server** running; you do **not** need the PHP `redis` extension unless you use PHP tools (e.g. phpRedisAdmin).

Reference guide (PHP extension + Laragon UI): [Redis on Laragon (DEV)](https://dev.to/dendihandian/installing-php-redis-extension-on-laragon-2mp3)

#### D.1 Start Redis from Laragon (recommended)

1. Open **Laragon** → **Menu** → **Preferences** → **Services & Ports**.
2. Enable **Redis** and confirm port **6379**.
3. **Start All** (or start Redis from the Laragon tray menu).

Redis should listen on `127.0.0.1:6379`.

#### D.2 Start Redis manually (alternative)

Full Laragon installs Redis under a path similar to:

```text
C:\laragon\bin\redis\redis-x64-3.2.100
```

In PowerShell or Command Prompt:

```powershell
cd C:\laragon\bin\redis\redis-x64-3.2.100
.\redis-server.exe
```

Leave the window open while developing, or use **D.1** so Laragon starts Redis with other services. Stop with `Ctrl+C` when running manually.

#### D.3 Project `.env`

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

Restart Django after saving `.env`.

> **Laragon Redis 3.2 only:** If login shows `unknown command 'HELLO'`, add to **local** `.env` only:  
> `REDIS_PROTOCOL=2`  
> Do **not** set this on VPS — production Redis from `apt` is 6+ and works without it.

#### D.4 Verify

```powershell
# If redis-cli is on PATH (Laragon / same redis folder):
redis-cli ping
```

Expected: `PONG`

Then run the [local verification](#local-verification) `cache.set` / `cache.get` test below.

#### D.5 Optional — PHP Redis extension (not required for Django)

Only needed if you want **phpRedisAdmin** in Laragon (`http://localhost/redis`) or PHP apps using Redis.  
Django uses the Python `redis` package from `requirements.txt`, not `php_redis.dll`.

If you still want the PHP extension (from the [DEV article](https://dev.to/dendihandian/installing-php-redis-extension-on-laragon-2mp3)):

1. Download the matching DLL from [PECL redis](https://pecl.php.net/package/redis) for your Laragon PHP version (check **NTS** vs **TS** on the Laragon dashboard).
2. Copy `php_redis.dll` to your PHP `ext` folder, e.g.
  `C:\laragon\bin\php\php-8.x.x-Win32-vs16-x64\ext`
3. Add to that PHP version’s `php.ini`:
  `extension=php_redis.dll`
4. Restart Apache/nginx in Laragon. Confirm under **PHP → Extensions** that `redis` appears.

> **Note:** Native Redis on Windows is limited to older 3.x builds in Laragon. For newer Redis features locally, use **Docker (Option C)** or **Memurai (Option A)**.

---

### Option C — Docker (optional)

Requires **Docker Desktop** installed **and running** on Windows.

```powershell
docker run -d --name redis --restart unless-stopped -p 127.0.0.1:6379:6379 redis:alpine
docker exec redis redis-cli ping
```

`.env`:

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

#### Docker error on Windows

If you see:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

**Cause:** Docker Desktop is not installed or not running.

**Fix:** Start Docker Desktop, or use **Memurai (Option A)** instead.

---

### Local verification

```powershell
python manage.py shell
```

```python
from django.core.cache import cache
cache.set("redis_test", "ok", 60)
print(cache.get("redis_test"))  # should print: ok
```

Then test login with 2FA (OTP email).

---

### Local OTP admin settings

After `python manage.py migrate`:

1. Open Django admin → **Project security settings**
2. Set **OTP validity (minutes)** (default: 10)
3. Resend cooldown uses the **same** duration automatically

---

## 4) VPS setup — Linux

Assumes Django (Gunicorn) and Redis run on the **same VPS**.

Package and service names depend on your distro:

| Distro | Install command | systemd service |
|--------|-----------------|-----------------|
| Ubuntu / Debian | `apt install redis-server` | `redis-server` |
| Fedora / AlmaLinux / Rocky / RHEL | `dnf install redis` | `redis` |

Do **not** set `REDIS_PROTOCOL` in production `.env` — VPS Redis is 6+ and works with the default `redis-py` client.

### 4.1 Install Redis

#### Ubuntu / Debian (`apt`)

```bash
sudo apt update
sudo apt install -y redis-server
```

#### Fedora / AlmaLinux / Rocky / RHEL (`dnf`)

The Debian package name `redis-server` **does not exist** on `dnf` systems. Use **`redis`**:

```bash
sudo dnf install -y redis
```

If you see `No match for argument: redis`, enable **EPEL** (common on AlmaLinux / Rocky / RHEL) and retry:

```bash
sudo dnf install -y epel-release
sudo dnf install -y redis
```

Still no package? Use [Docker Redis (section 5)](#5-vps--docker-alternative-optional) or install from [Redis official packages](https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/) for your distro.

### 4.2 Enable and start service

**Ubuntu / Debian:**

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
sudo systemctl status redis-server
redis-cli ping
```

**Fedora / AlmaLinux / Rocky / RHEL (`dnf`):**

```bash
sudo systemctl enable redis
sudo systemctl start redis
sudo systemctl status redis
redis-cli ping
```

Expected: `PONG`

### 4.3 Secure Redis (important)

Config file path **depends on the distro**. Do not create a new file at a path that does not exist.

**Find the real config path:**

```bash
# Installed config files from the redis package
rpm -ql redis 2>/dev/null | grep -E '\.conf$'

# Or search under /etc
sudo find /etc -maxdepth 3 -name '*redis*.conf' 2>/dev/null

# Or read what systemd uses when starting Redis
systemctl cat redis | grep -E 'conf|redis-server'
```

| Distro | Typical config path |
|--------|---------------------|
| Ubuntu / Debian | `/etc/redis/redis.conf` |
| AlmaLinux / Rocky / RHEL (often) | `/etc/redis.conf` |
| Fedora (some versions) | `/etc/redis/redis.conf` |

Edit the file that **already exists** (examples):

```bash
# Debian/Ubuntu
sudo nano /etc/redis/redis.conf

# AlmaLinux / Rocky / RHEL (common)
sudo nano /etc/redis.conf
```

Ensure:

```conf
bind 127.0.0.1 ::1
protected-mode yes
```

Optional but recommended — set a password:

```conf
requirepass YOUR_STRONG_REDIS_PASSWORD
```

**Quick check without editing** (current runtime values):

```bash
redis-cli CONFIG GET bind
redis-cli CONFIG GET protected-mode
redis-cli CONFIG GET requirepass
```

If `bind` is already `127.0.0.1` and Redis is not exposed on the public firewall, you may only need `requirepass` for production hardening.

Restart:

**Ubuntu / Debian:**

```bash
sudo systemctl restart redis-server
```

**dnf (`redis` service):**

```bash
sudo systemctl restart redis
```

Test with password:

```bash
redis-cli -a YOUR_STRONG_REDIS_PASSWORD ping
```

### 4.4 Firewall

**Do not** expose port 6379 to the public internet.

Redis should only be reachable from `127.0.0.1` on the same server.

- **Ubuntu (ufw):** do not run `ufw allow 6379` unless Redis is on a separate server.
- **AlmaLinux / Rocky (firewalld):** do not open `6379/tcp` in the public zone.

### 4.5 Configure project `.env` on VPS

Without password:

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

With password:

```env
REDIS_URL=redis://:YOUR_STRONG_REDIS_PASSWORD@127.0.0.1:6379/1
```

Do **not** set `REDIS_PROTOCOL` on VPS.

Also ensure production settings:

```env
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=your-domain.com,www.your-domain.com
```

### 4.6 Install dependencies and migrate

```bash
cd /path/to/excel-audit-dashboard
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

### 4.7 Restart application server

Example with systemd service named `gunicorn`:

```bash
sudo systemctl restart gunicorn
```

Or your process manager (supervisor, etc.).

### 4.8 VPS verification

```bash
python manage.py shell
```

```python
from django.core.cache import cache
cache.set("redis_test", "ok", 60)
print(cache.get("redis_test"))
```

Test full flow:

1. Sign in with a user that has 2FA enabled
2. Receive OTP email
3. Enter code on **first attempt** — should succeed

---

## 5) VPS — Docker alternative (optional)

If Docker is already installed on the VPS:

```bash
docker run -d --name redis --restart unless-stopped \
  -p 127.0.0.1:6379:6379 \
  redis:alpine

docker exec redis redis-cli ping
```

Same `.env`:

```env
REDIS_URL=redis://127.0.0.1:6379/1
```

---

## 6) Architecture (production)

```text
                    ┌─────────────┐
   Internet ───────►│ Nginx       │
                    │ (HTTPS)     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ Gunicorn    │
                    │ Worker 1..N │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌───▼───┐ ┌──────▼──────┐
       │ Redis       │ │ MySQL │ │ SMTP        │
       │ 127.0.0.1   │ │       │ │ (email OTP) │
       └─────────────┘ └───────┘ └─────────────┘
```

---

## 7) Troubleshooting


| Symptom                                                 | Likely cause                        | Fix                                                           |
| ------------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------- |
| `ResponseError: unknown command 'HELLO'` at login       | redis-py 5 + **old** Redis (e.g. Laragon 3.2) | **Local only:** add `REDIS_PROTOCOL=2` to `.env`. **VPS:** use Redis 6+ (`apt install redis-server`); do not set `REDIS_PROTOCOL` |
| OTP fails first time, works after resend                | No shared cache / Redis not running | Start Redis; set `REDIS_URL`; restart Django                  |
| `Connection refused` on 6379                            | Redis not running                   | Start Memurai / `redis-server` / Docker container             |
| Docker `dockerDesktopLinuxEngine` error (Windows)       | Docker Desktop not running          | Start Docker Desktop or use Memurai                           |
| Laragon Redis not starting                              | Service disabled in Preferences     | Laragon → Preferences → Services & Ports → enable Redis       |
| `redis-cli` not found (Windows)                         | CLI not on PATH                     | Use full path under `C:\laragon\bin\redis\...` or Memurai CLI |
| `ModuleNotFoundError: redis`                            | Python package missing              | `pip install redis`                                           |
| OTP works in tests but not in production                | Tests use LocMem; prod needs Redis  | Configure `REDIS_URL` on server                               |
| Redis works but OTP still fails                         | SMTP issue or wrong code            | Run `python manage.py test_smtp`                              |
| After changing OTP minutes in admin, old TTL still used | Settings cache (5 min)              | Wait or restart app; save settings again                      |


### Check Redis from command line

**Windows (Memurai):**

```powershell
memurai-cli ping
```

**Linux:**

```bash
redis-cli ping
```

**Check Django cache:**

```python
from django.core.cache import cache
from django.conf import settings
print(settings.CACHES)
cache.set("x", 1, 10)
print(cache.get("x"))
```

---

## 8) Quick checklist

### Local (Windows)

- [ ] Redis running (Memurai / Laragon / WSL / Docker)
- [ ] `REDIS_URL` in `.env`
- [ ] `pip install redis`
- [ ] `python manage.py migrate`
- [ ] Restart Django
- [ ] `cache.set` / `cache.get` test passes
- [ ] OTP works on first attempt

### VPS (production)

- [ ] Redis installed (`apt install redis-server` or `dnf install redis`)
- [ ] `bind 127.0.0.1` in `redis.conf`
- [ ] (Optional) `requirepass` + password in `REDIS_URL`
- [ ] Port 6379 **not** open to public
- [ ] `REDIS_URL` in production `.env`
- [ ] `pip install -r requirements.txt`
- [ ] `python manage.py migrate`
- [ ] Restart Gunicorn
- [ ] OTP works on first attempt
- [ ] OTP validity configurable in admin → **Project security settings**

---

## 9) Related environment variables


| Variable                       | Purpose                                 |
| ------------------------------ | --------------------------------------- |
| `REDIS_URL`                    | Redis connection for OTP and cache      |
| `REDIS_PROTOCOL`               | Optional `2` for Redis older than 6 (e.g. Laragon 3.2). See [§2.1](#21-redis_protocol--when-to-set-it-local-vs-vps). Omit on VPS with Redis 6+. |
| `AI_EXCEL_SMTP_`*              | Sending OTP emails                      |
| `DJANGO_ALLOWED_HOSTS`         | Production domain                       |
| `IDLE_SESSION_TIMEOUT_SECONDS` | Session timeout (separate from OTP TTL) |


OTP TTL is **not** in `.env` — it is configured in Django admin under **Project security settings** (default: 10 minutes; resend cooldown matches).