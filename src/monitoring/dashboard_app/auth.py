"""
Modulo di autenticazione per le pagine sensibili della dashboard.
"""
import os
import streamlit as st


def require_auth() -> bool:
    """
    Ritorna True se l'utente è autenticato.
    Se non lo è, mostra il campo di input per la password e ritorna False.
    """
    if st.session_state.get("auth_ok", False):
        return True

    password = os.environ.get("DASHBOARD_ADMIN_PASSWORD")
    if not password:
        st.error("Configurazione di sicurezza mancante. La pagina è bloccata.")
        st.caption("Aggiungi DASHBOARD_ADMIN_PASSWORD al file .env e riavvia.")
        return False

    st.warning("🔒 Pagina protetta. Inserisci la password per procedere.")
    pwd_input = st.text_input("Password Amministratore", type="password")

    if st.button("Sblocca"):
        if pwd_input == password:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Password errata.")

    return False
