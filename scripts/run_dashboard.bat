@echo off
REM Dashboard Streamlit — processo separato dal bot (sola lettura)
cd /d "%~dp0\.."
python -m streamlit run scripts\run_dashboard.py %*
