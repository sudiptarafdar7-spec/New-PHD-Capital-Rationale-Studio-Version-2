#!/usr/bin/env bash
###############################################################################
#  PHD Capital Rationale Studio  —  FAST UPDATE SCRIPT
#  -------------------------------------------------------------------------
#  Use this AFTER the first install (deploy.sh) to deploy code changes.
#  Skips all system-package work — just pulls latest code, rebuilds frontend,
#  applies any new DB schema, restarts the service. Takes ~30 seconds.
#
#  ONE-LINE on the VPS (as root):
#
#      curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/update.sh | sudo bash
#
#  Or, if you cloned locally:    sudo bash /var/www/new-rationale-studio/update.sh
###############################################################################

set -Eeuo pipefail

APP_NAME="phd-new"
APP_DIR="/var/www/new-rationale-studio"
APP_USER="phdnew"
ENV_FILE="/etc/${APP_NAME}.env"

GRN='\033[0;32m'; BLU='\033[0;34m'; RED='\033[0;31m'; YLW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GRN}✓${NC} $*"; }
log()  { echo -e "${BLU}▸${NC} $*"; }
warn() { echo -e "${YLW}!${NC} $*"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Run as root:  sudo bash update.sh"
[[ -d "$APP_DIR/.git" ]] || die "$APP_DIR is not installed yet — run deploy.sh first."
[[ -f "$ENV_FILE"     ]] || die "$ENV_FILE missing — run deploy.sh first."

START_COMMIT=$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)
log "current commit: $START_COMMIT"

# ── 1. Pull latest code ──────────────────────────────────────────────────────
log "pulling latest code from origin/main ..."
sudo -u "$APP_USER" git -C "$APP_DIR" fetch --all --prune
sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard origin/main
NEW_COMMIT=$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)
if [[ "$START_COMMIT" == "$NEW_COMMIT" ]]; then
    warn "already up-to-date at $NEW_COMMIT"
else
    ok "updated  $START_COMMIT → $NEW_COMMIT"
fi

# ── 2. Detect what changed (skip work that isn't needed) ────────────────────
CHANGED=$(sudo -u "$APP_USER" git -C "$APP_DIR" diff --name-only "$START_COMMIT" "$NEW_COMMIT" 2>/dev/null || true)
need_pip=false; need_npm=false; need_build=false; need_db=false
if [[ -z "$CHANGED" ]]; then
    # First update or nothing changed — do everything to be safe.
    need_pip=true; need_npm=true; need_build=true; need_db=true
else
    grep -q '^requirements\.txt$'                       <<<"$CHANGED" && need_pip=true || true
    grep -q '^package\(-lock\)\?\.json$'                <<<"$CHANGED" && need_npm=true || true
    grep -qE '^(src/|index\.html|vite\.config\.ts|tsconfig.*\.json|package\.json)' <<<"$CHANGED" && need_build=true || true
    grep -qE '^backend/(utils/database\.py|models/)'    <<<"$CHANGED" && need_db=true  || true
fi

# ── 3. Python deps ───────────────────────────────────────────────────────────
if $need_pip; then
    log "installing/updating Python deps ..."
    sudo -u "$APP_USER" bash -lc "cd '$APP_DIR' && source venv/bin/activate && pip install -r requirements.txt"
    ok "pip done"
fi

# ── 4. Node deps + build ─────────────────────────────────────────────────────
if $need_npm; then
    log "installing Node deps ..."
    sudo -u "$APP_USER" bash -lc "cd '$APP_DIR' && npm ci --no-audit --no-fund"
    ok "npm done"
    need_build=true
fi
if $need_build; then
    log "building frontend ..."
    sudo -u "$APP_USER" bash -lc "cd '$APP_DIR' && npm run build"
    ok "frontend built"
fi

# ── 5. DB schema (idempotent) ───────────────────────────────────────────────
if $need_db; then
    log "applying DB schema (idempotent) ..."
    sudo -u "$APP_USER" bash -lc "
        cd '$APP_DIR'
        set -a; source '$ENV_FILE'; set +a
        source venv/bin/activate
        python -c 'from backend.utils.database import init_database; init_database()'
    "
    ok "DB schema synced"
fi

# ── 6. Restart service ───────────────────────────────────────────────────────
log "restarting ${APP_NAME} ..."
systemctl restart "${APP_NAME}.service"
sleep 2
if systemctl is-active --quiet "${APP_NAME}.service"; then
    ok "${APP_NAME} restarted successfully"
else
    die "${APP_NAME} failed to start — check:  journalctl -u ${APP_NAME} -n 50"
fi

echo
echo -e "${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GRN}  UPDATE COMPLETE${NC}"
echo -e "${GRN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "  Commit       :  $NEW_COMMIT"
echo "  URL          :  https://new.researchrationale.in"
echo "  Live logs    :  journalctl -u ${APP_NAME} -f"
echo
