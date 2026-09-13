# Despliegue provisional en VPS (entorno de validacion)

Guia paso a paso para poner SIMA (Django + PostgreSQL + worker de IA + Whisper) en un
VPS Linux propio como **entorno provisional de validacion** (staging para la demostracion
ante el jurado). Pensada para seguirse en 1 a 2 horas.

> **Arquitectura objetivo de produccion: Microsoft Azure.** La arquitectura oficial de SIMA
> es la de los diagramas de arquitectura fisica y de despliegue de la tesis: Azure VM
> Ubuntu 22.04 con Nginx + Gunicorn + Django, Azure Database for PostgreSQL en subred
> privada, Network Security Group y, opcionalmente, Azure Blob Storage, Key Vault y Azure
> Monitor. Este VPS reproduce esa misma pila de aplicacion en un solo servidor para validarla;
> la seccion 14 explica como pasar de aqui a Azure.

**Arquitectura del entorno provisional**

```text
Internet ──443/80──> Nginx ──127.0.0.1:8000──> gunicorn (sima-web)  ──┐
                      │                                               ├──> PostgreSQL (local)
                      └── /static/ (archivos de collectstatic)        │
                                        sima-worker (run_worker) ─────┘──> Groq (API) + Whisper (CPU)
                                        sima-reminders.timer (18:00 diario, correo)
```

**Archivos del kit** (todos en `deploy/`):

| Archivo | Para que sirve |
|---|---|
| `PLAN_DESPLIEGUE_VPS.md` | Este plan |
| `env.production.example` | Plantilla del `.env` de produccion |
| `bootstrap_vps.sh` | Automatiza los pasos 2 a 8 (idempotente) |
| `update.sh` | Actualizar: respaldo + git pull + pip + migrate + collectstatic + reinicio + health check |
| `backup_db.sh` | Respaldo `pg_dump -Fc` con retencion de 14 dias |
| `systemd/sima-web.service` | gunicorn en 127.0.0.1:8000 |
| `systemd/sima-worker.service` | `manage.py run_worker` (cola en BD) |
| `systemd/sima-reminders.service` + `.timer` | `manage.py send_study_reminders` diario |
| `nginx/sima.conf` | Sitio Nginx (estaticos, subida de 200 MB, cabeceras de proxy, gzip) |

Convenciones: `DOMINIO` = tu dominio (ej. `sima.midominio.pe` o `simaupc.duckdns.org`),
`IP_DEL_VPS` = IP publica, `TU_USUARIO` = tu usuario con sudo en el VPS.
Los bloques marcados "PC (PowerShell)" se ejecutan en tu computadora Windows; el resto, en el VPS.

---

## 0. Antes de empezar

### 0.1 Subir tu codigo a GitHub (obligatorio, primero que todo)

El VPS descarga el codigo con `git clone` de `https://github.com/LiveLinDev/SIMAApp`,
rama `main`. **Todo lo que no este subido a `main` no llega al servidor**, incluido este
kit `deploy/` y los cambios de `sima/settings.py` y `requirements.txt`.

Estado detectado al preparar el kit (13-sep-2026): estas en la rama `fix-localmodel`
(36 commits sin subir a `origin/fix-localmodel`) y la rama local `main` tiene 24 commits
que no estan en `origin/main`; ademas hay cambios sin commit (este kit y ajustes de settings).

PC (PowerShell), en `D:\Tesis\SIMAApp`:

```bash
git status
git add deploy sima requirements.txt learning templates .env.example
git commit -m "Kit de despliegue en VPS y ajustes de produccion"
git switch main
git merge fix-localmodel
py -3.9 manage.py test learning
git push origin main
```

Revisa que `git status` no liste el `.env` (esta en `.gitignore`; nunca se sube).
Los despliegues salen **solo de `main`**: no apliques migraciones en la BD del servidor desde otra rama.

Si el repositorio es **privado**, el VPS necesita permiso de lectura: crea una *deploy key*
(ver 4.1, variante privada).

### 0.2 Que reunir

| Dato | Donde se consigue | Obligatorio |
|---|---|---|
| IP publica del VPS y usuario inicial (root o ubuntu) | Panel del proveedor (Hetzner, DigitalOcean, Contabo, Vultr, AWS Lightsail...) | Si |
| Dominio o subdominio DuckDNS | Tu registrador, o https://www.duckdns.org (gratis) | Si para HTTPS |
| Clave de API de Groq (`gsk_...`) | https://console.groq.com/keys | Si |
| Cuenta SMTP (usuario, contrasena de aplicacion, host, puerto) | Gmail (contrasena de aplicacion), Brevo, Mailjet... | Opcional (recordatorios por correo) |
| Clave SSH en tu PC | `ssh-keygen -t ed25519` | Si |
| Respaldo de la BD local (`sima_platform`) | Seccion 10 | Opcional (si quieres llevar tus datos) |

### 0.3 Tamano del VPS y memoria de Whisper

Minimo recomendado: **Ubuntu 24.04 LTS, 2 vCPU, 4 GB RAM, 25 GB de disco**.

