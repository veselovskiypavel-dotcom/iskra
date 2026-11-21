@echo off
chcp 65001 >nul
rem Сервер мышления «Искры» — запуск двойным щелчком. Окно не закрывать, пока идёт игра; остановить — Ctrl+C.
cd /d "%~dp0"
python -m uvicorn server:app --reload --port 8000
pause
