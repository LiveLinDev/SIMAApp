@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "DJANGO_PORT=8002"
set "PROXY_PORT=25564"
set "DJANGO_URL=http://127.0.0.1:%DJANGO_PORT%/"
set "PROXY_URL=http://127.0.0.1:%PROXY_PORT%/"

echo.
echo SIMA public starter
echo ===================
echo.

for %%F in (start-postgres.bat start-django.bat start-proxy.bat) do (
    if not exist "%ROOT%%%F" (
        echo [ERROR] No se encontro %%F
        pause
        exit /b 1
    )
)

echo [0/4] Cerrando procesos anteriores en %DJANGO_PORT% y %PROXY_PORT%...
call :stop_port %PROXY_PORT%
call :stop_port %DJANGO_PORT%

echo.
echo [1/4] Iniciando PostgreSQL...
call "%ROOT%start-postgres.bat"
if errorlevel 1 (
    echo [ERROR] PostgreSQL no pudo iniciarse. Abortando.
    pause
    exit /b 1
)

echo.
echo [2/4] Iniciando Django en 0.0.0.0:%DJANGO_PORT%...
start "SIMA Django :%DJANGO_PORT%" /D "%ROOT%" cmd /c ""%ROOT%start-django.bat""

echo [INFO] Esperando a que Django responda en %DJANGO_URL%...
call :wait_url "%DJANGO_URL%" 45
if errorlevel 1 (
    echo [ERROR] Django no respondio en %DJANGO_URL%.
    echo Revisa la ventana "SIMA Django :%DJANGO_PORT%" o los errores de migracion.
    pause
    exit /b 1
)
echo [OK] Django listo.

echo.
echo [3/4] Iniciando proxy publico en 0.0.0.0:%PROXY_PORT%...
start "SIMA Proxy :%PROXY_PORT%" /D "%ROOT%proxy-mini" cmd /c ""%ROOT%start-proxy.bat""

echo [INFO] Esperando a que el proxy responda en %PROXY_URL%...
call :wait_url "%PROXY_URL%" 20
if errorlevel 1 (
    echo [ERROR] El proxy no respondio en %PROXY_URL%.
    echo Revisa la ventana "SIMA Proxy :%PROXY_PORT%".
    pause
    exit /b 1
)
echo [OK] Proxy listo.

echo.
echo [4/4] SIMA esta arriba.
echo Local : %DJANGO_URL%
echo Proxy : %PROXY_URL%
echo Publico esperado: http://bellamama.duckdns.org:%PROXY_PORT%/
echo.
echo Puedes cerrar esta ventana. Deja abiertas las ventanas de Django y Proxy.
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
