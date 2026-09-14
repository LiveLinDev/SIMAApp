#!/usr/bin/env bash
# =============================================================================
# SIMA — preparacion automatica de un VPS Ubuntu 24.04 / 22.04 (pasos 2 a 8 del
# plan deploy/PLAN_DESPLIEGUE_VPS.md). Se puede ejecutar varias veces: lo que ya
# existe se respeta (no regenera la clave de Django ni la contrasena de la BD).
#
# Uso (como usuario con sudo, en el VPS):
#   curl -fsSLO https://raw.githubusercontent.com/LiveLinDev/SIMAApp/main/deploy/bootstrap_vps.sh
#   sudo DOMAIN=sima.midominio.pe GROQ_API_KEY=gsk_xxx bash bootstrap_vps.sh
#
# Parametros (variables de entorno o primer argumento para DOMAIN):
#   DOMAIN          (obligatorio) dominio publico, o la IP del VPS para modo demo.
#   DB_PASSWORD     contrasena del rol PostgreSQL "sima". Si falta: se reutiliza la
#                   del .env existente o se genera con openssl.
#   GROQ_API_KEY    clave de Groq para rellenar CLOUD_API_KEY (opcional; si falta,
#                   edita .env a mano despues).
#   REPO_URL        por defecto https://github.com/LiveLinDev/SIMAApp.git
#   BRANCH          por defecto main
#   INSTALL_WHISPER 0 (defecto) no instala Whisper: la transcripcion la hace la PC por tunel
#                   (TRANSCRIPTION_BACKEND=remote). 1 = instala torch CPU + openai-whisper en el VPS.
#   WHISPER_PRELOAD 1 (defecto) descarga el modelo de WHISPER_MODEL por adelantado.
#   SWAP_SIZE       tamano del swapfile si no hay swap (defecto 4G; "0" = no crear).
#
# NO hace: endurecimiento SSH/UFW (paso 1), createsuperuser ni certbot (paso 9).
# =============================================================================
set -euo pipefail

DOMAIN="${DOMAIN:-${1:-}}"
DB_PASSWORD="${DB_PASSWORD:-}"
GROQ_API_KEY="${GROQ_API_KEY:-}"
REPO_URL="${REPO_URL:-https://github.com/LiveLinDev/SIMAApp.git}"
BRANCH="${BRANCH:-main}"
INSTALL_WHISPER="${INSTALL_WHISPER:-0}"
WHISPER_PRELOAD="${WHISPER_PRELOAD:-1}"
SWAP_SIZE="${SWAP_SIZE:-4G}"

APP_USER=sima
SIMA_HOME=/srv/sima
APP_DIR="$SIMA_HOME/app"
VENV="$SIMA_HOME/venv"
ENV_FILE="$APP_DIR/.env"
DB_NAME=sima
DB_USER=sima

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[AVISO] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

as_app() { sudo -u "$APP_USER" -H "$@"; }
manage() { as_app bash -c "cd '$APP_DIR' && '$VENV/bin/python' manage.py $*"; }

# ── Validaciones ─────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Ejecuta con sudo: sudo DOMAIN=tu.dominio bash $0"
[[ -n "$DOMAIN" ]] || die "Falta DOMAIN (ej. sudo DOMAIN=sima.duckdns.org bash $0)"
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "DOMAIN invalido: '$DOMAIN' (sin http:// ni barras)"
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    [[ "${ID:-}" == "ubuntu" ]] || warn "Probado en Ubuntu 22.04/24.04; detectado ${PRETTY_NAME:-desconocido}."
fi

