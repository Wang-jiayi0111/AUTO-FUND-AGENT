@echo off
REM Force UTF-8 for Python stdout/stderr and cmd echo when appending to log files.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
