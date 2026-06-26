@echo off
REM Start WeWe RSS for local WeChat public account RSS generation
cd /d %~dp0
docker compose -f docker-compose.wewe-rss.yml up -d
echo.
echo WeWe RSS started: http://localhost:4000/dash
echo Next: log in with WeChat Reading, then add public accounts.
pause
