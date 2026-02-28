@echo off
REM Script to start the Coinmaker bot with Docker Compose (Windows)

echo ==========================================
echo   Starting Coinmaker Trading Bot
echo ==========================================

REM Check if .env exists
if not exist .env (
    echo ERROR: .env file not found!
    echo Please create .env from .env.example and configure your API keys
    pause
    exit /b 1
)

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not running!
    echo Please start Docker Desktop and try again
    pause
    exit /b 1
)

REM Create directories if they don't exist
if not exist logs mkdir logs
if not exist data mkdir data

REM Build Docker image
echo.
echo Building Docker image...
docker-compose build

REM Start the bot
echo.
echo Starting bot container...
docker-compose up -d

REM Show status
echo.
docker-compose ps

REM Show logs
echo.
echo ==========================================
echo Bot started successfully!
echo ==========================================
echo.
echo Commands:
echo   View logs:     docker-compose logs -f
echo   Stop bot:      docker-stop.bat
echo   Restart bot:   docker-restart.bat
echo   View status:   docker-compose ps
echo.
echo Following logs (Ctrl+C to exit, bot keeps running)...
echo.

docker-compose logs -f
