@echo off
if not defined SIMA_PUBLIC_HOST set "SIMA_PUBLIC_HOST=TU-HOST-PUBLICO"
setlocal

cd /d "%~dp0proxy-mini"

echo Iniciando proxy en http://0.0.0.0:25564/
echo Publico esperado: http://%SIMA_PUBLIC_HOST%:25564/
echo Reenvio local: 127.0.0.1:8002
node server.js

echo.
echo [INFO] Proxy se detuvo.
pause
