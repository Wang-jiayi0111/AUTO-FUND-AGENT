@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0_win_utf8.bat"
if not exist logs mkdir logs
call .venv\Scripts\activate.bat
set LOG=logs\daily.log
python -c "from src.utils.log_setup import log_job_banner; log_job_banner('start', r'%LOG%')"
python -m src.jobs.poll --limit 1 --log-file %LOG%
if errorlevel 1 (
    python -c "from src.utils.log_setup import append_log_line; append_log_line('poll failed, skip digest', r'%LOG%')"
    exit /b 1
)
python -m src.jobs.digest --log-file %LOG%
python -c "from src.utils.log_setup import log_job_banner; log_job_banner('end', r'%LOG%')"
