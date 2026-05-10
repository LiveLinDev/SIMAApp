@echo off
setlocal
cd /d "%~dp0"
echo Iniciando Django en http://127.0.0.1:8002/
"C:\Users\Erick\AppData\Local\Python\pythoncore-3.14-64\python.exe" manage.py runserver 127.0.0.1:8002
pause
