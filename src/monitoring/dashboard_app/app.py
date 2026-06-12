"""
Entry point della dashboard multipagina.

Avvio: streamlit run scripts/run_dashboard.py
"""
from datetime import datetime, timezone

import streamlit as st


def main():
    st.set_page_config(
        page_title="CoinMaker Quant — Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    pages = {
        "Trade in corso": "live",
        "Rischio & Esposizione": "risk",
        "Storico Operazioni": "history",
        "Contesto Mercato": "context",
        "Impostazioni": "settings",
        "Azioni": "actions",
    }
    with st.sidebar:
        st.title("CoinMaker Quant")
        choice = st.radio("Pagina", list(pages.keys()))
        st.caption(
            f"UTC {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} — "
            "dashboard in sola lettura, processo separato dal bot"
        )

    if pages[choice] == "live":
        from src.monitoring.dashboard_app import page_live
        page_live.render()
    elif pages[choice] == "risk":
        from src.monitoring.dashboard_app import page_risk
        page_risk.render()
    elif pages[choice] == "context":
        from src.monitoring.dashboard_app import page_context
        page_context.render()
    elif pages[choice] == "settings":
        from src.monitoring.dashboard_app import page_settings
        page_settings.render()
    elif pages[choice] == "actions":
        from src.monitoring.dashboard_app import page_actions
        page_actions.render()
    else:
        from src.monitoring.dashboard_app import page_history
        page_history.render()


if __name__ == "__main__":
    main()
