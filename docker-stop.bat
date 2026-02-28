@echo off
REM Script to stop the Coinmaker bot (Windows)

echo ==========================================
echo   Stopping Coinmaker Trading Bot
echo ==========================================

docker-compose stop

echo.
echo Bot stopped successfully!
echo.
echo To start again: docker-start.bat
echo To remove container: docker-compose down
pause
