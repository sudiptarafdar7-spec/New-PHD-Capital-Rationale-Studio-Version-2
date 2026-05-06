#!/usr/bin/env bash
###############################################################################
#  PHD Capital Rationale Studio  —  ONE-LINE PRODUCTION INSTALLER
#  -------------------------------------------------------------------------
#  Subdomain : new.researchrationale.in
#  Directory : /var/www/new-rationale-studio   (separate from existing app)
#  Service   : phd-new.service                  (separate from existing app)
#  DB        : phd_new_db / phd_new_user        (separate from existing app)
#  -------------------------------------------------------------------------
#  USAGE (run on the VPS as root):
#
#      curl -fsSL https://raw.githubusercontent.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2/main/deploy.sh | sudo bash
#
#  The script auto-detects FRESH INSTALL vs UPGRADE:
#    - FRESH INSTALL: installs system packages, creates DB + admin user,
#                     configures nginx + SSL, starts service.
#    - UPGRADE:       pulls latest code, rebuilds frontend, applies any new
#                     DB migrations, restarts service. ALL DATA PRESERVED.
#
#  Re-run the same one-liner any time to deploy updates.
###############################################################################

set -Eeuo pipefail

# ───────────────────────────  CONFIG  ────────────────────────────────────────
APP_NAME="phd-new"
APP_DIR="/var/www/new-rationale-studio"
APP_USER="phdnew"
DOMAIN="new.researchrationale.in"
GITHUB_REPO="https://github.com/sudiptarafdar7-spec/New-PHD-Capital-Rationale-Studio-Version-2.git"
DB_NAME="phd_new_db"
DB_USER="phd_new_user"
ENV_FILE="/etc/${APP_NAME}.env"
SERVICE_FILE="/etc/systemd/system/${APP_NAME}.service"
NGINX_FILE="/etc/nginx/sites-available/${APP_NAME}.conf"
PYTHON_BIN="python3.11"
GUNICORN_PORT="8100"   # different from the existing app's 8000

# Default admin (only created on FRESH INSTALL)
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@phdcapital.in}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin@123}"

