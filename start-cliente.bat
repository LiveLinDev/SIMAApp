@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "DJANGO_PORT=8002"
set "PROXY_PORT=25564"
set "DJANGO_URL=http://127.0.0.1:%DJANGO_PORT%/"
set "PROXY_URL=http://127.0.0.1:%PROXY_PORT%/"

:: Precalcular rutas con parentesis para evitar errores de sintaxis en batch
set "PF=%ProgramFiles%"
set "PF86=%ProgramFiles(x86)%"
set "LAD=%LOCALAPPDATA%"
set "UPL=%USERPROFILE%\AppData\Local"

:: =============================================================================
:: MODO CLIENTE REMOTO
:: =============================================================================
:: Conecta a PostgreSQL, Whisper (via API local remota) y Qwen expuestos por
:: la PC host (bellamama.duckdns.org). No necesitas Postgres ni modelos IA
:: locales; solo Python, Node y las credenciales del .env del proyecto.
:: =============================================================================

:: --- FORZAR conexion remota a PostgreSQL del host ---------------------------
set "POSTGRES_HOST=bellamama.duckdns.org"
set "POSTGRES_PORT=5432"

:: --- FORZAR conexion a la API local (Qwen / llama-server) del host ----------
set "LOCAL_API_BASE=http://bellamama.duckdns.org:8001/v1"

:: Asegurar que SIMA_PC no fuerce otra logica de red (opcional pero seguro)
set "SIMA_PC=cliente"

echo.
echo SIMA Cliente Remoto
echo ===================
echo.

:: =============================================================================
:: AUTO-DETECCION DE PYTHON
:: =============================================================================
echo [INFO] Buscando Python instalado...

:: 1) Revisar si esta en el PATH actual
for /f "delims=" %%i in ('where python.exe 2^>nul') do (
    set "PYTHON=%%i"
    goto :python_validate
)

:: 2) Revisar ubicaciones comunes de instalacion (usuario y sistema)
for /f "delims=" %%D in ('dir /b /ad "%LAD%\Programs\Python\Python*" 2^>nul') do (
    if exist "%LAD%\Programs\Python\%%D\python.exe" (
        set "PYTHON=%LAD%\Programs\Python\%%D\python.exe"
        goto :python_validate
    )
)
for /f "delims=" %%D in ('dir /b /ad "%UPL%\Programs\Python\Python*" 2^>nul') do (
    if exist "%UPL%\Programs\Python\%%D\python.exe" (
        set "PYTHON=%UPL%\Programs\Python\%%D\python.exe"
        goto :python_validate
    )
)
for /f "delims=" %%D in ('dir /b /ad "%PF%\Python*" 2^>nul') do (
    if exist "%PF%\%%D\python.exe" (
        set "PYTHON=%PF%\%%D\python.exe"
        goto :python_validate
    )
)
for /f "delims=" %%D in ('dir /b /ad "%PF86%\Python*" 2^>nul') do (
    if exist "%PF86%\%%D\python.exe" (
        set "PYTHON=%PF86%\%%D\python.exe"
        goto :python_validate
    )
)

echo [ERROR] No se encontro python.exe en PATH ni en las rutas comunes.
echo Instala Python desde https://python.org o agregalo al PATH.
pause
exit /b 1

:python_validate
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Se encontro python.exe pero no responde (puede ser el stub de Microsoft Store).
    echo Instala Python desde python.org y asegurate de que "python --version" funcione en CMD.
    pause
    exit /b 1
)
echo [OK] Python detectado: %PYTHON%

:: =============================================================================
:: AUTO-DETECCION DE NODE.JS
:: =============================================================================
echo [INFO] Buscando Node.js instalado...

:: 1) Revisar si esta en el PATH actual
for /f "delims=" %%i in ('where node.exe 2^>nul') do (
    set "NODE=%%i"
    goto :node_validate
)

:: 2) Revisar ubicaciones comunes de instalacion
if exist "%PF%\nodejs\node.exe" (
    set "NODE=%PF%\nodejs\node.exe"
    goto :node_validate
)
if exist "%PF86%\nodejs\node.exe" (
    set "NODE=%PF86%\nodejs\node.exe"
    goto :node_validate
)
if exist "%LAD%\Programs\nodejs\node.exe" (
    set "NODE=%LAD%\Programs\nodejs\node.exe"
    goto :node_validate
)
if exist "%APPDATA%\npm\node.exe" (
    set "NODE=%APPDATA%\npm\node.exe"
    goto :node_validate
)