- La web (3 procesos gunicorn) + PostgreSQL + Nginx usan ~600-900 MB.
- **Whisper corre en la CPU del VPS** dentro de `sima-worker`. Solo importar `torch`
  ya cuesta 300-500 MB. Memoria aproximada durante una transcripcion:

  | `WHISPER_MODEL` | RAM aprox. | Calidad / velocidad en 2 vCPU |
  |---|---|---|
  | `tiny` | ~1 GB | Rapido, mas errores |
  | `base` | ~1-1,5 GB | **Recomendado en 4 GB** |
  | `small` | ~2,5-3 GB | Solo con 8 GB de RAM |
  | `medium` / `large` | 5-10 GB | No en un VPS pequeno |

  Un audio largo suma memoria (1 h de audio ~ 250 MB solo de muestras). En CPU, una
  hora de audio puede tardar de 20 a 60 minutos con `base`.
- Con 4 GB crea un **swapfile de 4 GB** (el bootstrap lo hace si no hay swap) y usa
  `WHISPER_MODEL=base` (o `tiny` con 2 GB). El servicio del worker tiene `MemoryMax=2500M`
  para que, si Whisper se desborda, muera el worker y no la web ni PostgreSQL.
- Disco: torch CPU + Whisper + dependencias ocupan ~1,5 GB; el modelo `base`, 140 MB.
- **Clases solo de texto no necesitan Whisper.** Con `INSTALL_WHISPER=0` en el bootstrap
  el VPS puede ser de 2 GB, pero las clases con audio fallaran.

Diferencias con **Ubuntu 22.04**: trae Python 3.10 y PostgreSQL 14 (24.04 trae 3.12 y 16).
Ambos sirven para Django 5.2. El resto de comandos es igual.

### 0.4 Dominio: real o DuckDNS

Let's Encrypt **solo emite certificados para nombres de dominio**, no para IPs.

- **Dominio propio**: en tu registrador crea un registro `A` `sima` -> `IP_DEL_VPS`
  (y `AAAA` si tu VPS tiene IPv6). Espera a que resuelva.
- **DuckDNS (gratis)**: entra en https://www.duckdns.org con tu cuenta de GitHub/Google,
  crea el subdominio (ej. `simaupc`), escribe `IP_DEL_VPS` en *current ip* y pulsa
  *update ip*. Tu dominio sera `simaupc.duckdns.org`. La IP de un VPS no cambia, asi que
  no hace falta el script de actualizacion periodica.

Comprueba desde tu PC que el nombre apunta al VPS:

```bash
nslookup DOMINIO
```

- **Solo IP (demo rapida, sin HTTPS)**: usa `IP_DEL_VPS` como `DOMAIN`. Funciona por
  `http://IP_DEL_VPS/`, sin cifrado (las contrasenas viajan en claro). Solo para una demo corta.

---

## 1. Endurecimiento basico del servidor

Conectate como el usuario inicial que te dio el proveedor:

```bash
ssh root@IP_DEL_VPS
```

### 1.1 Usuario con sudo y clave SSH

```bash
adduser TU_USUARIO
usermod -aG sudo TU_USUARIO
mkdir -p /home/TU_USUARIO/.ssh
cp ~/.ssh/authorized_keys /home/TU_USUARIO/.ssh/ 2>/dev/null || true
chown -R TU_USUARIO:TU_USUARIO /home/TU_USUARIO/.ssh
chmod 700 /home/TU_USUARIO/.ssh
```

Si el proveedor no cargo tu clave, copiala desde tu PC (PowerShell):

```bash
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh TU_USUARIO@IP_DEL_VPS "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

**En otra ventana**, verifica que entras con la clave antes de seguir:

```bash
ssh TU_USUARIO@IP_DEL_VPS
```

Desactiva el acceso por contrasena y el login de root:

```bash
printf 'PasswordAuthentication no\nPermitRootLogin no\nKbdInteractiveAuthentication no\n' | sudo tee /etc/ssh/sshd_config.d/99-sima.conf
sudo sshd -t && sudo systemctl restart ssh
```

### 1.2 Firewall (solo 22, 80 y 443)

```bash
sudo apt-get update && sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status verbose
```

Si tu proveedor tiene ademas un firewall en el panel (AWS, Oracle, GCP), abre ahi los mismos puertos.

### 1.3 Actualizaciones automaticas y fail2ban (opcional)

```bash
sudo apt-get upgrade -y
sudo apt-get install -y unattended-upgrades fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
sudo timedatectl set-timezone America/Lima
```

(fail2ban ya trae la jaula `sshd` activa en Ubuntu. Si no arranca en 24.04, `sudo apt-get upgrade` lo corrige.)
Si `apt-get upgrade` instalo un kernel nuevo: `sudo reboot` y vuelve a entrar.

---

## Via rapida: bootstrap automatico (pasos 2 a 8)

Si prefieres no teclear los pasos 2 a 8, el script los hace por ti. Se puede repetir sin romper nada.

```bash
sudo apt-get update && sudo apt-get install -y git
git clone --branch main https://github.com/LiveLinDev/SIMAApp.git ~/SIMAApp
read -rsp "Clave de Groq: " GROQ_API_KEY; echo; export GROQ_API_KEY
sudo --preserve-env=GROQ_API_KEY DOMAIN=DOMINIO bash ~/SIMAApp/deploy/bootstrap_vps.sh
```

Opciones: `INSTALL_WHISPER=0` (solo texto), `SWAP_SIZE=0`, `BRANCH=...`, `DB_PASSWORD=...`.
(`read -rsp` evita que la clave quede en el historial de bash.)

Al terminar, salta al **paso 6.3** (createsuperuser y `check_ai --ping`) y luego al **paso 9** (HTTPS).
Si algo falla, el script se detiene en el paso con error: corrige y vuelve a ejecutarlo.
Los pasos 2 a 8 de abajo explican lo mismo a mano.

---

## 2. Paquetes del sistema

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev build-essential libpq-dev \
    postgresql postgresql-contrib nginx ffmpeg git curl ca-certificates openssl \
    certbot python3-certbot-nginx
```

