#!/usr/bin/env bash
# Copia CLOUD_API_KEY del .env de esta PC al .env del VPS sin mostrarla y reinicia SIMA.
# Uso (Git Bash, desde la carpeta SIMAApp):  bash deploy/copiar_clave_groq.sh
set -euo pipefail

VPS_HOST="${SIMA_VPS_HOST:-162.243.33.172}"
VPS_PORT="${SIMA_VPS_SSH_PORT:-2222}"
VPS_USER="${SIMA_VPS_USER:-erick}"
KEY_FILE="${SIMA_ADMIN_KEY:-$HOME/.ssh/sima_admin_ed25519}"
ENV_LOCAL="$(dirname "$0")/../.env"

line="$(grep -m1 '^CLOUD_API_KEY=' "$ENV_LOCAL" | tr -d '\r' || true)"
if [[ -z "$line" || "$line" == "CLOUD_API_KEY=" ]]; then
    echo "No hay CLOUD_API_KEY en $ENV_LOCAL" >&2
    exit 1
fi

printf '%s\n' "$line" | ssh -i "$KEY_FILE" -p "$VPS_PORT" "$VPS_USER@$VPS_HOST" \
    'read -r L; sudo sed -i "s|^CLOUD_API_KEY=.*|$L|" /srv/sima/app/.env && sudo systemctl restart sima-web sima-worker && echo "listo: clave copiada y SIMA reiniciado"'
