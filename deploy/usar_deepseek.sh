#!/usr/bin/env bash
# =============================================================================
# SIMA — usar DeepSeek (deepseek-chat) como modelo en la nube del VPS.
#
# Uso (en el VPS):  sudo bash /srv/sima/app/deploy/usar_deepseek.sh
#
# Pide la clave de DeepSeek sin mostrarla, respalda el .env, fija el proveedor,
# el modelo y la clave, quita el límite de tokens por minuto (propio de Groq) y
# reinicia la web y los workers. Para volver atrás: restaurar el respaldo que
# indica al final y reiniciar los servicios.
# =============================================================================
set -euo pipefail

ENV_FILE="${SIMA_ENV:-/srv/sima/app/.env}"
[[ $EUID -eq 0 ]] || { echo "Ejecuta con sudo: sudo bash $0" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }

read -r -s -p "Clave de DeepSeek (no se muestra): " CLAVE
echo
[[ "$CLAVE" == sk-* ]] || { echo "La clave de DeepSeek empieza por sk-" >&2; exit 1; }

RESPALDO="$ENV_FILE.antes-deepseek.$(date +%Y%m%d%H%M%S)"
cp -p "$ENV_FILE" "$RESPALDO"

fijar() {  # fijar CLAVE VALOR: reemplaza la línea o la agrega al final
    local k="$1" v="$2"
    if grep -q "^$k=" "$ENV_FILE"; then
        sed -i "s|^$k=.*|$k=$v|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$k" "$v" >> "$ENV_FILE"
    fi
}
fijar CLOUD_PROVIDER deepseek
fijar CLOUD_API_BASE https://api.deepseek.com
fijar CLOUD_MODEL deepseek-chat
fijar CLOUD_VERIFICATION_MODEL deepseek-chat
fijar CLOUD_LABEL DeepSeek
fijar CLOUD_TOKENS_PER_MINUTE 0
fijar CLOUD_API_KEY "$CLAVE"
unset CLAVE

for s in sima-web sima-worker sima-worker-study; do
    systemctl list-unit-files "$s.service" >/dev/null 2>&1 && systemctl restart "$s" || true
done
sleep 3
curl -s -H "Origin: https://mini-format.pmoluna.com" http://127.0.0.1:8000/api/mini/estado/ || true
echo
echo "Listo. Respaldo del .env anterior: $RESPALDO"
