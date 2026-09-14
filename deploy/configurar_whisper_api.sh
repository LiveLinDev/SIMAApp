#!/usr/bin/env bash
# SIMA — usar Whisper API privada del equipo para transcribir en el VPS (sin tunel SSH a una PC).
#
#   sudo bash /srv/sima/app/deploy/configurar_whisper_api.sh
#
# Pide la WHISPER_API_KEY sin mostrarla en pantalla ni guardarla en el historial, la escribe en el .env privado
# (dueno sima, permisos 600), activa TRANSCRIPTION_BACKEND=api, reinicia el worker y verifica la salud del
# servicio sin enviar la clave. Para volver al tunel: TRANSCRIPTION_BACKEND=remote en el .env y reiniciar.
set -euo pipefail

SIMA_HOME="${SIMA_HOME:-/srv/sima}"
APP_DIR="$SIMA_HOME/app"
ENV_FILE="$APP_DIR/.env"
BASE_URL="https://whisper-api.aquelarredemujeres.com"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Ejecuta con sudo."
[[ -f "$ENV_FILE" ]] || die "No existe $ENV_FILE"

log "Salud del servicio (sin credencial)"
curl -fsS --proto '=https' --max-time 15 "$BASE_URL/health/live" >/dev/null || die "Whisper API no responde en $BASE_URL"
curl -fsS --proto '=https' --max-time 15 "$BASE_URL/health/ready" >/dev/null && echo "live y ready: 200" \
    || echo "live: 200; ready aun no (el modelo puede estar cargando); se configura igual"

log "Credencial"
read -rsp "Pega la WHISPER_API_KEY y presiona Enter (no se mostrara): " KEY
echo
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
[[ ${#KEY} -ge 32 ]] || die "La clave parece incompleta; no se guardo nada."

[[ "$KEY" =~ ^[A-Za-z0-9._~+/=-]+$ ]] || die "La clave tiene caracteres inesperados; no se guardo nada."
# La clave viaja por el entorno del proceso (no por argumentos visibles en `ps`) y el heredoc va entre comillas.
WHISPER_KEY_INPUT="$KEY" python3 - "$ENV_FILE" "$BASE_URL" <<'PY'
import os, re, sys
path, base = sys.argv[1:3]
values = {
    "TRANSCRIPTION_BACKEND": "api",
    "WHISPER_API_BASE_URL": base,
    "WHISPER_API_KEY": os.environ["WHISPER_KEY_INPUT"],
    "WHISPER_API_POLL_INTERVAL_SECONDS": "4",
    "WHISPER_API_REQUEST_TIMEOUT_SECONDS": "620",
    "WHISPER_API_MAX_WAIT_SECONDS": "9000",
}
with open(path, "r+", encoding="utf-8") as fh:
    text = fh.read()
    for key, value in values.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
        text = pattern.sub(lambda _m, l=line: l, text) if pattern.search(text) else text.rstrip("\n") + "\n" + line + "\n"
    fh.seek(0); fh.write(text); fh.truncate()
PY
unset KEY
chown sima:sima "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "Guardada en $ENV_FILE (solo lectura para el usuario sima)."

log "Reinicio del worker (espera a que no haya clases procesandose)"
systemctl restart sima-worker sima-web
sleep 3
sudo -u sima -H "$SIMA_HOME/venv/bin/python" "$APP_DIR/manage.py" check_ai 2>/dev/null | grep -iE "whisper|transcrip" || true

log "Listo"
echo "Prueba real opcional con un audio corto y no sensible:"
echo "  sudo -u sima -H $SIMA_HOME/venv/bin/python $APP_DIR/manage.py check_whisper_api /ruta/audio.mp3"