IS_IP=0
if [[ "$DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then IS_IP=1; fi

# ── Paso 2: paquetes del sistema ─────────────────────────────────────────────
log "Paso 2: paquetes del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev build-essential libpq-dev \
    postgresql postgresql-contrib nginx ffmpeg git curl ca-certificates openssl \
    certbot python3-certbot-nginx

# Swap: Whisper + torch necesitan colchon en VPS de 2-4 GB
if [[ "$SWAP_SIZE" != "0" ]] && ! swapon --show --noheadings | grep -q .; then
    log "Creando swapfile de $SWAP_SIZE en /swapfile"
    if [[ ! -f /swapfile ]]; then
        fallocate -l "$SWAP_SIZE" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
        chmod 600 /swapfile
        mkswap /swapfile
    fi
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -q vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/99-sima-swap.conf
else
    log "Swap: ya existe (o SWAP_SIZE=0); no se toca"
fi

# ── Usuario de la aplicacion ─────────────────────────────────────────────────
log "Usuario de sistema '$APP_USER' con home $SIMA_HOME"
if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$SIMA_HOME" --shell /bin/bash "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 755 "$SIMA_HOME"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$SIMA_HOME/backups"

# ── Paso 4: codigo ───────────────────────────────────────────────────────────
log "Paso 4: codigo en $APP_DIR (rama $BRANCH)"
if [[ -d "$APP_DIR/.git" ]]; then
    as_app git -C "$APP_DIR" fetch --prune origin
    as_app git -C "$APP_DIR" checkout "$BRANCH"
    as_app git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
    as_app git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
[[ -f "$APP_DIR/deploy/env.production.example" ]] \
    || die "La rama $BRANCH no trae deploy/. ¿Hiciste git push de tus commits locales?"

# ── Paso 3: PostgreSQL ───────────────────────────────────────────────────────
log "Paso 3: PostgreSQL (rol y base '$DB_NAME')"
systemctl enable --now postgresql
if [[ -z "$DB_PASSWORD" && -f "$ENV_FILE" ]]; then
    DB_PASSWORD="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
    if [[ "$DB_PASSWORD" == CAMBIAR_* ]]; then DB_PASSWORD=""; fi
fi
if [[ -z "$DB_PASSWORD" ]]; then
    DB_PASSWORD="$(openssl rand -hex 24)"
    log "Contrasena de BD generada (queda solo en $ENV_FILE)"
fi
[[ "$DB_PASSWORD" =~ ^[A-Za-z0-9_-]+$ ]] || die "DB_PASSWORD solo puede tener letras, numeros, _ y -"

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    sudo -u postgres psql -q -c "ALTER ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASSWORD';"
else
    sudo -u postgres psql -q -c "CREATE ROLE $DB_USER WITH LOGIN PASSWORD '$DB_PASSWORD';"
fi
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    sudo -u postgres createdb -O "$DB_USER" -E UTF8 -T template0 "$DB_NAME"
fi

# ── Paso 4 (cont.): entorno virtual y dependencias ───────────────────────────
log "Paso 4: entorno virtual $VENV y dependencias"
[[ -x "$VENV/bin/python" ]] || as_app python3 -m venv "$VENV"
as_app "$VENV/bin/pip" install --upgrade pip wheel
if [[ "$INSTALL_WHISPER" == "1" ]]; then
    # torch CPU primero: evita descargar varios GB de librerias CUDA
    if ! as_app "$VENV/bin/python" -c "import torch" >/dev/null 2>&1; then
        as_app "$VENV/bin/pip" install torch --index-url https://download.pytorch.org/whl/cpu
    fi
    as_app "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
else
    log "INSTALL_WHISPER=0: se omite openai-whisper (el audio lo transcribe la PC por el tunel SSH)"
    grep -viE '^openai-whisper' "$APP_DIR/requirements.txt" > "$SIMA_HOME/requirements-sin-whisper.txt"
    chown "$APP_USER:$APP_USER" "$SIMA_HOME/requirements-sin-whisper.txt"
    as_app "$VENV/bin/pip" install -r "$SIMA_HOME/requirements-sin-whisper.txt"
fi
as_app "$VENV/bin/python" -c "import gunicorn" || as_app "$VENV/bin/pip" install "gunicorn>=23.0"

# ── Paso 5: .env de produccion ───────────────────────────────────────────────
log "Paso 5: $ENV_FILE"
if [[ ! -f "$ENV_FILE" ]]; then
    install -o "$APP_USER" -g "$APP_USER" -m 600 "$APP_DIR/deploy/env.production.example" "$ENV_FILE"
    SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
    sed -i \
        -e "s|CAMBIAR_SECRET_KEY|$SECRET|" \
        -e "s|CAMBIAR_DB_PASSWORD|$DB_PASSWORD|g" \
        -e "s|DOMINIO|$DOMAIN|g" \
        "$ENV_FILE"
    if [[ $IS_IP -eq 1 ]]; then
        sed -i -e "s|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=http://$DOMAIN|" \
               -e "s|^SIMA_SITE_URL=.*|SIMA_SITE_URL=http://$DOMAIN|" "$ENV_FILE"
    fi
    if [[ "$INSTALL_WHISPER" == "1" ]]; then
        sed -i "s|^TRANSCRIPTION_BACKEND=.*|TRANSCRIPTION_BACKEND=local|" "$ENV_FILE"
    fi
    if [[ -n "${WHISPER_REMOTE_TOKEN:-}" ]]; then
        sed -i "s|^WHISPER_REMOTE_TOKEN=.*|WHISPER_REMOTE_TOKEN=$WHISPER_REMOTE_TOKEN|" "$ENV_FILE"
    fi
else
    log ".env ya existe: no se sobrescribe (solo se sincroniza POSTGRES_PASSWORD)"
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DB_PASSWORD|" "$ENV_FILE"
fi
if [[ -n "$GROQ_API_KEY" ]]; then
    sed -i "s|^CLOUD_API_KEY=.*|CLOUD_API_KEY=$GROQ_API_KEY|" "$ENV_FILE"
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"
if grep -q '^CLOUD_API_KEY=CAMBIAR_' "$ENV_FILE"; then
    warn "CLOUD_API_KEY sin definir: edita $ENV_FILE (clave de Groq)"
fi

# ── Paso 6: migraciones y estaticos ──────────────────────────────────────────
log "Paso 6: migrate, collectstatic y check --deploy"
as_app install -d -m 750 "$APP_DIR/media" "$APP_DIR/logs"
manage migrate --noinput
manage collectstatic --noinput
manage check --deploy || warn "check --deploy dio avisos (normales antes de activar HTTPS; ver plan, paso 9)"

if [[ "$INSTALL_WHISPER" == "1" && "$WHISPER_PRELOAD" == "1" ]]; then
    WMODEL="$(grep -E '^WHISPER_MODEL=' "$ENV_FILE" | cut -d= -f2- || echo base)"
    log "Descargando modelo Whisper '${WMODEL:-base}' a $SIMA_HOME/.cache/whisper"
    as_app "$VENV/bin/python" -c "import whisper; whisper.load_model('${WMODEL:-base}')" \
        || warn "No se pudo precargar Whisper (se descargara en la primera clase con audio)"
fi

# ── Paso 7: systemd ──────────────────────────────────────────────────────────
log "Paso 7: servicios systemd"
install -m 644 "$APP_DIR"/deploy/systemd/sima-web.service       /etc/systemd/system/
install -m 644 "$APP_DIR"/deploy/systemd/sima-worker.service    /etc/systemd/system/
install -m 644 "$APP_DIR"/deploy/systemd/sima-reminders.service /etc/systemd/system/
install -m 644 "$APP_DIR"/deploy/systemd/sima-reminders.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable sima-web sima-worker sima-reminders.timer
systemctl restart sima-web sima-worker
systemctl start sima-reminders.timer

# ── Paso 8: Nginx ────────────────────────────────────────────────────────────
log "Paso 8: Nginx"
SITE=/etc/nginx/sites-available/sima
if [[ -f "$SITE" ]] && grep -q 'managed by Certbot' "$SITE"; then
    warn "$SITE ya tiene cambios de certbot: no se sobrescribe"
else
    sed "s/DOMINIO/$DOMAIN/g" "$APP_DIR/deploy/nginx/sima.conf" > "$SITE"
fi
ln -sf "$SITE" /etc/nginx/sites-enabled/sima
rm -f /etc/nginx/sites-enabled/default
# Nginx (www-data) debe poder atravesar /srv/sima y leer staticfiles
chmod 755 "$SIMA_HOME" "$APP_DIR"
nginx -t
systemctl enable nginx
systemctl reload nginx || systemctl restart nginx

# ── Verificacion ─────────────────────────────────────────────────────────────
log "Verificacion: /salud/"
ok=0
for _ in $(seq 1 20); do
    if curl -fsS -H "Host: 127.0.0.1" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/salud/; then
        ok=1; echo; break
    fi
    sleep 2
done
[[ $ok -eq 1 ]] || warn "gunicorn no respondio en /salud/. Revisa: journalctl -u sima-web -n 80"
systemctl --no-pager --lines=0 status sima-web sima-worker || true

cat <<EOF

=============================================================================
 Listo. Siguientes pasos manuales:
  1) Crear administrador:
       sudo -u $APP_USER -H bash -c 'cd $APP_DIR && $VENV/bin/python manage.py createsuperuser'
  2) Probar la IA:
       sudo -u $APP_USER -H bash -c 'cd $APP_DIR && $VENV/bin/python manage.py check_ai --ping'
  3) Abrir http://$DOMAIN/
EOF
if [[ $IS_IP -eq 0 ]]; then
cat <<EOF
  4) HTTPS:  sudo certbot --nginx -d $DOMAIN
     y luego en $ENV_FILE: SECURE_SSL_REDIRECT=1, SESSION_COOKIE_SECURE=1,
     CSRF_COOKIE_SECURE=1, SECURE_HSTS_SECONDS=3600  ->  sudo systemctl restart sima-web
EOF
fi
echo "============================================================================="
