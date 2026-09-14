#!/usr/bin/env bash
# SIMA — publicar con HTTPS en un subdominio y cerrar el puerto 8080 (idempotente: se puede volver a correr).
#
#   sudo bash /srv/sima/app/deploy/enable_https.sh sima.pmoluna.com
#
# Antes: en Cloudflare, registro A "sima" -> IP del VPS con el proxy APAGADO (nube gris, "DNS only").
#
# El sitio Nginx de SIMA se genera SIEMPRE completo desde deploy/nginx/sima.conf (no se edita lo que deja
# certbot). Cada version se escribe aparte, se valida con `nginx -t` y solo entonces reemplaza a la anterior;
# si no valida, se restaura la anterior. Asi el archivo en disco nunca queda invalido (un nginx invalido en
# disco pondria en riesgo a Luna en el siguiente reinicio).
#
# Fases:
#   1. Sin certificado: sitio HTTP en 80 y 8080, y `certbot certonly --nginx` (obtiene el certificado sin
#      tocar la configuracion).
#   2. Transicion: HTTPS en 443 + redireccion 80 -> 443, el 8080 sigue activo. Se verifica https://DOMINIO.
#   3. Final: sin 8080 ni IP, cookies seguras, HSTS, redireccion en Django y 8080 cerrado en UFW.
set -euo pipefail

DOMAIN="${1:-}"
SIMA_HOME="${SIMA_HOME:-/srv/sima}"
APP_DIR="$SIMA_HOME/app"
ENV_FILE="$APP_DIR/.env"
TEMPLATE="$APP_DIR/deploy/nginx/sima.conf"
SITE=/etc/nginx/sites-available/sima
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[AVISO] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Ejecuta con sudo."
[[ "$DOMAIN" =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]] || die "Uso: sudo bash $0 sima.pmoluna.com"
[[ -f "$ENV_FILE" ]] || die "No existe $ENV_FILE"
[[ -f "$TEMPLATE" ]] || die "No existe $TEMPLATE"
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

PUBLIC_IP="$(hostname -I | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' \
    | grep -vE '^(10\.|127\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' | head -1 || true)"

# Genera el sitio desde la plantilla. Modo: http | https-transition | https-final
render_site() {
    python3 - "$TEMPLATE" "$1" "$DOMAIN" "$PUBLIC_IP" "$CERT_DIR" <<'PY'
import os, sys
template, mode, domain, ip, cert_dir = sys.argv[1:6]
text = open(template, encoding="utf-8").read()
head = "    listen 80;\n    listen [::]:80;\n    server_name DOMINIO;\n"
if head not in text:
    sys.exit("La plantilla no tiene el bloque listen 80 / server_name DOMINIO esperado.")
transition = mode in ("http", "https-transition")
names = domain + (f" {ip}" if transition and ip else "")
extra = "    listen 8080; # transicion\n    listen [::]:8080; # transicion\n" if transition else ""
if mode == "http":
    new_head = f"    listen 80;\n    listen [::]:80;\n{extra}    server_name {names};\n"
    redirect = ""
else:
    ssl = [f"    ssl_certificate {cert_dir}/fullchain.pem;", f"    ssl_certificate_key {cert_dir}/privkey.pem;"]
    if os.path.exists("/etc/letsencrypt/options-ssl-nginx.conf"):
        ssl.append("    include /etc/letsencrypt/options-ssl-nginx.conf;")
    if os.path.exists("/etc/letsencrypt/ssl-dhparams.pem"):
        ssl.append("    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;")
    new_head = f"    listen 443 ssl;\n    listen [::]:443 ssl;\n{extra}    server_name {names};\n" + "\n".join(ssl) + "\n"
    redirect = (
        "\n# HTTP -> HTTPS\n"
        "server {\n"
        "    listen 80;\n"
        "    listen [::]:80;\n"
        f"    server_name {domain};\n"
        "    return 301 https://$host$request_uri;\n"
        "}\n"
    )
text = text.replace(head, new_head, 1).replace("DOMINIO", domain) + redirect
if text.count("{") != text.count("}"):
    sys.exit("Llaves desbalanceadas en la configuracion generada.")
sys.stdout.write(text)
PY
}