Swapfile de 4 GB (si `swapon --show` no muestra nada):

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-sima-swap.conf
sudo sysctl -p /etc/sysctl.d/99-sima-swap.conf
free -h
```

## 3. PostgreSQL: rol y base de datos

```bash
DB_PASSWORD="$(openssl rand -hex 24)"
echo "Guarda esta contrasena para el .env: $DB_PASSWORD"
sudo -u postgres psql -c "CREATE ROLE sima WITH LOGIN PASSWORD '$DB_PASSWORD';"
sudo -u postgres createdb -O sima -E UTF8 -T template0 sima
sudo -u postgres psql -c "\l sima"
```

PostgreSQL solo escucha en `localhost` por defecto: no abras el puerto 5432 en el firewall.

## 4. Usuario de la aplicacion, codigo y entorno virtual

### 4.1 Usuario `sima` y codigo en `/srv/sima/app`

```bash
sudo useradd --system --create-home --home-dir /srv/sima --shell /bin/bash sima
sudo chmod 755 /srv/sima
sudo -u sima -H git clone --branch main https://github.com/LiveLinDev/SIMAApp.git /srv/sima/app
ls /srv/sima/app/deploy
```

Si `deploy/` no aparece, no hiciste el `git push` del paso 0.1.

*Variante repositorio privado*: crea una clave para `sima` y agregala en GitHub ->
repo -> Settings -> Deploy keys (solo lectura):

```bash
sudo -u sima -H install -d -m 700 /srv/sima/.ssh
sudo -u sima -H ssh-keygen -t ed25519 -N "" -f /srv/sima/.ssh/id_ed25519
sudo cat /srv/sima/.ssh/id_ed25519.pub
sudo -u sima -H git clone --branch main git@github.com:LiveLinDev/SIMAApp.git /srv/sima/app
```

### 4.2 Entorno virtual y dependencias

Primero **torch solo CPU** (si no, pip descarga varios GB de librerias CUDA que un VPS no usa):

```bash
sudo -u sima -H python3 -m venv /srv/sima/venv
sudo -u sima -H /srv/sima/venv/bin/pip install --upgrade pip wheel
sudo -u sima -H /srv/sima/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
sudo -u sima -H /srv/sima/venv/bin/pip install -r /srv/sima/app/requirements.txt
sudo -u sima -H /srv/sima/venv/bin/python -c "import django, gunicorn, whisper, torch; print(django.get_version(), torch.__version__)"
```

`gunicorn` ya viene en `requirements.txt` (con el marcador `sys_platform != "win32"`, asi
en tu PC Windows no se instala y en Linux si). Se eligio **no** crear un `requirements-prod.txt`
aparte: gunicorn es pequeno, puro Python y un solo archivo evita que el VPS y la PC se desincronicen.

*Sin Whisper (solo clases de texto, VPS de 2 GB)*:

```bash
grep -viE '^openai-whisper' /srv/sima/app/requirements.txt | sudo -u sima -H tee /srv/sima/requirements-sin-whisper.txt
sudo -u sima -H /srv/sima/venv/bin/pip install -r /srv/sima/requirements-sin-whisper.txt
```

## 5. Archivo `.env` de produccion

`sima/settings.py` lee `/srv/sima/app/.env` por su cuenta (no hace falta `EnvironmentFile`
en systemd) y **sus valores pisan las variables de entorno del sistema**.
Los comentarios van **solo en su propia linea**: un `# ...` al final de una linea se vuelve parte del valor.

```bash
sudo -u sima cp /srv/sima/app/deploy/env.production.example /srv/sima/app/.env
sudo chmod 600 /srv/sima/app/.env
SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
sudo sed -i -e "s|CAMBIAR_SECRET_KEY|$SECRET|" -e "s|CAMBIAR_DB_PASSWORD|$DB_PASSWORD|g" -e "s|DOMINIO|DOMINIO_REAL|g" /srv/sima/app/.env
sudo -u sima nano /srv/sima/app/.env
```

(En el `sed`, cambia `DOMINIO_REAL` por tu dominio. Si cerraste la sesion y perdiste
`$DB_PASSWORD`, escribelo a mano en `nano`.)

Revisa en `nano`:

- `CLOUD_API_KEY=` tu clave `gsk_...` de Groq.
- `DJANGO_ALLOWED_HOSTS=DOMINIO,127.0.0.1,localhost` y `CSRF_TRUSTED_ORIGINS=https://DOMINIO`
  (modo solo IP: `http://IP_DEL_VPS`).
- `SIMA_QUEUE_MODE=db` (con gunicorn no uses `thread`).
- `LOCAL_AI_ENABLED=False`: en el VPS no hay Ollama/LM Studio; las acciones que antes
  pedian el modelo local (reparar transcripcion, coherencia) usan Groq.
- `WHISPER_MODEL=base` (o `tiny`).
- Fase 1 (sin HTTPS aun): `SECURE_SSL_REDIRECT=0`, `SESSION_COOKIE_SECURE=0`,
  `CSRF_COOKIE_SECURE=0`, `SECURE_HSTS_SECONDS=0`, y `BEHIND_PROXY=1` siempre.
- Correo SMTP (opcional): `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`,
  `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`.

Comprueba que no quedaron marcadores:

