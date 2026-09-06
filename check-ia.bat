@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ============================================
echo  SIMA - diagnostico del proveedor de IA
echo  (lee .env, hace un ping y genera items .mini de prueba)
echo ============================================
echo.
python manage.py check_ai --ping --mini
echo.
if errorlevel 1 (
    echo [ERROR] Revisa los puntos marcados con [XX] y vuelve a intentar.
) else (
    echo [OK] Puedes arrancar SIMA con INICIAR_SIMA.bat o start-django.bat
)
echo.
pause
