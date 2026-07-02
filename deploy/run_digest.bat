@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0_win_utf8.bat"
if not exist logs mkdir logs
set LOG=logs\digest.log
if not exist .venv\Scripts\python.exe (
    echo missing .venv\Scripts\python.exe>>%LOG%
    exit /b 1
)
.venv\Scripts\python.exe -c "from src.utils.log_setup import log_job_banner; log_job_banner('digest start', r'%LOG%')"
.venv\Scripts\python.exe -m src.jobs.digest --log-file %LOG%
if errorlevel 1 (
    .venv\Scripts\python.exe -c "from src.utils.log_setup import append_log_line; append_log_line('digest failed', r'%LOG%')"
    exit /b 1
)
.venv\Scripts\python.exe -c "from src.utils.log_setup import log_job_banner; log_job_banner('digest end', r'%LOG%')"
