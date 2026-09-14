#!/usr/bin/env bash
# SIMA — endurecimiento del VPS compartido (idempotente). No toca Luna ni otras apps.
#
#   sudo bash /srv/sima/app/deploy/harden_vps.sh
#
# 1. Topes de memoria para sima-web y sima-worker (drop-ins de systemd) y prioridad
#    para que, si falta RAM, el kernel cierre SIMA antes que las demas apps.
# 2. Nginx sin numero de version en las cabeceras (server_tokens off, global).
# 3. Registro por invitacion: SIMA_REGISTRATION=invite con un codigo aleatorio si no hay uno.
# 4. Reinicia SIMA y recarga Nginx solo si la configuracion es valida.
set -euo pipefail

APP_USER="${APP_USER:-sima}"
SIMA_HOME="${SIMA_HOME:-/srv/sima}"
APP_DIR="$SIMA_HOME/app"
ENV_FILE="$APP_DIR/.env"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[AVISO] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Ejecuta con sudo."
[[ -f "$ENV_FILE" ]] || die "No existe $ENV_FILE"

# Cambia o agrega KEY=VALUE en .env conservando dueno y permisos del archivo.
set_env() {
    python3 - "$ENV_FILE" "$1" "$2" <<'PY'
import re, sys
path, key, value = sys.argv[1:4]
with open(path, "r+", encoding="utf-8") as fh:
    text = fh.read()
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    text = pattern.sub(lambda _m: line, text) if pattern.search(text) else text.rstrip("\n") + "\n" + line + "\n"
    fh.seek(0); fh.write(text); fh.truncate()
PY
}
get_env() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

log "Topes de memoria (systemd drop-ins)"
install -d /etc/systemd/system/sima-web.service.d /etc/systemd/system/sima-worker.service.d \n    /etc/systemd/system/sima-worker-study.service.d
cat > /etc/systemd/system/sima-web.service.d/10-limites.conf <<'CONF'
[Service]
MemoryHigh=450M
MemoryMax=600M
OOMScoreAdjust=300
CONF
cat > /etc/systemd/system/sima-worker.service.d/10-limites.conf <<'CONF'
[Service]
MemoryHigh=550M
MemoryMax=700M
OOMScoreAdjust=500
CONF
cat > /etc/systemd/system/sima-worker-study.service.d/10-limites.conf <<'CONF'
[Service]
MemoryHigh=300M
MemoryMax=450M
OOMScoreAdjust=500
CONF
systemctl daemon-reload

log "Nginx sin version en las cabeceras"
if grep -RqsE '^\s*server_tokens\s+off' /etc/nginx/nginx.conf /etc/nginx/conf.d/; then
    echo "server_tokens off ya estaba activo."
else
    echo "server_tokens off;" > /etc/nginx/conf.d/10-server-tokens.conf
fi
nginx -t || die "La configuracion de Nginx no es valida; no se recargo."
systemctl reload nginx

log "Registro por invitacion"
if [[ "$(get_env SIMA_REGISTRATION)" != "invite" || -z "$(get_env SIMA_INVITE_CODE)" || "$(get_env SIMA_INVITE_CODE)" == CAMBIAR* ]]; then
    set_env SIMA_REGISTRATION invite
    if [[ -z "$(get_env SIMA_INVITE_CODE)" || "$(get_env SIMA_INVITE_CODE)" == CAMBIAR* ]]; then
        set_env SIMA_INVITE_CODE "sima-$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
    fi
fi

log "Reinicio de SIMA"
systemctl restart sima-web sima-worker
systemctl restart sima-worker-study 2>/dev/null || true
for i in $(seq 1 20); do
    curl -fsS -o /dev/null -H "Host: 127.0.0.1" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/salud/ && break
    sleep 1
done
systemctl is-active --quiet sima-web || die "sima-web no arranco: journalctl -u sima-web -n 80"
systemctl is-active --quiet sima-worker || warn "sima-worker no esta activo: journalctl -u sima-worker -n 80"

log "Listo"
systemctl show sima-web sima-worker -p Id -p MemoryMax -p OOMScoreAdjust
echo
echo "Codigo de invitacion para crear cuentas: $(get_env SIMA_INVITE_CODE)"
echo "Compartelo solo con quien deba registrarse. Para cambiarlo, edita SIMA_INVITE_CODE en $ENV_FILE y reinicia sima-web."
