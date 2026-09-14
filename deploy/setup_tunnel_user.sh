#!/usr/bin/env bash
# =============================================================================
# SIMA — usuario restringido para el tunel SSH inverso de transcripcion.
#
# La PC del equipo corre `manage.py serve_whisper` y abre:
#   ssh -N -R 127.0.0.1:9000:127.0.0.1:9000 sima-tunnel@IP_DEL_VPS
# Asi el worker del VPS transcribe llamando a http://127.0.0.1:9000 sin abrir
# puertos en la PC ni en el VPS.
#
# El usuario sima-tunnel NO tiene shell ni puede ejecutar comandos: su clave solo
# permite publicar el puerto 127.0.0.1:9000 del VPS.
#
# Uso (en el VPS, como root):
#   sudo bash setup_tunnel_user.sh "ssh-ed25519 AAAA... sima_tunnel@pc-erick"
# =============================================================================
set -euo pipefail

PUBKEY="${1:-}"
TUNNEL_USER="${TUNNEL_USER:-sima-tunnel}"
TUNNEL_PORT="${TUNNEL_PORT:-9000}"

[[ $EUID -eq 0 ]] || { echo "Ejecuta como root (sudo)." >&2; exit 1; }
[[ "$PUBKEY" == ssh-* ]] || { echo "Pasa la clave publica del tunel como primer argumento." >&2; exit 1; }

if ! id "$TUNNEL_USER" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "/home/$TUNNEL_USER" --shell /usr/sbin/nologin "$TUNNEL_USER"
fi
install -d -m 700 -o "$TUNNEL_USER" -g "$TUNNEL_USER" "/home/$TUNNEL_USER/.ssh"
AUTH="/home/$TUNNEL_USER/.ssh/authorized_keys"
# restrict quita pty, agente, X11 y reenvios; luego se permite solo el reenvio remoto al puerto indicado.
LINE="restrict,port-forwarding,permitlisten=\"127.0.0.1:$TUNNEL_PORT\",command=\"/bin/false\" $PUBKEY"
printf '%s\n' "$LINE" > "$AUTH"
chown "$TUNNEL_USER:$TUNNEL_USER" "$AUTH"
chmod 600 "$AUTH"

# Mantener vivo el tunel y liberar el puerto si la PC se desconecta sin cerrar.
DROPIN=/etc/ssh/sshd_config.d/60-sima-tunnel.conf
cat > "$DROPIN" <<EOF
Match User $TUNNEL_USER
    AllowTcpForwarding remote
    GatewayPorts no
    X11Forwarding no
    PermitTTY no
    ClientAliveInterval 30
    ClientAliveCountMax 3
EOF
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd

echo "Listo: $TUNNEL_USER solo puede publicar 127.0.0.1:$TUNNEL_PORT en este servidor."
