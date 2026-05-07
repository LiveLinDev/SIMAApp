@echo off
setlocal

set "ROOT=%~dp0"

if not exist "%ROOT%start-django.bat" (
  echo [ERROR] No se encontro start-django.bat
  pause
  exit /b 1
)

if not exist "%ROOT%start-proxy.bat" (
  echo [ERROR] No se encontro start-proxy.bat
  pause
  exit /b 1
)

start "SIMA Django" "%ROOT%start-django.bat"
start "SIMA Proxy" "%ROOT%start-proxy.bat"

echo Django: http://127.0.0.1:8002/
echo Proxy : http://127.0.0.1:25564/
echo.
echo Puedes cerrar esta ventana. Deja abiertas las ventanas de Django y Proxy.
pause
