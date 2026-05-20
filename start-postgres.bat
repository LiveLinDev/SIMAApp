@echo off
setlocal EnableExtensions

set "PG_SERVICE=postgresql-x64-18"
set "PSQL=C:\Program Files\PostgreSQL\18\bin\psql.exe"
set "PG_PORT=5433"
set "PG_USER=postgres"
set "PGPASSWORD=root"
set "PG_DB=sima_platform"

if not exist "%PSQL%" (
    echo [ERROR] No se encontro psql.exe en "%PSQL%".
    pause
    exit /b 1
)

echo [INFO] Probando PostgreSQL en puerto %PG_PORT%...
"%PSQL%" -U %PG_USER% -p %PG_PORT% -c "SELECT 1;" >nul 2>&1
if not errorlevel 1 (
    echo [OK] PostgreSQL ya responde.
    goto :ensure_db
)

echo [INFO] PostgreSQL no responde todavia. Intentando iniciar servicio %PG_SERVICE%...
net start "%PG_SERVICE%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se pudo iniciar PostgreSQL automaticamente.
    echo Ejecuta start-all.bat como Administrador o inicia el servicio %PG_SERVICE% manualmente.
    pause
    exit /b 1
)

echo [INFO] Esperando que PostgreSQL responda...
for /L %%I in (1,1,30) do (
    timeout /t 1 /nobreak >nul
    "%PSQL%" -U %PG_USER% -p %PG_PORT% -c "SELECT 1;" >nul 2>&1
    if not errorlevel 1 goto :ensure_db
)

echo [ERROR] PostgreSQL no respondio en el puerto %PG_PORT%.
pause
exit /b 1

:ensure_db
"%PSQL%" -U %PG_USER% -p %PG_PORT% -lqt | findstr /i "%PG_DB%" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Creando base de datos %PG_DB%...
    "%PSQL%" -U %PG_USER% -p %PG_PORT% -c "CREATE DATABASE %PG_DB%;"
    if errorlevel 1 (
        echo [ERROR] No se pudo crear la base de datos %PG_DB%.
        pause
        exit /b 1
    )
    echo [OK] Base de datos %PG_DB% creada.
) else (
    echo [OK] Base de datos %PG_DB% ya existe.
)

endlocal
exit /b 0
