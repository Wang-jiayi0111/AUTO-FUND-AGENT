@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0_win_utf8.bat"
if not exist logs mkdir logs
call .venv\Scripts\activate.bat
python -m src.jobs.digest --log-file logs\digest.log