```bash
sudo grep -nE 'CAMBIAR_|DOMINIO' /srv/sima/app/.env
```

## 6. Migraciones, estaticos y comprobaciones

### 6.1 Migrar y recolectar estaticos

```bash
cd /srv/sima/app
sudo -u sima -H install -d -m 750 media logs
sudo -u sima -H /srv/sima/venv/bin/python manage.py migrate --noinput
sudo -u sima -H /srv/sima/venv/bin/python manage.py collectstatic --noinput
```

`collectstatic` copia ~132 archivos a `/srv/sima/app/staticfiles` (valor de `STATIC_ROOT`).

### 6.2 Comprobaciones de Django

```bash
cd /srv/sima/app
sudo -u sima -H /srv/sima/venv/bin/python manage.py check --deploy
```

En la fase 1 (HTTP) salen 4 avisos esperados: `W004` (HSTS), `W008` (SSL redirect),
`W012` (cookie de sesion) y `W016` (cookie CSRF). Desaparecen en el paso 9. Despues
de activar HTTPS solo queda `W021` (HSTS preload), que es opcional.
Cualquier **ERROR**, o avisos `W009` (SECRET_KEY debil) o `W018` (DEBUG activo), hay que corregirlos.

### 6.3 Administrador y prueba de la IA

```bash
cd /srv/sima/app
sudo -u sima -H /srv/sima/venv/bin/python manage.py createsuperuser
sudo -u sima -H /srv/sima/venv/bin/python manage.py check_ai
sudo -u sima -H /srv/sima/venv/bin/python manage.py check_ai --ping
```

`check_ai --ping` hace una llamada minima real a Groq (gasta unos pocos tokens). Si falla,
revisa `CLOUD_API_KEY`, `CLOUD_MODEL` y la seccion 13.

Precarga opcional del modelo Whisper (evita que la primera clase con audio lo descargue):

```bash
sudo -u sima -H /srv/sima/venv/bin/python -c "import whisper; whisper.load_model('base')"
```

## 7. Servicios systemd

```bash
sudo install -m 644 /srv/sima/app/deploy/systemd/sima-web.service /etc/systemd/system/
sudo install -m 644 /srv/sima/app/deploy/systemd/sima-worker.service /etc/systemd/system/
sudo install -m 644 /srv/sima/app/deploy/systemd/sima-reminders.service /etc/systemd/system/
sudo install -m 644 /srv/sima/app/deploy/systemd/sima-reminders.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sima-web sima-worker sima-reminders.timer
systemctl status sima-web sima-worker --no-pager
systemctl list-timers sima-reminders.timer
curl -s -H "Host: 127.0.0.1" http://127.0.0.1:8000/salud/
```

Que hace cada unidad:

- **sima-web**: `gunicorn sima.wsgi:application --bind 127.0.0.1:8000 --workers 3 --threads 2 --timeout 300`.
  El timeout es largo porque dos vistas llaman a la IA **de forma sincrona** dentro de la
  peticion: *reparar transcripcion* (`/clase/<id>/transcripcion/`) y *reparar coherencia*
  (`/clase/<id>/coherencia/`); con reintentos ante 429 de Groq pueden tardar minutos. Todo lo
  demas pesado (pipeline de clases, refuerzos, resumenes) se encola y lo procesa el worker.
- **sima-worker**: `python manage.py run_worker` (reclama trabajos con `select_for_update(skip_locked)`).
  Un solo worker basta en 4 GB; dos workers con Whisper pueden agotar la RAM.
- **sima-reminders.timer**: ejecuta `send_study_reminders` todos los dias a las 18:00 (hora de Lima).
  Prueba manual: `sudo systemctl start sima-reminders && journalctl -u sima-reminders -n 30`.

## 8. Nginx

```bash
sudo cp /srv/sima/app/deploy/nginx/sima.conf /etc/nginx/sites-available/sima
sudo sed -i 's/DOMINIO/DOMINIO_REAL/g' /etc/nginx/sites-available/sima
sudo ln -sf /etc/nginx/sites-available/sima /etc/nginx/sites-enabled/sima
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
curl -sI http://DOMINIO/ | head -n 5
```

Lo que configura `sima.conf`:

- `location /static/` -> `alias /srv/sima/app/staticfiles/` (cache 7 dias).
- `location /media/` -> `alias /srv/sima/app/media/` marcado `internal`: los audios subidos
  son privados y se borran tras transcribir; ninguna pagina los enlaza, asi que no se publican.
- `client_max_body_size 200M` para audios de clase.
- `proxy_read_timeout 310s` (algo mas que el `--timeout 300` de gunicorn).
- Cabeceras `Host`, `X-Real-IP`, `X-Forwarded-For` y **`X-Forwarded-Proto`** (Django la usa
  con `BEHIND_PROXY=1` para saber que la peticion llego por HTTPS).
- `gzip` para HTML, CSS, JS, JSON y SVG.

Abre `http://DOMINIO/` en el navegador: debe cargar la portada.

## 9. HTTPS con Let's Encrypt

Requiere que `DOMINIO` ya apunte al VPS y que el puerto 80 este abierto.

```bash
sudo certbot --nginx -d DOMINIO --redirect -m tu_correo@ejemplo.com --no-eff-email
sudo certbot renew --dry-run
systemctl list-timers | grep certbot
```

certbot te pedira aceptar los terminos de Let's Encrypt; agrega el bloque `listen 443 ssl`
a `/etc/nginx/sites-available/sima`, redirige HTTP a HTTPS y deja programada la renovacion.