echo [ERROR] No se encontro node.exe en PATH ni en las rutas comunes.
echo Instala Node.js desde https://nodejs.org o agregalo al PATH.
pause
exit /b 1

:node_validate
"%NODE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Se encontro node.exe pero no responde.
    pause
    exit /b 1
)
echo [OK] Node.js detectado: %NODE%
echo.

:: =============================================================================
:: VALIDAR DEPENDENCIAS DE PYTHON
:: =============================================================================
echo [INFO] Verificando dependencias de Python (Django, psycopg, openai, whisper)...
"%PYTHON%" -c "import django, psycopg, openai, whisper" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Faltan librerias de Python necesarias.
    echo.
    echo Solucion rapida: ejecuta esto en CMD dentro de esta carpeta:
    echo.
    echo    "%PYTHON%" -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo [OK] Dependencias de Python verificadas.

:: =============================================================================
:: VALIDAR ARCHIVOS NECESARIOS
:: =============================================================================
if not exist "%ROOT%manage.py" (
    echo [ERROR] No se encontro manage.py en %ROOT%
    pause
    exit /b 1
)
if not exist "%ROOT%proxy-mini\server.js" (
    echo [ERROR] No se encontro proxy-mini\server.js en %ROOT%
    pause
    exit /b 1
)
if not exist "%ROOT%proxy-mini\node_modules" (
    echo.
    echo [ERROR] Faltan dependencias de Node en proxy-mini.
    echo.
    echo Solucion rapida: ejecuta esto en CMD dentro de esta carpeta:
    echo.
    echo    cd proxy-mini ^&^& "%NODE%" npm install
    echo.
    pause
    exit /b 1
)

echo.
echo Base de datos remota: %POSTGRES_HOST%:%POSTGRES_PORT%
echo API IA remota       : %LOCAL_API_BASE%
echo.

:: =============================================================================
:: CERRAR PROCESOS ANTERIORES
:: =============================================================================
echo [0/4] Cerrando procesos anteriores en %DJANGO_PORT% y %PROXY_PORT%...
call :stop_port %PROXY_PORT%
call :stop_port %DJANGO_PORT%

:: =============================================================================
:: VALIDAR CONEXION A POSTGRESQL REMOTO (rapido, 10 seg max)
:: =============================================================================
echo [1/4] Probando conexion a PostgreSQL remoto...
"%PYTHON%" -c "import os,sys,psycopg; h=os.environ['POSTGRES_HOST']; pt=os.environ['POSTGRES_PORT']; db=os.environ.get('POSTGRES_DB','simaapp'); u=os.environ.get('POSTGRES_USER','simaapp'); pw=os.environ.get('POSTGRES_PASSWORD',''); conn=psycopg.connect(host=h,port=pt,dbname=db,user=u,password=pw,connect_timeout=10); cur=conn.cursor(); cur.execute('SELECT 1'); cur.fetchone(); conn.close(); print('OK')" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudo conectar a PostgreSQL remoto (%POSTGRES_HOST%:%POSTGRES_PORT%).
    echo.
    echo Causas mas comunes:
    echo  1. Tu .env no tiene las credenciales correctas (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB).
    echo  2. El host no tiene PostgreSQL escuchando conexiones externas.
    echo  3. El router/firewall del host no tiene abierto el puerto 5432.
    echo.
    pause
    exit /b 1
)
echo [OK] PostgreSQL remoto responde.

:: =============================================================================
:: INICIAR DJANGO
:: =============================================================================
echo.
echo [2/4] Iniciando Django en 0.0.0.0:%DJANGO_PORT% (modo remoto)...
start "SIMA Cliente Django :%DJANGO_PORT%" /D "%ROOT%" cmd /c "echo [INFO] Aplicando migraciones... ^&^& "%PYTHON%" manage.py migrate --run-syncdb ^|^| (echo. ^&^& echo [ERROR] Las migraciones fallaron. Revisa la conexion a la DB remota. ^&^& pause ^&^& exit /b 1) ^&^& echo. ^&^& echo [INFO] Django listo. Iniciando servidor... ^&^& "%PYTHON%" manage.py runserver 0.0.0.0:%DJANGO_PORT% ^&^& echo. ^&^& echo [INFO] Django se detuvo. ^&^& pause"

