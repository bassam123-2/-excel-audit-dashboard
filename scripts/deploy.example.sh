#!/usr/bin/env bash
# =============================================================================
# deploy.example.sh — Audit Dashboard deploy script template (copy to deploy.sh)
# =============================================================================
#
# One-time setup on VPS:
#   cp scripts/deploy.example.sh scripts/deploy.sh
#   chmod +x scripts/deploy.sh
#   # Set DEPLOY_* variables in .env (see .env.example)
#
# Usage:
#   ./scripts/deploy.sh
#   ./scripts/deploy.sh --skip-git
#   ./scripts/deploy.sh --skip-restart
#   ./scripts/deploy.sh --dry-run
#
# One-time bootstrap (not on every deploy):
#   python manage.py create_default_admin
#   python manage.py setup_groups
#   python manage.py setup_companies
# =============================================================================

# ── Exit immediately on any error ──────────────────────────────────────────────
set -euo pipefail

# ── Path to scripts/ (used to auto-detect project root) ───────────────────────
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── CLI flags ────────────────────────────────────────────────────────────────
SKIP_GIT=false
SKIP_RESTART=false
DRY_RUN=false

# =============================================================================
# Helper functions
# =============================================================================

# ── Print a timestamped message ──────────────────────────────────────────────
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ── Print an error and exit ──────────────────────────────────────────────────
die() {
    log "ERROR: $*" >&2
    exit 1
}

# ── Read a variable value from .env (supports trailing # comments) ───────────
env_val() {
    local key="$1" file="$2" raw
    [[ -f "${file}" ]] || return 0
    raw="$(grep -E "^[[:space:]]*${key}=" "${file}" 2>/dev/null | tail -1 | sed -E "s/^[[:space:]]*${key}=//")"
    raw="${raw%% #*}"
    raw="$(echo "${raw}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/^["'\''](.*)["'\'']$/\1/')"
    raw="${raw//$'\r'/}"
    printf '%s' "${raw}"
}

# ── Run a command, or print it only in dry-run mode ──────────────────────────
run() {
    log "▶ $*"
    if [[ "${DRY_RUN}" == "false" ]]; then
        eval "$@"
    fi
}

# ── Parse command-line arguments ───────────────────────────────────────────────
for arg in "$@"; do
    case "${arg}" in
        --skip-git)      SKIP_GIT=true ;;
        --skip-restart)  SKIP_RESTART=true ;;
        --dry-run)       DRY_RUN=true ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            die "Unknown argument: ${arg} (use --help)"
            ;;
    esac
done

# =============================================================================
# Load settings from .env
# =============================================================================

# ── Auto-detect project root when manage.py sits next to scripts/ ─────────────
if [[ -f "${_SCRIPT_DIR}/../manage.py" ]]; then
    PROJECT_ROOT="$(cd "${_SCRIPT_DIR}/.." && pwd)"
else
    PROJECT_ROOT=""
fi

# ── Temporary .env path used before the final PROJECT_ROOT is chosen ─────────
_ENV_CANDIDATE=""
if [[ -n "${PROJECT_ROOT}" && -f "${PROJECT_ROOT}/.env" ]]; then
    _ENV_CANDIDATE="${PROJECT_ROOT}/.env"
fi

# ── DEPLOY_PROJECT_ROOT from .env overrides auto-detection ───────────────────
if [[ -n "${_ENV_CANDIDATE}" ]]; then
    _ROOT_FROM_ENV="$(env_val DEPLOY_PROJECT_ROOT "${_ENV_CANDIDATE}")"
    if [[ -n "${_ROOT_FROM_ENV}" ]]; then
        PROJECT_ROOT="${_ROOT_FROM_ENV}"
    fi
fi

[[ -n "${PROJECT_ROOT}" ]] || die "Could not determine project root. Set DEPLOY_PROJECT_ROOT in .env"

ENV_FILE="${PROJECT_ROOT}/.env"
[[ -f "${ENV_FILE}" ]] || die ".env file not found: ${ENV_FILE}"

# ── Read deploy variables from .env ──────────────────────────────────────────
DEPLOY_VENV_DIR="$(env_val DEPLOY_VENV_DIR "${ENV_FILE}")"
DEPLOY_VENV_DIR="${DEPLOY_VENV_DIR:-venv}"