# Instala una version del sitio solo si nginx la valida; si no, restaura la anterior.
install_site() {
    local mode="$1" tmp prev
    tmp="$(mktemp)"
    render_site "$mode" > "$tmp" || { rm -f "$tmp"; die "No se pudo generar la configuracion ($mode)."; }
    prev="$(mktemp)"
    [[ -f "$SITE" ]] && cp -a "$SITE" "$prev"
    install -m 644 "$tmp" "$SITE"
    ln -sf "$SITE" /etc/nginx/sites-enabled/sima
    rm -f "$tmp"
    if ! nginx -t; then
        if [[ -s "$prev" ]]; then cp -a "$prev" "$SITE"; else rm -f "$SITE" /etc/nginx/sites-enabled/sima; fi
        rm -f "$prev"
        nginx -t >/dev/null 2>&1 || warn "La configuracion anterior tampoco valida: revisa /etc/nginx antes de reiniciar nginx."
        die "Nginx no valido la configuracion ($mode); se restauro la anterior."
    fi
    rm -f "$prev"
    systemctl reload nginx
}

log "DNS de $DOMAIN"
RESOLVED="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ')"
[[ -n "${RESOLVED// /}" ]] || die "$DOMAIN aun no resuelve. Crea el registro A en Cloudflare y espera un minuto."
SERVER_IPS=" $(hostname -I) "
for ip in $RESOLVED; do
    [[ "$SERVER_IPS" == *" $ip "* ]] || die "$DOMAIN apunta a $ip, que no es este servidor. En Cloudflare deja el registro en 'DNS only' (nube gris)."
done
echo "$DOMAIN -> $RESOLVED(este servidor)"

[[ -f "$SITE" ]] && cp -a "$SITE" "$SITE.bak.$(date +%Y%m%d%H%M%S)"

if [[ ! -f "$CERT_DIR/fullchain.pem" ]]; then
    log "Sitio HTTP temporal y certificado Let's Encrypt"
    install_site http
    CERTBOT_ARGS=(certonly --nginx -d "$DOMAIN" --non-interactive --keep-until-expiring)
    if [[ -z "$(ls -A /etc/letsencrypt/accounts 2>/dev/null)" ]]; then
        CERTBOT_ARGS+=(--agree-tos --register-unsafely-without-email)
    fi
    certbot "${CERTBOT_ARGS[@]}"
else
    log "Certificado ya emitido para $DOMAIN"
fi

log "HTTPS con el 8080 todavia activo"
install_site https-transition
HOSTS="$(get_env DJANGO_ALLOWED_HOSTS)"
[[ ",$HOSTS," == *",$DOMAIN,"* ]] || set_env DJANGO_ALLOWED_HOSTS "$DOMAIN${HOSTS:+,$HOSTS}"
ORIGINS="$(get_env CSRF_TRUSTED_ORIGINS)"
[[ ",$ORIGINS," == *",https://$DOMAIN,"* ]] || set_env CSRF_TRUSTED_ORIGINS "https://$DOMAIN${ORIGINS:+,$ORIGINS}"
set_env BEHIND_PROXY 1
systemctl restart sima-web
wait_https || die "https://$DOMAIN/salud/ no responde. El sitio sigue en el 8080; revisa journalctl -u sima-web -n 80 y /var/log/nginx/sima.error.log"
echo "https://$DOMAIN responde."

log "Solo HTTPS: fuera el 8080 y la IP; cookies seguras, HSTS y redireccion"
install_site https-final
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
echo "El certificado se renueva solo (certbot.timer)."
echo "Cuando todo vaya bien unos dias, puedes subir SECURE_HSTS_SECONDS a 31536000 en $ENV_FILE."
