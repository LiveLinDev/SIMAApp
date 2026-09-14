@echo off
rem =============================================================================
rem SIMA - la PC transcribe el audio para el VPS.
rem 1) Levanta el servicio de Whisper en 127.0.0.1:9000 (manage.py serve_whisper).
rem 2) Abre el tunel SSH inverso: el VPS llega a este servicio en su 127.0.0.1:9000.
rem Requisitos en .env: WHISPER_REMOTE_TOKEN (igual que en el VPS), SIMA_VPS_HOST (IP o dominio del VPS)
rem y opcional SIMA_VPS_SSH_PORT (por defecto 22).
rem La clave del tunel es %USERPROFILE%\.ssh\sima_tunnel_ed25519 (autorizada en el usuario sima-tunnel).
rem Cierra esta ventana para cortar el tunel. El servicio sigue en su propia ventana.
rem =============================================================================
setlocal
cd /d "%~dp0"

set "VPS_HOST="
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"SIMA_VPS_HOST=" .env`) do set "VPS_HOST=%%b"
if "%VPS_HOST%"=="" (
    echo [ERROR] Falta SIMA_VPS_HOST en .env ^(IP o dominio del VPS^).
    pause
    exit /b 1
)
set "VPS_PORT=22"
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b /c:"SIMA_VPS_SSH_PORT=" .env`) do set "VPS_PORT=%%b"
set "TUNNEL_KEY=%USERPROFILE%\.ssh\sima_tunnel_ed25519"
if not exist "%TUNNEL_KEY%" (
    echo [ERROR] No existe la clave del tunel: %TUNNEL_KEY%
    pause
    exit /b 1
)

echo Iniciando el servicio de transcripcion en otra ventana...
start "SIMA - Whisper para el VPS" cmd /k python manage.py serve_whisper --port 9000

echo Abriendo el tunel hacia %VPS_HOST%:%VPS_PORT% (se reintenta solo si se cae)...
:loop
ssh -i "%TUNNEL_KEY%" -p %VPS_PORT% -N ^
    -o ExitOnForwardFailure=yes ^
    -o ServerAliveInterval=30 ^
    -o ServerAliveCountMax=3 ^
    -o StrictHostKeyChecking=accept-new ^
    -R 127.0.0.1:9000:127.0.0.1:9000 sima-tunnel@%VPS_HOST%
echo [%time%] Tunel caido. Reintentando en 10 segundos... (Ctrl+C para salir)
timeout /t 10 /nobreak >nul
goto loop