GIT_BRANCH="$(env_val DEPLOY_GIT_BRANCH "${ENV_FILE}")"
GIT_BRANCH="${GIT_BRANCH:-main}"

APP_SERVICE="$(env_val DEPLOY_APP_SERVICE "${ENV_FILE}")"
APP_SERVICE="${APP_SERVICE:-excel-dashboard}"

REDIS_SERVICE="$(env_val DEPLOY_REDIS_SERVICE "${ENV_FILE}")"
REDIS_SERVICE="${REDIS_SERVICE:-redis}"

PUBLIC_SITE_URL="$(env_val PUBLIC_SITE_URL "${ENV_FILE}")"
HEALTH_URL="$(env_val DEPLOY_HEALTH_URL "${ENV_FILE}")"
if [[ -z "${HEALTH_URL}" && -n "${PUBLIC_SITE_URL}" ]]; then
    HEALTH_URL="${PUBLIC_SITE_URL%/}/api/version"
fi

# ── Python paths inside the virtual environment ──────────────────────────────
PYTHON="${PROJECT_ROOT}/${DEPLOY_VENV_DIR}/bin/python"
PIP="${PROJECT_ROOT}/${DEPLOY_VENV_DIR}/bin/pip"

# =============================================================================
# Pre-deploy checks
# =============================================================================

log "Starting deploy — project: ${PROJECT_ROOT}"
log "Branch: ${GIT_BRANCH} | Service: ${APP_SERVICE} | Redis: ${REDIS_SERVICE}"

cd "${PROJECT_ROOT}"

[[ -x "${PYTHON}" ]] || die "Virtual environment not found: ${PROJECT_ROOT}/${DEPLOY_VENV_DIR}"
[[ -d "${PROJECT_ROOT}/config" ]] || die "config/ directory not found."

# ── Activate virtual environment (equivalent to: source venv/bin/activate) ─────
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/${DEPLOY_VENV_DIR}/bin/activate"

# =============================================================================
# 1) Pull latest code from Git
# =============================================================================

if [[ "${SKIP_GIT}" == "false" ]] && [[ -d "${PROJECT_ROOT}/.git" ]]; then
    # ── Fetch latest changes from remote ─────────────────────────────────────
    run "git -C '${PROJECT_ROOT}' fetch"

    # ── Sync server with remote branch (discards local changes) ──────────────
    run "git -C '${PROJECT_ROOT}' reset --hard 'origin/${GIT_BRANCH}'"
else
    log "Skipping git (--skip-git or not a git repository)"
fi

# =============================================================================
# 2) Apply database migrations
# =============================================================================

run "'${PYTHON}' manage.py migrate"

# =============================================================================
# 3) Compile Arabic UI translations
# =============================================================================

# ── Convert locale/ar/*.po to .mo — required after Arabic UI string changes ──
run "'${PYTHON}' manage.py compilemessages -l ar"

# =============================================================================
# 4) Collect static files (Manifest hashes — cache bust for all users)
# =============================================================================

# Produces hashed names (e.g. app.a1b2c3.js) so browsers load new JS/CSS after
# deploy without requiring a hard reload. Avoid --clear so open tabs with older
# HTML can still load previous hashed assets until they refresh the page.
run "'${PYTHON}' manage.py collectstatic --noinput"

# =============================================================================
# 5) Restart services
# =============================================================================

if [[ "${SKIP_RESTART}" == "false" ]]; then
    run "systemctl restart '${REDIS_SERVICE}'"
    run "systemctl daemon-reload"
    run "systemctl restart '${APP_SERVICE}'"
    run "systemctl status '${APP_SERVICE}' --no-pager -l"
else
    log "Skipping service restart (--skip-restart)"
fi

# =============================================================================
# 6) Post-deploy verification
# =============================================================================

if [[ "${DRY_RUN}" == "false" ]] && [[ "${SKIP_RESTART}" == "false" ]] && [[ -n "${HEALTH_URL}" ]]; then
    sleep 2
    if command -v curl &>/dev/null; then
        log "Health check: ${HEALTH_URL}"
        if curl -fsS --max-time 15 "${HEALTH_URL}"; then
            echo ""
            log "Deploy succeeded — application is responding"
        else
            log "WARNING: Health check failed — see: journalctl -u ${APP_SERVICE} -n 50"
        fi
    fi
fi

log "Deploy completed successfully."