# ───────────────────────────  HELPERS  ───────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BLU='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLU}▸${NC} $*"; }
ok()   { echo -e "${GRN}✓${NC} $*"; }
warn() { echo -e "${YLW}!${NC} $*"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }
header() { echo; echo -e "${BLU}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLU}  $*${NC}"; echo -e "${BLU}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

[[ "$EUID" -eq 0 ]] || die "Run as root:  sudo bash deploy.sh"

# ───────────────────  DETECT FRESH-INSTALL vs UPGRADE  ───────────────────────
IS_UPGRADE=false
if [[ -d "$APP_DIR/.git" ]] && [[ -f "$ENV_FILE" ]]; then
    IS_UPGRADE=true
fi

header "PHD Capital Rationale Studio — ${DOMAIN}"
echo "  Mode      : $([[ "$IS_UPGRADE" == true ]] && echo 'UPGRADE (data preserved)' || echo 'FRESH INSTALL')"
echo "  App dir   : $APP_DIR"
echo "  DB        : $DB_NAME (user: $DB_USER)"
echo "  Service   : ${APP_NAME}.service  (port $GUNICORN_PORT)"
echo "  Repo      : $GITHUB_REPO"

# ═══════════════════════  FRESH-INSTALL ONE-TIME WORK  ══════════════════════
if [[ "$IS_UPGRADE" == false ]]; then

    header "1/8  Install system packages"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y --no-install-recommends \
        software-properties-common curl ca-certificates gnupg lsb-release \
        build-essential pkg-config git nginx ufw \
        ffmpeg \
        postgresql postgresql-contrib libpq-dev \
        certbot python3-certbot-nginx
    # Python 3.11 (deadsnakes) — Ubuntu 24.04 ships 3.12 by default but we want 3.11.
    if ! command -v python3.11 >/dev/null; then
        add-apt-repository -y ppa:deadsnakes/ppa
        apt-get update -y
        apt-get install -y python3.11 python3.11-venv python3.11-dev
    fi
    # Node.js 20
    if ! command -v node >/dev/null || [[ "$(node -v | sed 's/v//;s/\..*//')" -lt 20 ]]; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs
    fi
    ok "system packages ready"

    header "2/8  Create system user"
    if ! id "$APP_USER" >/dev/null 2>&1; then
        useradd --system --create-home --shell /bin/bash "$APP_USER"
        ok "user '$APP_USER' created"
    else
        ok "user '$APP_USER' already exists"
    fi

    header "3/8  Provision PostgreSQL database"
    DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    sudo -u postgres psql <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER ROLE $DB_USER WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;
SQL
    sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
        || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
    sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;"
    ok "database ready"

    header "4/8  Write environment file ($ENV_FILE)"
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    cat > "$ENV_FILE" <<EOF
# Generated by deploy.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
FLASK_ENV=production
SECRET_KEY=$SECRET_KEY
JWT_SECRET_KEY=$JWT_SECRET
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
ALLOWED_ORIGINS=https://$DOMAIN

# Fill these in after first deploy (Admin → API Keys page can also store them):
OPENAI_API_KEY=
GEMINI_API_KEY=
ASSEMBLYAI_API_KEY=
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
EOF
    chmod 600 "$ENV_FILE"
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    ok "env file written (chmod 600)"
fi

# ═══════════════════════  CODE: CLONE OR PULL  ══════════════════════════════
header "5/8  Sync code from GitHub"
if [[ "$IS_UPGRADE" == false ]]; then
    mkdir -p "$APP_DIR"
    chown "$APP_USER:$APP_USER" "$APP_DIR"
    sudo -u "$APP_USER" git clone --depth 1 "$GITHUB_REPO" "$APP_DIR"
else
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --all --prune
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard origin/main
fi
# Persistent runtime dirs (outside git, kept on upgrade)
sudo -u "$APP_USER" mkdir -p \
    "$APP_DIR/backend/job_files" \
    "$APP_DIR/backend/uploaded_files" \
    "$APP_DIR/backend/channel_logos" \
    "$APP_DIR/backend/generated_charts" \
    "$APP_DIR/backend/models/vosk"
ok "code synced"

# ═══════════════════════  PYTHON DEPENDENCIES  ══════════════════════════════
header "6/8  Install Python + Node deps & build frontend"
sudo -u "$APP_USER" bash -lc "
    set -e
    cd '$APP_DIR'
    if [[ ! -d venv ]]; then $PYTHON_BIN -m venv venv; fi
    source venv/bin/activate
    pip install --upgrade pip wheel
    pip install -r requirements.txt
    npm ci --no-audit --no-fund
    npm run build
"
ok "deps installed, frontend built"

# ═══════════════════════  DATABASE INIT + ADMIN  ════════════════════════════
header "7/8  Init DB schema & ensure admin user"
sudo -u "$APP_USER" bash -lc "
    set -e
    cd '$APP_DIR'
    set -a; source '$ENV_FILE'; set +a
    source venv/bin/activate
    # Tables — idempotent, safe on every run.
    python -c 'from backend.utils.database import init_database; init_database()'
"
# Only seed the admin on FRESH INSTALL (don't overwrite a real admin password on upgrades)
if [[ "$IS_UPGRADE" == false ]]; then
    sudo -u "$APP_USER" bash -lc "
        set -e
        cd '$APP_DIR'
        set -a; source '$ENV_FILE'; set +a
        source venv/bin/activate
        python - <<PY
from backend.models.user import User
try:
    u = User.create(
        first_name='Admin', last_name='User',
        email='${ADMIN_EMAIL}', mobile='',
        role='admin', password='${ADMIN_PASSWORD}',
        avatar_path='https://api.dicebear.com/7.x/avataaars/svg?seed=Admin',
    )
    print('✓ admin created:', u['email'])
except Exception as e:
    print('ℹ admin exists or:', e)
PY
    "
fi
ok "DB ready"

# ═══════════════════════  SYSTEMD + NGINX + SSL  ════════════════════════════
header "8/8  systemd, nginx, SSL"

# systemd unit
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=PHD Capital Rationale Studio (${DOMAIN})
After=network.target postgresql.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/venv/bin/gunicorn \\
    --workers 3 --threads 4 --timeout 600 \\
    --bind 127.0.0.1:$GUNICORN_PORT \\
    'backend.app:create_app()'
Restart=always
RestartSec=5
StandardOutput=append:/var/log/${APP_NAME}.log
StandardError=append:/var/log/${APP_NAME}.err.log

[Install]
WantedBy=multi-user.target
EOF
touch /var/log/${APP_NAME}.log /var/log/${APP_NAME}.err.log
chown "$APP_USER:$APP_USER" /var/log/${APP_NAME}.log /var/log/${APP_NAME}.err.log
systemctl daemon-reload
systemctl enable "${APP_NAME}.service" >/dev/null
systemctl restart "${APP_NAME}.service"
ok "systemd unit installed & started"

# nginx vhost (HTTP first; certbot will add the HTTPS block)
if [[ ! -f "$NGINX_FILE" ]]; then
cat > "$NGINX_FILE" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    client_max_body_size 600M;

    # Frontend (built static files)
    root $APP_DIR/build;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:$GUNICORN_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
}
EOF
    ln -sf "$NGINX_FILE" /etc/nginx/sites-enabled/${APP_NAME}.conf
    [[ -L /etc/nginx/sites-enabled/default ]] && rm -f /etc/nginx/sites-enabled/default || true
fi
nginx -t
systemctl reload nginx
ok "nginx vhost ready ($DOMAIN → :$GUNICORN_PORT)"

# Firewall (no-op if already configured)
if command -v ufw >/dev/null; then
    ufw allow 'Nginx Full' >/dev/null 2>&1 || true
    ufw allow OpenSSH       >/dev/null 2>&1 || true
fi

# SSL via Let's Encrypt (idempotent — skip if cert already exists)
if [[ ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
    log "obtaining SSL cert for $DOMAIN ..."
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
        -m "admin@$(echo "$DOMAIN" | cut -d. -f2-)" --redirect || \
        warn "certbot failed — DNS may not be pointing to this server yet. Re-run after DNS propagates:  certbot --nginx -d $DOMAIN"
else
    ok "SSL cert already present — skipped certbot"
fi

# ════════════════════════════  DONE  ════════════════════════════════════════
header "DEPLOYMENT COMPLETE"
echo "  URL          :  https://$DOMAIN"
if [[ "$IS_UPGRADE" == false ]]; then
echo "  Admin login  :  $ADMIN_EMAIL  /  $ADMIN_PASSWORD"
echo "                  (CHANGE THIS PASSWORD after first login!)"
fi
echo
echo "  Logs         :  journalctl -u ${APP_NAME} -f"
echo "  Restart      :  systemctl restart ${APP_NAME}"
echo "  Env file     :  $ENV_FILE"
echo "  Update app   :  re-run the same one-line installer"
echo
