#!/usr/bin/env bash
# SIMA — publicar con HTTPS en un subdominio y cerrar el puerto 8080 (idempotente).
#
#   sudo bash /srv/sima/app/deploy/enable_https.sh sima.pmoluna.com
#
# Antes: en Cloudflare, registro A "sima" -> IP del VPS con el proxy APAGADO (nube gris, "DNS only").
# Pasos: comprueba el DNS, pone el sitio Nginx de SIMA en el puerto 80 para el dominio (sin quitar
# aun el 8080), pide el certificado con certbot (redirige HTTP a HTTPS) y verifica HTTPS. Solo si
# responde: quita el 8080 y la IP, activa cookies seguras, HSTS y redireccion, y cierra el 8080 en UFW.
# Si algo falla antes de eso, el sitio sigue disponible en http://IP:8080.
# No modifica los sitios de Luna ni del simulador.
set -euo pipefail

DOMAIN="${1:-}"
SIMA_HOME="${SIMA_HOME:-/srv/sima}"
APP_DIR="$SIMA_HOME/app"
ENV_FILE="$APP_DIR/.env"
SITE=/etc/nginx/sites-available/sima

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[AVISO] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Ejecuta con sudo."
[[ "$DOMAIN" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] || die "Uso: sudo bash $0 sima.pmoluna.com"
[[ -f "$ENV_FILE" ]] || die "No existe $ENV_FILE"
command -v certbot >/dev/null || die "Falta certbot: sudo apt install certbot python3-certbot-nginx"

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

wait_https() {
    for _ in $(seq 1 25); do
        curl -fsS -o /dev/null "https://$DOMAIN/salud/" && return 0
        sleep 1
    done
    return 1
}

log "DNS de $DOMAIN"
SERVER_IPS=" $(hostname -I) "
RESOLVED="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ')"
[[ -n "${RESOLVED// /}" ]] || die "$DOMAIN aun no resuelve. Crea el registro A en Cloudflare y espera un minuto."
for ip in $RESOLVED; do
    [[ "$SERVER_IPS" == *" $ip "* ]] || die "$DOMAIN apunta a $ip, que no es este servidor. En Cloudflare deja el registro en 'DNS only' (nube gris) apuntando a la IP del VPS."
done
echo "$DOMAIN -> $RESOLVED(este servidor)"

log "Sitio Nginx de SIMA en el puerto 80 (el 8080 se mantiene durante la transicion)"
if ! grep -qs "ssl_certificate .*$DOMAIN" "$SITE"; then
    [[ -f "$SITE" ]] && cp -a "$SITE" "$SITE.bak.$(date +%Y%m%d%H%M%S)"
    PUBLIC_IP="$(get_env DJANGO_ALLOWED_HOSTS | tr ',' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' | grep -v '^127\.' | head -1 || true)"
    python3 - "$APP_DIR/deploy/nginx/sima.conf" "$SITE" "$DOMAIN" "$PUBLIC_IP" <<'PY'
import sys
src, dst, domain, ip = sys.argv[1:5]
text = open(src, encoding="utf-8").read()
names = domain + (" " + ip if ip else "")
text = text.replace("server_name DOMINIO;", f"server_name {names};", 1).replace("DOMINIO", domain)
text = text.replace("    listen [::]:80;\n",
                    "    listen [::]:80;\n    listen 8080; # sima-transicion\n    listen [::]:8080; # sima-transicion\n", 1)
open(dst, "w", encoding="utf-8").write(text)
PY
    ln -sf "$SITE" /etc/nginx/sites-enabled/sima
fi
nginx -t || die "Nginx no valida la configuracion; hay un respaldo en $SITE.bak.*"
systemctl reload nginx

log "Certificado Let's Encrypt"
CERTBOT_ARGS=(--nginx -d "$DOMAIN" --non-interactive --redirect --keep-until-expiring)
if [[ -z "$(ls -A /etc/letsencrypt/accounts 2>/dev/null)" ]]; then
    CERTBOT_ARGS+=(--agree-tos --register-unsafely-without-email)
fi
certbot "${CERTBOT_ARGS[@]}"
nginx -t && systemctl reload nginx

log "Verificacion de HTTPS (el 8080 sigue activo)"
HOSTS="$(get_env DJANGO_ALLOWED_HOSTS)"
[[ ",$HOSTS," == *",$DOMAIN,"* ]] || set_env DJANGO_ALLOWED_HOSTS "$DOMAIN${HOSTS:+,$HOSTS}"
ORIGINS="$(get_env CSRF_TRUSTED_ORIGINS)"
[[ ",$ORIGINS," == *",https://$DOMAIN,"* ]] || set_env CSRF_TRUSTED_ORIGINS "https://$DOMAIN${ORIGINS:+,$ORIGINS}"
set_env BEHIND_PROXY 1
systemctl restart sima-web
wait_https || die "https://$DOMAIN/salud/ no responde. El sitio sigue en el 8080; revisa journalctl -u sima-web -n 80 y /var/log/nginx/sima.error.log"
echo "https://$DOMAIN responde."

log "Solo HTTPS: fuera el 8080 y la IP; cookies seguras, HSTS y redireccion"
python3 - "$SITE" "$DOMAIN" <<'PY'
import re, sys
path, domain = sys.argv[1:3]
text = open(path, encoding="utf-8").read()
text = "".join(l for l in text.splitlines(keepends=True) if not l.rstrip().endswith("# sima-transicion"))
text = re.sub(rf"server_name {re.escape(domain)} [0-9.]+;", f"server_name {domain};", text)
open(path, "w", encoding="utf-8").write(text)
PY
nginx -t || die "Nginx no valida la configuracion final; revisa $SITE"
systemctl reload nginx
set_env DJANGO_ALLOWED_HOSTS "$DOMAIN,127.0.0.1,localhost"
set_env CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
set_env SIMA_SITE_URL "https://$DOMAIN"
set_env SECURE_SSL_REDIRECT 1
set_env SESSION_COOKIE_SECURE 1
set_env CSRF_COOKIE_SECURE 1
set_env SECURE_HSTS_SECONDS 3600
systemctl restart sima-web
wait_https || die "https://$DOMAIN dejo de responder tras el ajuste final; revisa journalctl -u sima-web -n 80"
systemctl restart sima-worker || warn "No se pudo reiniciar sima-worker"

log "Cierre del puerto 8080 en UFW"
if command -v ufw >/dev/null; then
    for n in $(ufw status numbered | grep -E '\] 8080(/tcp)? ' | sed -E 's/^\[ *([0-9]+)\].*/\1/' | sort -rn); do
        ufw --force delete "$n" >/dev/null
    done
    ufw status | grep -E '^(80|443|2222|3002|8080)' || true
fi

log "Listo: https://$DOMAIN"
echo "Cuando todo vaya bien unos dias, puedes subir SECURE_HSTS_SECONDS a 31536000 en $ENV_FILE."