Ahora activa la seguridad de HTTPS en Django (fase 2):

```bash
sudo sed -i -e 's/^SECURE_SSL_REDIRECT=.*/SECURE_SSL_REDIRECT=1/' \
            -e 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=1/' \
            -e 's/^CSRF_COOKIE_SECURE=.*/CSRF_COOKIE_SECURE=1/' \
            -e 's/^SECURE_HSTS_SECONDS=.*/SECURE_HSTS_SECONDS=3600/' /srv/sima/app/.env
sudo grep -nE '^(BEHIND_PROXY|SECURE_|SESSION_COOKIE_SECURE|CSRF_)' /srv/sima/app/.env
sudo systemctl restart sima-web sima-worker
cd /srv/sima/app && sudo -u sima -H /srv/sima/venv/bin/python manage.py check --deploy
curl -sI http://DOMINIO/ | head -n 3
curl -s https://DOMINIO/salud/
```

- `check --deploy` debe mostrar solo `W021` (preload de HSTS, opcional).
- Tras unos dias sin problemas, sube `SECURE_HSTS_SECONDS=31536000`. Ojo: con HSTS los
  navegadores recuerdan que el sitio es solo HTTPS; no lo actives si piensas volver a HTTP.
- `SIMA_SITE_URL=https://DOMINIO` para que los enlaces de los correos sean correctos.

**Modo demo solo IP**: omite este paso; deja los `SECURE_*` en 0 y `CSRF_TRUSTED_ORIGINS=http://IP_DEL_VPS`.

## 10. Migrar los datos desde tu PC

Haz esto **despues** del paso 6 y **antes** de que alguien use el sitio (se reemplaza la BD del VPS).

### 10.1 Volcado de la BD local (PC, PowerShell)

Tu PostgreSQL local es la version 18, en el puerto 5433, base `sima_platform`:

```bash
New-Item -ItemType Directory -Force D:\respaldos | Out-Null
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h 127.0.0.1 -p 5433 -U postgres -Fc --no-owner --no-privileges -f D:\respaldos\sima_platform.dump sima_platform
scp D:\respaldos\sima_platform.dump TU_USUARIO@IP_DEL_VPS:/tmp/
```

### 10.2 Restaurar en el VPS con `pg_restore`

Un volcado hecho con `pg_dump` 18 solo lo lee `pg_restore` 18 o superior; Ubuntu trae 16 (24.04)
o 14 (22.04). Instala solo el **cliente** 18 del repositorio oficial de PostgreSQL (el servidor sigue siendo el de Ubuntu):

```bash
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-client-18
/usr/lib/postgresql/18/bin/pg_restore --version
```

Restaura en una base limpia con el rol `sima` como dueno:

```bash
sudo systemctl stop sima-web sima-worker
sudo bash /srv/sima/app/deploy/backup_db.sh
sudo -u postgres dropdb sima
sudo -u postgres createdb -O sima -E UTF8 -T template0 sima
sudo chmod 644 /tmp/sima_platform.dump
sudo -u postgres /usr/lib/postgresql/18/bin/pg_restore --no-owner --no-privileges --role=sima -d sima /tmp/sima_platform.dump
cd /srv/sima/app && sudo -u sima -H /srv/sima/venv/bin/python manage.py migrate --noinput
sudo systemctl start sima-web sima-worker
sudo rm /tmp/sima_platform.dump
```

- Un error como `unrecognized configuration parameter "transaction_timeout"` es inofensivo
  (parametro de PostgreSQL 17+ que el servidor 16 no conoce); `pg_restore` sigue y al final dice
  `errors ignored on restore: 1`. Otros errores si hay que revisarlos.
- `migrate` aplica migraciones que el VPS tenga y tu PC no.
- Si el volcado trae trabajos en `QUEUED`/`PROCESSING`, el worker los retomara (y gastara tokens de Groq).

*Alternativa sin instalar el cliente 18*: volcado en SQL plano desde la PC
(`pg_dump.exe ... -Fp --no-owner --no-privileges -f D:\respaldos\sima_platform.sql sima_platform`) y en el VPS:

```bash
PGPASSWORD="$(sudo grep '^POSTGRES_PASSWORD=' /srv/sima/app/.env | cut -d= -f2-)" psql -h 127.0.0.1 -U sima -d sima -f /tmp/sima_platform.sql
```

### 10.3 Copiar `media/`

Los audios se borran tras transcribirse, asi que `media/` suele ser pequeno (hoy ~5 MB de restos).
Copialo solo si quieres conservarlo. PC (PowerShell):

```bash
scp -r D:\Tesis\SIMAApp\media TU_USUARIO@IP_DEL_VPS:/tmp/sima-media
```

VPS:

```bash
sudo cp -r /tmp/sima-media/. /srv/sima/app/media/
sudo chown -R sima:sima /srv/sima/app/media
sudo rm -rf /tmp/sima-media
```

### 10.4 Alternativa: mover solo algunos cursos

Util si no quieres llevar usuarios ni historial. En la PC:

```bash
py -3.9 manage.py export_course 5 --out D:\respaldos\curso_5.json
scp D:\respaldos\curso_5.json TU_USUARIO@IP_DEL_VPS:/tmp/
```

En el VPS (el usuario destino ya debe existir, p. ej. el que creaste con `createsuperuser` o `/registro/`):

