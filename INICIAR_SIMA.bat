@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
set "STARTER=%ROOT%start-everything.bat"

echo.
echo ============================================
echo  INICIAR SIMAApp
echo  ROOT: %ROOT%
echo  STARTER: %STARTER%
echo ============================================
echo.

if not exist "%STARTER%" (
    echo [ERROR] No se encontro el lanzador interno: %STARTER%
    echo [INFO] Verifica que el proyecto SIMAApp este completo.
    echo.
    echo Presiona cualquier tecla para cerrar esta ventana...
    pause >nul
    exit /b 1
)

echo [INFO] Lanzando SIMAApp desde %STARTER%...
call "%STARTER%"
set "EXIT_CODE=%errorlevel%"

echo.
echo ============================================
echo  El lanzador de SIMAApp termino con codigo: %EXIT_CODE%
echo ============================================
echo.

if %EXIT_CODE% neq 0 (
    echo [ERROR] SIMAApp no arranco correctamente. Revisa los mensajes anteriores.
)

echo.
echo Presiona cualquier tecla para cerrar esta ventana...
pause >nul
endlocal
exit /b %EXIT_CODE%
