@echo off
setlocal EnableExtensions

set "OLLAMA_HOST=127.0.0.1:8001"
set "MODEL_URL=http://%OLLAMA_HOST%/v1/models"
set "OLLAMA_EXE=ollama.exe"

where /q %OLLAMA_EXE%
if errorlevel 1 (
    echo [ERROR] No se encontro %OLLAMA_EXE% en el PATH.
    echo Instala Ollama desde https://ollama.com o agregalo al PATH.
    pause
    exit /b 1
)

echo.
echo [INFO] Cerrando instancias previas de Ollama...
taskkill /F /IM ollama.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [INFO] Iniciando Ollama en %OLLAMA_HOST%...
start "SIMA Ollama :8001" cmd /c "set OLLAMA_HOST=%OLLAMA_HOST% && ollama serve"

echo [INFO] Esperando que Ollama responda en %MODEL_URL%...
for /L %%I in (1,1,60) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%MODEL_URL%'; if ($r.StatusCode -lt 500) { exit 0 } exit 1 } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 (
        echo [OK] Ollama listo en %MODEL_URL%.
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)

echo [ERROR] Ollama no respondio en %MODEL_URL%.
echo Verifica que Ollama este instalado y que el puerto 8001 este libre.
pause
exit /b 1
