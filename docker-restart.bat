@echo off
REM Script to restart the bot (Windows)

echo ==========================================
echo   Restarting Coinmaker Trading Bot
echo ==========================================

docker-compose restart

echo.
echo Bot restarted successfully!
echo.
echo View logs: docker-logs.bat
pause
