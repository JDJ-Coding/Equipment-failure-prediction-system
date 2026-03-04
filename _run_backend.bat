@echo off
cd /d "%~dp0dashboard\backend"
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
pause