```bash
cd /srv/sima/app
sudo chmod 644 /tmp/curso_5.json
sudo -u sima -H /srv/sima/venv/bin/python manage.py import_course /tmp/curso_5.json --user NOMBRE_DE_USUARIO
sudo -u sima -H /srv/sima/venv/bin/python manage.py sync_question_bank
```

## 11. Prueba de humo

Abre cada URL (con `https://DOMINIO`, o `http://IP_DEL_VPS` en modo demo):

| URL | Esperado |
|---|---|
| `/` | Portada con estilos (si sale sin CSS: seccion 13, "estaticos 404") |
| `/salud/` | JSON con `"status": "ok"`, `"database": "ok"`, `"queue": {"mode": "db", ...}`, `"cloud_backend": true` |
| `/registro/` | Formulario; crea un usuario de prueba (sin error 403 de CSRF) |
| `/login/` | Inicia sesion con ese usuario |
| `/dashboard/` | Panel del estudiante |
| `/cursos/nuevo/` | Crea un curso "Prueba" |
| `/api/nueva/` | Formulario de nueva clase con IA |
| `/admin/` | Admin de Django con el superusuario (con estilos) |

Prueba del pipeline completo con una clase **de texto**:

1. En una terminal del VPS, deja mirando el worker y el log de la app:

   ```bash
   sudo journalctl -u sima-worker -f
   ```

   ```bash
   sudo tail -f /srv/sima/app/logs/sima.log
   ```

2. En `/api/nueva/` elige el curso "Prueba", pega 400-800 palabras de texto de una clase
   (p. ej. el contenido de `clase_fotosintesis_3000.txt` de tu PC) y envia.
3. En el worker debe aparecer `-> lesson #N (auto)`, las etapas (generacion, verificacion...)
   y al final `listo en XXs`. Con el nivel gratuito de Groq puede tardar varios minutos
   (espera entre llamadas por el limite de tokens por minuto).
4. La pagina de la clase pasa a "completado" y muestra los items; abre el quiz y las flashcards.
5. (Opcional) Repite con un audio corto (1-2 min) para probar Whisper, y mira la RAM con `free -h` mientras transcribe.

Comprobaciones de servicios:

```bash
systemctl is-active sima-web sima-worker nginx postgresql
systemctl list-timers sima-reminders.timer
cd /srv/sima/app && sudo -u sima -H /srv/sima/venv/bin/python manage.py send_study_reminders --dry-run
```

## 12. Operacion diaria

### 12.1 Publicar cambios

En la PC: commit, merge a `main` y `git push origin main`. En el VPS:

```bash
sudo bash /srv/sima/app/deploy/update.sh
```

`update.sh` hace: respaldo de la BD -> anota el commit actual en `/srv/sima/deploy_history.log`
-> `git pull --ff-only` -> `pip install -r requirements.txt` -> `migrate` -> `collectstatic`
-> `check` -> reinstala unidades systemd si cambiaron -> reinicia `sima-web` y `sima-worker`
-> espera a que `/salud/` responda. Reiniciar el worker corta un trabajo en curso: actualiza
cuando la cola este vacia (mira `/salud/`) o usa `SKIP_WORKER_RESTART=1` y reinicia despues.

### 12.2 Logs

```bash
journalctl -u sima-web -n 100 --no-pager
journalctl -u sima-worker -f
journalctl -u sima-reminders -n 50 --no-pager
sudo tail -n 200 /srv/sima/app/logs/sima.log
sudo tail -n 100 /var/log/nginx/sima.error.log
sudo tail -n 100 /var/log/nginx/sima.access.log
```

### 12.3 Respaldos

Diario a las 03:15, con 14 dias de retencion (`/srv/sima/backups/sima-AAAAMMDD-HHMMSS.dump` y `media-*.tar.gz`):

```bash
echo '15 3 * * * root bash /srv/sima/app/deploy/backup_db.sh >> /var/log/sima-backup.log 2>&1' | sudo tee /etc/cron.d/sima-backup
sudo bash /srv/sima/app/deploy/backup_db.sh
ls -lh /srv/sima/backups
```

Un respaldo que vive solo en el VPS se pierde con el VPS. Bajalo a tu PC de vez en cuando (PowerShell):

```bash
scp "TU_USUARIO@IP_DEL_VPS:/srv/sima/backups/sima-*.dump" D:\respaldos\
```

(Si `scp` no puede leer los archivos, en el VPS: `sudo usermod -aG sima TU_USUARIO` y vuelve a entrar por SSH.)

Restaurar un respaldo:

```bash
sudo systemctl stop sima-web sima-worker
sudo cat /srv/sima/backups/sima-AAAAMMDD-HHMMSS.dump | sudo -u postgres pg_restore --clean --if-exists --no-owner --no-privileges --role=sima -d sima
sudo systemctl start sima-web sima-worker
```

### 12.4 Volver atras (rollback)

```bash
tail -n 5 /srv/sima/deploy_history.log
sudo systemctl stop sima-worker
sudo -u sima -H git -C /srv/sima/app checkout COMMIT_ANTERIOR
cd /srv/sima/app && sudo -u sima -H /srv/sima/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart sima-web sima-worker
curl -s -H "Host: 127.0.0.1" http://127.0.0.1:8000/salud/
```

- Si la version nueva **agrego migraciones**, el codigo viejo puede no entender la BD: restaura
  el respaldo que `update.sh` hizo justo antes (12.3), o deshaz la migracion con
  `manage.py migrate learning NUMERO_MIGRACION_ANTERIOR` antes del `checkout`.
