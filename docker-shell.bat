@echo off
REM Script to open a shell inside the bot container (Windows)

echo ==========================================
echo   Opening shell in bot container
echo ==========================================
echo.

docker-compose ps | findstr "coinmaker-bot.*Up" >nul
if errorlevel 1 (
    echo ERROR: Bot container is not running!
    echo Start it first with: docker-start.bat
    pause
    exit /b 1
)

docker-compose exec coinmaker-bot /bin/bash
