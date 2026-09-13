#!/usr/bin/env bash
# =============================================================================
# SIMA — actualizar el VPS con lo ultimo de la rama (git pull + dependencias +
# migraciones + estaticos + reinicio + health check).
#
# Uso (en el VPS, como usuario con sudo):
#   sudo bash /srv/sima/app/deploy/update.sh
#   sudo BRANCH=main SKIP_WORKER_RESTART=1 bash /srv/sima/app/deploy/update.sh
#
# Antes de actualizar se guarda un respaldo de la BD (deploy/backup_db.sh) y se
# anota el commit anterior para poder volver atras (ver plan, seccion 12).
# =============================================================================
set -euo pipefail

BRANCH="${BRANCH:-main}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
SKIP_WORKER_RESTART="${SKIP_WORKER_RESTART:-0}"
APP_USER=sima
SIMA_HOME=/srv/sima
APP_DIR="$SIMA_HOME/app"
VENV="$SIMA_HOME/venv"
HEALTH_URL="http://127.0.0.1:8000/salud/"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[AVISO] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }
as_app() { sudo -u "$APP_USER" -H "$@"; }
manage() { as_app bash -c "cd '$APP_DIR' && '$VENV/bin/python' manage.py $*"; }

[[ $EUID -eq 0 ]] || die "Ejecuta con sudo: sudo bash $0"
[[ -d "$APP_DIR/.git" ]] || die "No existe $APP_DIR (corre primero deploy/bootstrap_vps.sh)"

PREV_COMMIT="$(as_app git -C "$APP_DIR" rev-parse HEAD)"
echo "$PREV_COMMIT $(date -Iseconds)" >> "$SIMA_HOME/deploy_history.log"
log "Commit actual: $PREV_COMMIT (anotado en $SIMA_HOME/deploy_history.log)"

if [[ "$SKIP_BACKUP" != "1" ]]; then
    log "Respaldo de la base de datos antes de migrar"
    bash "$APP_DIR/deploy/backup_db.sh" || die "Fallo el respaldo; aborto (usa SKIP_BACKUP=1 bajo tu riesgo)"
fi

log "git pull ($BRANCH)"
if [[ -n "$(as_app git -C "$APP_DIR" status --porcelain --untracked-files=no)" ]]; then
    die "Hay cambios locales sin commit en $APP_DIR; revisalos con git status"
fi
as_app git -C "$APP_DIR" fetch --prune origin
as_app git -C "$APP_DIR" checkout "$BRANCH"
as_app git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
NEW_COMMIT="$(as_app git -C "$APP_DIR" rev-parse HEAD)"
as_app git -C "$APP_DIR" log --oneline "$PREV_COMMIT..$NEW_COMMIT" | head -n 20 || true

log "Dependencias"
if as_app "$VENV/bin/python" -c "import whisper" >/dev/null 2>&1; then
    as_app "$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
else
    # Instalacion "solo texto": se respeta la omision de openai-whisper
    grep -viE '^openai-whisper' "$APP_DIR/requirements.txt" > "$SIMA_HOME/requirements-sin-whisper.txt"
    chown "$APP_USER:$APP_USER" "$SIMA_HOME/requirements-sin-whisper.txt"
    as_app "$VENV/bin/pip" install -r "$SIMA_HOME/requirements-sin-whisper.txt"
fi

log "Migraciones y estaticos"
manage migrate --noinput
manage collectstatic --noinput
manage check

log "Reinicio de servicios"
# Unidades por si cambiaron en el repo
changed_units=0
for unit in sima-web.service sima-worker.service sima-reminders.service sima-reminders.timer; do
    if ! cmp -s "$APP_DIR/deploy/systemd/$unit" "/etc/systemd/system/$unit"; then
        install -m 644 "$APP_DIR/deploy/systemd/$unit" /etc/systemd/system/
        changed_units=1
    fi
done
if [[ $changed_units -eq 1 ]]; then
    systemctl daemon-reload
fi
systemctl restart sima-web
if [[ "$SKIP_WORKER_RESTART" == "1" ]]; then
    warn "SKIP_WORKER_RESTART=1: el worker sigue con el codigo anterior hasta que lo reinicies"
else
    # Si hay un trabajo en curso, reiniciar lo corta; se reencola solo (ver plan, seccion 13).
    systemctl restart sima-worker
fi
systemctl restart sima-reminders.timer

log "Health check $HEALTH_URL"
ok=0
for _ in $(seq 1 30); do
    if body="$(curl -fsS -H "Host: 127.0.0.1" -H "X-Forwarded-Proto: https" "$HEALTH_URL")"; then
        ok=1
        echo "$body"
        break
    fi
    sleep 2
done
if [[ $ok -ne 1 ]]; then
    journalctl -u sima-web -n 40 --no-pager || true
    die "/salud/ no responde. Para volver atras: sudo -u $APP_USER git -C $APP_DIR checkout $PREV_COMMIT && sudo systemctl restart sima-web sima-worker"
fi
systemctl is-active --quiet sima-worker || warn "sima-worker no esta activo: journalctl -u sima-worker -n 50"
log "Actualizado: $PREV_COMMIT -> $NEW_COMMIT"
