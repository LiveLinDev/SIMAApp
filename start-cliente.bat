@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "DJANGO_PORT=8002"
set "PROXY_PORT=25564"
set "DJANGO_URL=http://127.0.0.1:%DJANGO_PORT%/"
set "PROXY_URL=http://127.0.0.1:%PROXY_PORT%/"

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
    goto :python_found
)

:: 2) Revisar ubicaciones comunes de instalacion (usuario y sistema)
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :python_found
    )
)
for /d %%D in ("%ProgramFiles%\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :python_found
    )
)
for /d %%D in ("%ProgramFiles(x86)%\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :python_found
    )
)
for /d %%D in ("%USERPROFILE%\AppData\Local\Programs\Python\Python*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :python_found
    )
)

echo [ERROR] No se encontro python.exe en PATH ni en las rutas comunes.
echo Instala Python desde https://python.org o agregalo al PATH.
pause
exit /b 1

:python_found
echo [OK] Python detectado: %PYTHON%

:: =============================================================================
:: AUTO-DETECCION DE NODE.JS
:: =============================================================================
echo [INFO] Buscando Node.js instalado...

:: 1) Revisar si esta en el PATH actual
for /f "delims=" %%i in ('where node.exe 2^>nul') do (
    set "NODE=%%i"
    goto :node_found
)

:: 2) Revisar ubicaciones comunes de instalacion
if exist "%ProgramFiles%\nodejs\node.exe" (
    set "NODE=%ProgramFiles%\nodejs\node.exe"
    goto :node_found
)
if exist "%ProgramFiles(x86)%\nodejs\node.exe" (
    set "NODE=%ProgramFiles(x86)%\nodejs\node.exe"
    goto :node_found
)
if exist "%LOCALAPPDATA%\Programs\nodejs\node.exe" (
    set "NODE=%LOCALAPPDATA%\Programs\nodejs\node.exe"
    goto :node_found
)
if exist "%APPDATA%\npm\node.exe" (
    set "NODE=%APPDATA%\npm\node.exe"
    goto :node_found
)

echo [ERROR] No se encontro node.exe en PATH ni en las rutas comunes.
echo Instala Node.js desde https://nodejs.org o agregalo al PATH.
pause
exit /b 1

:node_found
echo [OK] Node.js detectado: %NODE%
echo.

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

echo Base de datos remota: %POSTGRES_HOST%:%POSTGRES_PORT%
echo API IA remota       : %LOCAL_API_BASE%
echo.

:: =============================================================================
:: CERRAR PROCESOS ANTERIORES
:: =============================================================================
echo [0/3] Cerrando procesos anteriores en %DJANGO_PORT% y %PROXY_PORT%...
call :stop_port %PROXY_PORT%
call :stop_port %DJANGO_PORT%

:: =============================================================================
:: INICIAR DJANGO (directamente con la ruta de Python detectada)
:: =============================================================================
echo.
echo [1/3] Iniciando Django en 0.0.0.0:%DJANGO_PORT% (modo remoto)...
start "SIMA Cliente Django :%DJANGO_PORT%" cmd /c "cd /d "%ROOT%" ^&^& echo Aplicando migraciones... ^&^& "%PYTHON%" manage.py migrate --run-syncdb ^&^& if errorlevel 1 ( echo. ^&^& echo [ERROR] No se pudieron aplicar migraciones. ^&^& pause ^&^& exit /b 1 ) ^&^& echo. ^&^& echo Iniciando Django en http://0.0.0.0:%DJANGO_PORT%/ ^&^& echo Acceso local:  http://127.0.0.1:%DJANGO_PORT%/ ^&^& echo Via proxy:     http://bellamama.duckdns.org:%PROXY_PORT%/ ^&^& "%PYTHON%" manage.py runserver 0.0.0.0:%DJANGO_PORT% ^&^& echo. ^&^& echo [INFO] Django se detuvo. ^&^& pause"

echo [INFO] Esperando a que Django responda en %DJANGO_URL%...
call :wait_url "%DJANGO_URL%" 45
if errorlevel 1 (
    echo [ERROR] Django no respondio en %DJANGO_URL%.
    echo Revisa la ventana "SIMA Cliente Django :%DJANGO_PORT%" o los errores de conexion a la DB remota.
    pause
    exit /b 1
)
echo [OK] Django listo.

:: =============================================================================
:: INICIAR PROXY (directamente con la ruta de Node detectada)
:: =============================================================================
echo.
echo [2/3] Iniciando proxy publico en 0.0.0.0:%PROXY_PORT%...
start "SIMA Cliente Proxy :%PROXY_PORT%" cmd /c "cd /d "%ROOT%proxy-mini" ^&^& echo Iniciando proxy en http://0.0.0.0:%PROXY_PORT%/ ^&^& echo Publico esperado: http://bellamama.duckdns.org:%PROXY_PORT%/ ^&^& echo Reenvio local: 127.0.0.1:%DJANGO_PORT% ^&^& "%NODE%" server.js ^&^& echo. ^&^& echo [INFO] Proxy se detuvo. ^&^& pause"

echo [INFO] Esperando a que el proxy responda en %PROXY_URL%...
call :wait_url "%PROXY_URL%" 20
if errorlevel 1 (
    echo [ERROR] El proxy no respondio en %PROXY_URL%.
    echo Revisa la ventana "SIMA Cliente Proxy :%PROXY_PORT%".
    pause
    exit /b 1
)
echo [OK] Proxy listo.

:: =============================================================================
:: RESUMEN
:: =============================================================================
echo.
echo [3/3] SIMA Cliente esta arriba.
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
for /L %%I in (1,1,%TRIES%) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL_TO_WAIT%'; if ($r.StatusCode -lt 500) { exit 0 } exit 1 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 exit /b 0
    timeout /t 1 /nobreak >nul
)
exit /b 1