echo [INFO] Esperando a que Django responda en %DJANGO_URL%...
call :wait_url "%DJANGO_URL%" 90 "Django"
if errorlevel 1 (
    echo.
    :: Diagnosticar: revisar si el puerto esta ocupado
    netstat -ano | findstr /R /C:":%DJANGO_PORT% .*LISTENING" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Django no arranco. La ventana se cerro o fallo antes de escuchar en el puerto.
        echo.
        echo Causas mas comunes:
        echo  - Error de conexion a PostgreSQL (revisa la ventana SIMA Cliente Django).
        echo  - Faltan variables en el .env (POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB).
        echo  - Python no tiene instaladas las dependencias.
        echo.
        echo Si la ventana de Django se abrio y se cerro muy rapido, ejecuta manualmente:
        echo    "%PYTHON%" manage.py migrate --run-syncdb
        echo    "%PYTHON%" manage.py runserver 0.0.0.0:%DJANGO_PORT%
        echo.
    ) else (
        echo [ERROR] Django esta escuchando en el puerto %DJANGO_PORT% pero no responde HTTP.
        echo Puede estar atorado en migraciones lentas o hay un error interno.
    )
    pause
    exit /b 1
)

:: =============================================================================
:: INICIAR PROXY
:: =============================================================================
echo.
echo [3/4] Iniciando proxy publico en 0.0.0.0:%PROXY_PORT%...
start "SIMA Cliente Proxy :%PROXY_PORT%" /D "%ROOT%proxy-mini" cmd /c "echo [INFO] Iniciando proxy en http://0.0.0.0:%PROXY_PORT%/... ^&^& echo Publico esperado: http://bellamama.duckdns.org:%PROXY_PORT%/... ^&^& echo Reenvio local: 127.0.0.1:%DJANGO_PORT%... ^&^& "%NODE%" server.js ^&^& echo. ^&^& echo [INFO] Proxy se detuvo. ^&^& pause"

echo [INFO] Esperando a que el proxy responda en %PROXY_URL%...
call :wait_url "%PROXY_URL%" 20 "Proxy"
if errorlevel 1 (
    echo.
    netstat -ano | findstr /R /C:":%PROXY_PORT% .*LISTENING" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] El proxy no arranco. Revisa la ventana SIMA Cliente Proxy.
    ) else (
        echo [ERROR] El proxy esta escuchando pero no responde HTTP.
    )
    pause
    exit /b 1
)

:: =============================================================================
:: RESUMEN
:: =============================================================================
echo.
echo [4/4] SIMA Cliente esta arriba.
echo Local : %DJANGO_URL%
echo Proxy : %PROXY_URL%
echo Publico esperado: http://bellamama.duckdns.org:%PROXY_PORT%/
echo.
echo Asegurate de que tu .env local tenga las credenciales correctas de PostgreSQL.
echo Puedes cerrar esta ventana. Deja abiertas las ventanas de Django y Proxy.
pause
exit /b 0

:: =============================================================================
:: SUBRUTINAS
:: =============================================================================
:stop_port
set "PORT_TO_STOP=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT_TO_STOP% .*LISTENING"') do (
    echo [INFO] Cerrando PID %%P que usa el puerto %PORT_TO_STOP%...
    taskkill /F /PID %%P >nul 2>&1
)
exit /b 0

:wait_url
set "URL_TO_WAIT=%~1"
set "TRIES=%~2"
set "NAME=%~3"
echo|set /p="[INFO] Esperando a %NAME% "
for /L %%I in (1,1,%TRIES%) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL_TO_WAIT%'; if ($r.StatusCode -lt 500) { exit 0 } exit 1 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo.
        echo [OK] %NAME% listo.
        exit /b 0
    )
    set /a "MOD=%%I %% 5"
    if "!MOD!"=="0" echo|set /p="."
    timeout /t 1 /nobreak >nul
)
echo.
exit /b 1
