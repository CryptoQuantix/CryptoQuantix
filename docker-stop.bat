@echo off
REM Script to stop the CryptoQuantix bot (Windows)

echo ==========================================
echo   Stopping CryptoQuantix Trading Bot
echo ==========================================

docker-compose stop

echo.
echo Bot stopped successfully!
echo.
echo To start again: docker-start.bat
echo To remove container: docker-compose down
pause
