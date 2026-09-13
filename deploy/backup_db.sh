#!/usr/bin/env bash
# =============================================================================
# SIMA — respaldo de PostgreSQL en formato custom (pg_dump -Fc) con retencion.
#
# Uso manual:   sudo bash /srv/sima/app/deploy/backup_db.sh
# Diario (cron de root, 03:15):
#   echo '15 3 * * * root bash /srv/sima/app/deploy/backup_db.sh >> /var/log/sima-backup.log 2>&1' \
#     | sudo tee /etc/cron.d/sima-backup
# Restaurar:    ver PLAN_DESPLIEGUE_VPS.md, seccion 12 (pg_restore --clean).
#
# Variables: DB_NAME (sima), BACKUP_DIR (/srv/sima/backups), RETENTION_DAYS (14),
#            INCLUDE_MEDIA (1 = tambien empaqueta /srv/sima/app/media).
# =============================================================================
set -euo pipefail

DB_NAME="${DB_NAME:-sima}"
BACKUP_DIR="${BACKUP_DIR:-/srv/sima/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
INCLUDE_MEDIA="${INCLUDE_MEDIA:-1}"
MEDIA_DIR="${MEDIA_DIR:-/srv/sima/app/media}"

[[ $EUID -eq 0 ]] || { echo "Ejecuta con sudo" >&2; exit 1; }

stamp="$(date +%Y%m%d-%H%M%S)"
install -d -m 750 -o sima -g sima "$BACKUP_DIR"
out="$BACKUP_DIR/${DB_NAME}-${stamp}.dump"
tmp="$out.partial"

# El usuario postgres del sistema se autentica por "peer" sin contrasena
if ! sudo -u postgres pg_dump -Fc --no-owner --no-privileges "$DB_NAME" > "$tmp"; then
    rm -f "$tmp"
    echo "[ERROR] pg_dump fallo para la base $DB_NAME" >&2
    exit 1
fi
mv "$tmp" "$out"
chown sima:sima "$out"
chmod 640 "$out"
# Comprobacion rapida de que el archivo es legible por pg_restore
pg_restore --list "$out" > /dev/null
echo "$(date -Iseconds) respaldo OK: $out ($(du -h "$out" | cut -f1))"

if [[ "$INCLUDE_MEDIA" == "1" && -d "$MEDIA_DIR" ]] && [[ -n "$(ls -A "$MEDIA_DIR" 2>/dev/null)" ]]; then
    media_out="$BACKUP_DIR/media-${stamp}.tar.gz"
    tar -C "$(dirname "$MEDIA_DIR")" -czf "$media_out" "$(basename "$MEDIA_DIR")"
    chown sima:sima "$media_out"
    chmod 640 "$media_out"
    echo "$(date -Iseconds) media OK: $media_out"
fi

# Retencion: borra respaldos con mas de RETENTION_DAYS dias
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name "${DB_NAME}-*.dump" -o -name 'media-*.tar.gz' \) \
    -mtime +"$RETENTION_DAYS" -print -delete
