"""
Dashboard Streamlit multipagina — processo SEPARATO dal bot.

Legge: journal.db, signal_log.db, state JSON, .env e Deribit via REST
in sola lettura. Non importa mai il bot in esecuzione.

Avvio:  streamlit run scripts/run_dashboard.py
"""