- Para volver a la rama: `sudo -u sima -H git -C /srv/sima/app checkout main` y `update.sh`.

## 13. Solucion de problemas

| Sintoma | Causa probable | Que hacer |
|---|---|---|
| **502 Bad Gateway** | gunicorn caido o arrancando | `systemctl status sima-web`, `journalctl -u sima-web -n 80`. Errores tipicos: `.env` con `CAMBIAR_...`, BD inaccesible (`POSTGRES_PASSWORD`), `ModuleNotFoundError` (falto `pip install`). Prueba `curl -H "Host: 127.0.0.1" http://127.0.0.1:8000/salud/` |
| **504 Gateway Timeout** | Vista sincrona con la IA tardo mas de 310 s | Suele ser reparar transcripcion/coherencia con 429 de Groq. Reintenta luego; si pasa siempre, sube `--timeout` en la unidad y `proxy_read_timeout` en Nginx |
| **400 Bad Request** | Host no permitido | Agrega el dominio o IP a `DJANGO_ALLOWED_HOSTS` y `sudo systemctl restart sima-web` |
| **Estaticos 404 / pagina sin estilos** | Falta `collectstatic` o Nginx no puede leer | `manage.py collectstatic --noinput`; revisa `alias /srv/sima/app/staticfiles/;` (con barra final); permisos: `sudo chmod 755 /srv/sima /srv/sima/app`; `sudo -u www-data ls /srv/sima/app/staticfiles` |
| **403 CSRF verification failed** tras activar HTTPS | Django no sabe que la peticion es HTTPS, o el origen no esta confiado | `BEHIND_PROXY=1` en `.env`, `CSRF_TRUSTED_ORIGINS=https://DOMINIO` (con `https://`, sin barra final), `proxy_set_header X-Forwarded-Proto $scheme;` en Nginx; reinicia `sima-web`. Borra cookies del sitio |
| **Redireccion infinita (ERR_TOO_MANY_REDIRECTS)** | `SECURE_SSL_REDIRECT=1` sin `BEHIND_PROXY=1` | Pon `BEHIND_PROXY=1` y reinicia |
| No inicia sesion con HTTP (modo IP) | Cookies `Secure` sin HTTPS | En modo IP: `SESSION_COOKIE_SECURE=0`, `CSRF_COOKIE_SECURE=0`, `SECURE_SSL_REDIRECT=0` |
| **413 Request Entity Too Large** al subir audio | Limite de Nginx | Sube `client_max_body_size` en `/etc/nginx/sites-available/sima` (tambien en el bloque 443 si certbot lo duplico), `sudo nginx -t && sudo systemctl reload nginx` |
| **Groq 429** (rate limit) en el log | Nivel gratuito: tokens por minuto o tope diario | SIMA espera y reintenta solo (`CLOUD_RATE_LIMIT_RETRIES`). Web y worker llevan cada uno su propio limitador: deja `CLOUD_TOKENS_PER_MINUTE` por debajo de la cuota (6000 < 8000). Si es el tope **diario**, espera al dia siguiente o usa un plan de pago |
| **Groq 413** (request too large) | Peticion supera los tokens por peticion del modelo | Baja `CLOUD_CHUNK_WORDS` (p. ej. 900), `VERIFICATION_CONTEXT_MAX_CHARS` (6000) y `CLOUD_MAX_TOKENS` (3000); reinicia web y worker |
| `check_ai --ping` falla con 401/404 | Clave o modelo | Revisa `CLOUD_API_KEY`; confirma el id del modelo en console.groq.com/docs/models; prueba otro con `check_ai --ping --model openai/gpt-oss-120b` |
| **Clases quedan "en cola" para siempre** | Worker parado o cola en modo `thread` | `systemctl status sima-worker`; `.env` debe tener `SIMA_QUEUE_MODE=db` (web **y** worker lo leen; reinicia ambos); `journalctl -u sima-worker -n 50`. `/salud/` muestra los conteos |
| **Clase atascada en "procesando"** tras reiniciar el worker | El reinicio corto el trabajo; se reencola solo tras 120 min sin actividad | Para retomarla ya (con un solo worker): `sudo systemctl stop sima-worker`, luego `cd /srv/sima/app && sudo -u sima -H /srv/sima/venv/bin/python manage.py shell -c "from learning.job_queue import reset_stale_processing; print(reset_stale_processing(1))"` y `sudo systemctl start sima-worker` |
| **Worker muere transcribiendo** (`Killed`, `oom-kill`, `status=9/KILL`) | Whisper sin memoria | `journalctl -u sima-worker -n 50` y `sudo journalctl -k --grep=oom -n 20`. Usa `WHISPER_MODEL=tiny`, confirma swap (`free -h`), audios mas cortos, o un VPS de 8 GB; ajusta `MemoryMax` en `sima-worker.service` |
| `No module named whisper` en el worker | Instalado sin Whisper | `sudo -u sima -H /srv/sima/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu` y `pip install openai-whisper`; reinicia el worker |
| Error `Failed to load audio` | Formato raro o ffmpeg | `ffmpeg -version`; prueba convertir el audio a mp3/wav |
| Reparar transcripcion/coherencia dice "no se pudo conectar al servidor de IA" | `LOCAL_AI_ENABLED` no esta en `False` | Pon `LOCAL_AI_ENABLED=False` y reinicia `sima-web` |
| Recordatorios no llegan | Backend de consola o SMTP mal configurado | Con `console` los correos solo salen en `journalctl -u sima-reminders`. Para SMTP revisa `EMAIL_*` y prueba `manage.py send_study_reminders --dry-run`. Muchos VPS bloquean el puerto 25: usa 587 |
| certbot falla (`Timeout during connect` / `NXDOMAIN`) | DNS aun no apunta o puerto 80 cerrado | `nslookup DOMINIO`, `sudo ufw status`, firewall del panel del proveedor |
| Cambie `.env` y no pasa nada | Los procesos leen `.env` al arrancar | `sudo systemctl restart sima-web sima-worker` |
| Una variable en `.env` "no toma" su valor | Comentario al final de la linea | Mueve el `# comentario` a su propia linea |

