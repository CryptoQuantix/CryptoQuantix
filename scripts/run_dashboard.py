"""
Launcher dashboard Streamlit (processo separato dal bot).

Avvio:
    streamlit run scripts/run_dashboard.py
oppure:
    scripts\\run_dashboard.bat
"""
import os
import sys

# Repo root nel path per gli import src.*
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)  # percorsi relativi (data/journal.db, .env) dal repo root

from src.monitoring.dashboard_app.app import main  # noqa: E402

main()
