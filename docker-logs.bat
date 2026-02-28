@echo off
REM Script to view bot logs (Windows)

echo ==========================================
echo   Coinmaker Bot Logs
echo ==========================================
echo Press Ctrl+C to exit (bot keeps running)
echo.

docker-compose logs -f coinmaker-bot
