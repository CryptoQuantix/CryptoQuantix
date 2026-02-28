@echo off
:: Helper script to run dry run scripts with UTF-8 encoding on Windows
set PYTHONIOENCODING=utf-8

if "%1"=="data" (
    echo Running: Data layer dry run...
    python scripts/dry_run_data.py %2 %3 %4
) else if "%1"=="orderflow" (
    echo Running: Orderflow engine dry run...
    python scripts/dry_run_orderflow.py %2 %3 %4
) else if "%1"=="strategies" (
    echo Running: Strategy dry run...
    python scripts/dry_run_strategies.py %2 %3 %4
) else if "%1"=="full" (
    echo Running: Full system dry run...
    python scripts/dry_run_full.py %2 %3 %4
) else (
    echo Usage: run_dry_run.bat [data^|orderflow^|strategies^|full] [options]
    echo.
    echo Examples:
    echo   run_dry_run.bat data --duration 30
    echo   run_dry_run.bat orderflow --duration 60
    echo   run_dry_run.bat strategies --backtest
    echo   run_dry_run.bat full --duration 120
    echo.
    echo Quick start (test without Binance connection):
    echo   run_dry_run.bat strategies
)
