@echo off
setlocal
cd /d "%~dp0proxy-mini"
echo Iniciando proxy en http://127.0.0.1:25564/
npm run dev
pause
