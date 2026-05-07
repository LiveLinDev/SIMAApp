@echo off
setlocal
cd /d "%~dp0"
echo Iniciando Django en http://127.0.0.1:8002/
python manage.py runserver 127.0.0.1:8002
pause
