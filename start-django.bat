@echo off
if not defined SIMA_PUBLIC_HOST set "SIMA_PUBLIC_HOST=TU-HOST-PUBLICO"
setlocal

cd /d "%~dp0"

echo Aplicando migraciones...
python manage.py migrate --run-syncdb
if errorlevel 1 (
    echo.
    echo [ERROR] No se pudieron aplicar migraciones.
    pause
    exit /b 1
)

echo.
echo Iniciando Django en http://0.0.0.0:8002/
echo Acceso local:  http://127.0.0.1:8002/
echo Via proxy:     http://%SIMA_PUBLIC_HOST%:25564/
python manage.py runserver 0.0.0.0:8002

echo.
echo [INFO] Django se detuvo.
pause
