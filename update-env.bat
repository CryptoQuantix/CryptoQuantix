@echo off
REM Script to update .env file with missing Smart Money parameters

echo Updating .env file...

REM Backup current .env
copy .env .env.backup >nul 2>&1

REM Update LOG_LEVEL to DEBUG
powershell -Command "(Get-Content .env) -replace 'LOG_LEVEL=INFO', 'LOG_LEVEL=DEBUG' | Set-Content .env"

REM Add missing parameters if not present
findstr /C:"SM_ABSORPTION_MIN_VOL" .env >nul 2>&1
if errorlevel 1 (
    echo. >> .env
    echo # Smart Money - Order Flow Parameters >> .env
    echo SM_ABSORPTION_MIN_VOL=10.0  # Minimum volume threshold >> .env
    echo SM_ABSORPTION_DELTA_RATIO=0.15  # Delta ratio threshold ^(15%% of total vol^) >> .env
    echo SM_ABSORPTION_PRICE_THRESHOLD=0.01  # Price change threshold ^(1%%^) >> .env
)

findstr /C:"RISK_PER_TRADE_PCT" .env >nul 2>&1
if errorlevel 1 (
    echo. >> .env
    echo # Smart Money - Risk Parameters >> .env
    echo RISK_PER_TRADE_PCT=0.015  # 1.5%% risk per trade >> .env
    echo RISK_REWARD_RATIO=2.5  # Target 2.5:1 risk/reward >> .env
    echo LEVERAGE_MAX=5  # Maximum leverage >> .env
)

findstr /C:"MONITORING_INTERVAL_MINUTES" .env >nul 2>&1
if errorlevel 1 (
    echo. >> .env
    echo # Monitoring >> .env
    echo MONITORING_INTERVAL_MINUTES=5  # Scan interval in minutes >> .env
)

echo.
echo ✓ .env file updated successfully!
echo ✓ Backup saved as .env.backup
echo.
echo Changes made:
echo   - LOG_LEVEL set to DEBUG
echo   - Added Smart Money absorption parameters
echo   - Added risk management parameters
echo   - Added monitoring interval
echo.
pause
