@echo off
if not defined SIMA_PUBLIC_HOST set "SIMA_PUBLIC_HOST=TU-HOST-PUBLICO"
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "MODEL_PORT=8001"
set "PROXY_IA_PORT=8003"
set "DJANGO_PORT=8002"
set "PROXY_PORT=25564"
set "MODEL_URL=http://127.0.0.1:%MODEL_PORT%/v1/models"
set "PROXY_IA_URL=http://127.0.0.1:%PROXY_IA_PORT%/_proxy/health"
set "DJANGO_URL=http://127.0.0.1:%DJANGO_PORT%/"
set "PROXY_URL=http://127.0.0.1:%PROXY_PORT%/"
set "PUBLIC_URL=http://%SIMA_PUBLIC_HOST%:%PROXY_PORT%/"

echo.
echo SIMA + IA full launcher
echo =======================
echo.

if not exist "%ROOT%start-all.bat" (
    echo [ERROR] No se encontro start-all.bat en %ROOT%
    pause
    exit /b 1
)
if not exist "%ROOT%proxy-8003.js" (
    echo [ERROR] No se encontro proxy-8003.js en %ROOT%
    pause
    exit /b 1
)
if not exist "%ROOT%start-model.bat" (
    echo [ERROR] No se encontro start-model.bat en %ROOT%
    echo.
    echo Copia el archivo de ejemplo y configuralo:
    echo   copy start-model.bat.example start-model.bat
    echo Luego edita start-model.bat con el comando que inicia tu modelo local.
    echo.
    pause
    exit /b 1
)

call :check_env_proxy

echo [0/6] Cerrando procesos anteriores en puertos %MODEL_PORT%, %PROXY_IA_PORT%, %DJANGO_PORT%, %PROXY_PORT%...
call :stop_port %MODEL_PORT%
call :stop_port %PROXY_IA_PORT%
call :stop_port %DJANGO_PORT%
call :stop_port %PROXY_PORT%

echo.
echo [1/6] Iniciando PostgreSQL...
call "%ROOT%start-postgres.bat"
if errorlevel 1 (
    echo [ERROR] PostgreSQL no pudo iniciarse. Abortando.
    pause
    exit /b 1
)

echo.
echo [2/6] Iniciando modelo local de IA en %MODEL_URL%...
start "SIMA Modelo IA :%MODEL_PORT%" /D "%ROOT%" cmd /c ""%ROOT%start-model.bat""
echo [INFO] Esperando que el modelo local responda en %MODEL_URL%...
call :wait_url "%MODEL_URL%" 60
if errorlevel 1 (
    echo [ERROR] El modelo local no respondio en %MODEL_URL%.
    echo Revisa la ventana "SIMA Modelo IA :%MODEL_PORT%" y el comando en start-model.bat.
    pause
    exit /b 1
)
echo [OK] Modelo local listo.

echo.
echo [3/6] Iniciando proxy IA %PROXY_IA_PORT% -
cd /d "%ROOT%"
start "SIMA Proxy IA :%PROXY_IA_PORT%" cmd /c "node proxy-8003.js"
echo [INFO] Esperando que el proxy IA responda en %PROXY_IA_URL%...
call :wait_url "%PROXY_IA_URL%" 20
if errorlevel 1 (
    echo [ERROR] El proxy IA no respondio en %PROXY_IA_URL%.
    echo Revisa la ventana "SIMA Proxy IA :%PROXY_IA_PORT%".
    pause
    exit /b 1
)
echo [OK] Proxy IA listo.

echo.
echo [4/6] Iniciando Django en %DJANGO_URL%...
start "SIMA Django :%DJANGO_PORT%" /D "%ROOT%" cmd /c ""%ROOT%start-django.bat""
echo [INFO] Esperando que Django responda en %DJANGO_URL%...
call :wait_url "%DJANGO_URL%" 45
if errorlevel 1 (
    echo [ERROR] Django no respondio en %DJANGO_URL%.
    echo Revisa la ventana "SIMA Django :%DJANGO_PORT%" o los errores de migracion.
    pause
    exit /b 1
)
echo [OK] Django listo.

echo.
echo [5/6] Iniciando proxy publico en %PROXY_URL%...
start "SIMA Proxy :%PROXY_PORT%" /D "%ROOT%proxy-mini" cmd /c ""%ROOT%start-proxy.bat""
echo [INFO] Esperando que el proxy publico responda en %PROXY_URL%...
call :wait_url "%PROXY_URL%" 20
if errorlevel 1 (
    echo [ERROR] El proxy publico no respondio en %PROXY_URL%.
    echo Revisa la ventana "SIMA Proxy :%PROXY_PORT%".
    pause
    exit /b 1
)
echo [OK] Proxy publico listo.

echo.
echo [6/6] SIMA esta completamente arriba.
echo.
echo  Local (tu PC):  %PROXY_URL%
echo  Publico (red):  %PUBLIC_URL%
echo.
echo Deja abiertas las ventanas del modelo, proxy IA, Django y proxy publico.
echo Cierra esta ventana cuando quieras; los servicios seguiran corriendo.
pause
exit /b 0


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


:check_env_proxy
set "ENV_FILE=%ROOT%.env"
if not exist "%ENV_FILE%" exit /b 0
for /f "usebackq tokens=1* delims==" %%A in ("%ENV_FILE%") do (
    if /i "%%A"=="LOCAL_API_BASE" (
        set "BASE_VALUE=%%B"
        echo !BASE_VALUE! | findstr /i ":8003" >nul
        if errorlevel 1 (
            echo.
            echo [ADVERTENCIA] LOCAL_API_BASE en .env apunta a "!BASE_VALUE!" y no al proxy 8003.
            echo Para que SIMA use proxy-8003.js cambia .env a:
            echo   LOCAL_API_BASE=http://127.0.0.1:8003/v1
            echo.
            echo Se continuara de todos modos, pero las llamadas a IA podrian fallar.
            echo.
            pause
        )
    )
)
exit /b 0