## 14. Paso a la arquitectura objetivo en Azure

Este VPS es provisional. La produccion oficial va en Azure, tal como aparece en los
diagramas de arquitectura fisica y de despliegue. Cada pieza del entorno provisional tiene su equivalente:

| Pieza en el VPS provisional | Equivalente en Azure (arquitectura objetivo) |
|---|---|
| VPS Ubuntu 24.04/22.04, 2 vCPU / 4 GB | Azure VM Ubuntu 22.04 LTS, tamano B2s (2 vCPU / 4 GB) o similar (B2ms con 8 GB si se usa Whisper `small`) |
| PostgreSQL local en el mismo servidor | Azure Database for PostgreSQL - Flexible Server con acceso privado (integracion con VNet, subred delegada, sin IP publica) |
| UFW (22/80/443) | Network Security Group (NSG) en la subred/NIC de la VM **mas** UFW dentro de la VM; SSH limitado a tu IP o via Azure Bastion |
| Let's Encrypt con certbot en Nginx | Igual (certbot en la VM), o certificado en Azure Application Gateway si se pone delante |
| `media/` en el disco del servidor | Disco de la VM (igual que hoy) u, opcionalmente, Azure Blob Storage |
| Secretos en `/srv/sima/app/.env` | `.env` en la VM (igual que hoy) u, opcionalmente, Azure Key Vault con identidad administrada |
| `journalctl` y `logs/sima.log` | Igual en la VM, u opcionalmente Azure Monitor (agente AMA + Log Analytics) |
| `backup_db.sh` + cron | Copias de seguridad automaticas del Flexible Server (retencion configurable, restauracion a un punto en el tiempo) |
| DuckDNS / registro `A` a la IP del VPS | IP publica estatica de la VM (o etiqueta DNS `*.cloudapp.azure.com`) y registro `A` en tu dominio o Azure DNS |

**Que se reutiliza sin cambios en la Azure VM:** `bootstrap_vps.sh`, las unidades de
`deploy/systemd/`, `deploy/nginx/sima.conf` y `update.sh` funcionan igual en una Azure VM
Ubuntu 22.04 (mismo usuario `sima`, mismas rutas `/srv/sima`, mismo Nginx + Gunicorn + Django).

**Lo unico que cambia al usar la base administrada es la conexion en `.env`:** se define
`DATABASE_URL` (tiene prioridad sobre las `POSTGRES_*`) con `sslmode=require`, que Azure exige:

```bash
sudo -u sima nano /srv/sima/app/.env
```

```text
DATABASE_URL=postgresql://sima_admin:CAMBIAR_CONTRASENA_PG@sima-pg.postgres.database.azure.com:5432/sima?sslmode=require
```

- `sima/settings.py` pasa los parametros de la URL (`?sslmode=require`) a `OPTIONS` de la conexion.
- Usa una contrasena **solo con letras mayusculas, minusculas, numeros, `-` y `_`** (Azure la
  acepta y es igual de fuerte si es larga, p. ej. `openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32`).
  `settings.py` no decodifica `%40` y similares en la URL, asi que simbolos como `@ : / # ?` rompen la conexion.
- Crea la base `sima` en el Flexible Server (portal o `az postgres flexible-server db create`)
  y deja que `manage.py migrate` cree las tablas.
- Detalles a tener en cuenta: el bootstrap igual instala un PostgreSQL local, que con
  `DATABASE_URL` queda sin uso (puedes desactivarlo con `sudo systemctl disable --now postgresql`),
  y `backup_db.sh` respalda solo la base local, asi que en Azure se reemplaza por las copias
  automaticas del Flexible Server. Para llevar los datos del VPS a Azure usa `pg_dump -Fc`
  en el VPS y `pg_restore --no-owner -h sima-pg.postgres.database.azure.com -U sima_admin -d sima`
  desde la VM de Azure (seccion 10, cambiando el destino).

---

### Anexo: cambios de codigo hechos para produccion

- `sima/settings.py`
  - `STATIC_ROOT` (por defecto `BASE_DIR / "staticfiles"`, cambiable con `DJANGO_STATIC_ROOT`): sin el, `collectstatic` no funciona y Nginx no tiene que servir.
  - `DJANGO_ALLOWED_HOSTS` ahora ignora espacios y entradas vacias (`"a.pe, 127.0.0.1"` ya no rompe).
  - `SIMA_ENV_FILE` (opcional): elige otro archivo de entorno en vez de `.env`. Por defecto no cambia nada; sirve para correr `check --deploy` con valores de produccion sin tocar el `.env` real.
  - `LOCAL_AI_ENABLED` (agregado en paralelo): con `False`, las etapas que pedian el modelo local usan la nube.
- `requirements.txt`: `gunicorn>=23.0; sys_platform != "win32"`.
- `.gitignore`: ya ignoraba `staticfiles/`, `.env` y `media/`.
