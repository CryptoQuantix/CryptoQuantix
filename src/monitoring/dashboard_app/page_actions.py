"""
Pagina "Azioni" — controlli operativi dietro conferma doppia (Fase 4).

1. Kill switch manuale (flag file -> il RiskManager blocca i nuovi ingressi)
2. Chiusura manuale di una posizione (market reduce-only, type-to-confirm)
3. Pulizia ordini orfani on-demand (stessa definizione del PositionMonitor)

Ogni azione scrive l'audit log (logs/dashboard_actions.log): chi/cosa/quando.
"""
import pandas as pd
import streamlit as st

from src.core import flags
from src.monitoring.dashboard_app import data_access as da
from src.monitoring.dashboard_app.audit import audit, read_audit


def render():
    st.header("Azioni operative")
    st.caption(
        "Tutte le azioni richiedono conferma doppia e finiscono nell'audit "
        "log. Il kill switch passa da flag file (il bot lo onora ai gate di "
        "ingresso); chiusure e pulizia orfani vanno DIRETTAMENTE sul venue."
    )

    _render_kill_switch()
    st.divider()

    live = da.fetch_live_state()
    if not live["ok"]:
        st.error(f"Venue non raggiungibile: {live['error']} — chiusure e "
                 "pulizia orfani non disponibili.")
    else:
        _render_manual_close(live)
        st.divider()
        _render_orphan_cleanup(live)

    st.divider()
    _render_audit_trail()


# ----------------------------------------------------------------------
# 1. Kill switch manuale
# ----------------------------------------------------------------------

def _render_kill_switch():
    st.subheader("Kill switch manuale")
    active = flags.flag_active(flags.KILL_SWITCH_FLAG)

    if active:
        info = flags.flag_info(flags.KILL_SWITCH_FLAG) or {}
        st.error(
            f"KILL SWITCH MANUALE ATTIVO dal {info.get('created_utc', '?')} — "
            f"motivo: {info.get('reason', '?')}. Il bot rifiuta ogni nuovo "
            "ingresso; le posizioni aperte restano gestite (SL/TP/time exit)."
        )
        ok = st.checkbox("Confermo la RIATTIVAZIONE del trading", key="ks_off_ok")
        if st.button("Disattiva kill switch", disabled=not ok):
            flags.clear_flag(flags.KILL_SWITCH_FLAG)
            audit("kill_switch_off", {}, "ok")
            st.success("Kill switch rimosso: il bot torna a valutare ingressi.")
            st.rerun()
    else:
        st.success("Kill switch manuale NON attivo.")
        reason = st.text_input("Motivo (finisce nell'audit e nella flag)",
                               key="ks_reason")
        ok = st.checkbox(
            "Confermo: BLOCCARE ogni nuovo ingresso del bot (le posizioni "
            "aperte restano gestite)", key="ks_on_ok")
        if st.button("ATTIVA kill switch", type="primary", disabled=not ok):
            flags.set_flag(flags.KILL_SWITCH_FLAG,
                           reason=reason or "attivato da dashboard")
            audit("kill_switch_on", {"reason": reason}, "ok")
            st.rerun()


# ----------------------------------------------------------------------
# 2. Chiusura manuale posizione (reduce-only market)
# ----------------------------------------------------------------------

def _render_manual_close(live):
    st.subheader("Chiusura manuale posizione")
    positions = live["positions"]
    if not positions:
        st.info("Nessuna posizione aperta sul venue.")
        return

    options = {
        f"{p['instrument_name']} — "
        f"{'LONG' if p.get('direction') == 'buy' else 'SHORT'} "
        f"${abs(p.get('size', 0)):,.0f}": p
        for p in positions
    }
    choice = st.selectbox("Posizione da chiudere", list(options.keys()),
                          key="close_choice")
    p = options[choice]
    instr = p["instrument_name"]
    size = abs(p.get("size", 0.0))
    close_side = "sell" if p.get("direction") == "buy" else "buy"

    idx = live["index_usd"].get(da.position_currency(instr), 0.0)
    pnl_usd = (p.get("floating_profit_loss", 0.0) or 0.0) * idx
    st.markdown(
        f"Verra' inviato un **{close_side.upper()} market reduce-only** di "
        f"**${size:,.0f}** su `{instr}` (P&L non realizzato stimato: "
        f"${pnl_usd:+,.2f}). Gli eventuali SL/TP residui diventano orfani e "
        "vengono ripuliti dal bot (o qui sotto)."
    )
    typed = st.text_input(
        f"Per confermare scrivi il nome strumento esatto: `{instr}`",
        key="close_typed")
    if st.button("CHIUDI POSIZIONE", type="primary",
                 disabled=(typed.strip() != instr)):
        result = _close_position(instr, close_side, size)
        audit("manual_close",
              {"instrument": instr, "side": close_side, "size_usd": size},
              result)
        if result == "ok":
            st.success(f"Ordine di chiusura inviato su {instr}.")
            da.fetch_live_state.clear()
            st.rerun()
        else:
            st.error(f"Chiusura fallita: {result}")


def _close_position(instrument: str, side: str, size: float) -> str:
    client, _ = da.get_deribit_client()
    if client is None:
        return "client non configurato"
    try:
        fn = client.sell if side == "sell" else client.buy
        order = fn(instrument, size, type="market",
                   label="dash_manual_close", reduce_only=True)
        if order and "error" not in order:
            return "ok"
        return f"rifiutato: {order}"
    except Exception as e:
        return f"exception: {e}"


# ----------------------------------------------------------------------
# 3. Pulizia ordini orfani on-demand
# ----------------------------------------------------------------------

def _render_orphan_cleanup(live):
    st.subheader("Pulizia ordini orfani")
    st.caption(
        "Orfano = ordine SL/TP (reduce-only o stop) su uno strumento SENZA "
        "posizione aperta — stessa definizione del cleanup automatico del "
        "bot (management loop 30s). Qui lo esegui subito."
    )

    open_instr = {p["instrument_name"] for p in live["positions"]}
    orphans = [
        o for o in live["orders"]
        if o.get("instrument_name") not in open_instr
        and (o.get("reduce_only") or da.is_stop_order(o))
    ]
    if not orphans:
        st.success("Nessun ordine orfano sul venue.")
        return

    rows = [{
        "Strumento": o.get("instrument_name", "?"),
        "Tipo": o.get("order_type", "?"),
        "Lato": (o.get("direction") or "?").upper(),
        "Size USD": o.get("amount", 0.0),
        "Label": o.get("label", ""),
        "order_id": o.get("order_id", ""),
    } for o in orphans]
    st.error(f"{len(orphans)} ordini orfani trovati:")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    ok = st.checkbox(f"Confermo la CANCELLAZIONE di {len(orphans)} ordini",
                     key="orph_ok")
    if st.button("Cancella orfani", type="primary", disabled=not ok):
        client, _ = da.get_deribit_client()
        cancelled, failed = 0, []
        for o in orphans:
            oid = o.get("order_id", "")
            if oid and client and client.cancel(oid):
                cancelled += 1
            else:
                failed.append(oid)
        result = f"cancelled={cancelled}, failed={failed}"
        audit("orphan_cleanup",
              {"order_ids": [r["order_id"] for r in rows]}, result)
        if failed:
            st.error(f"Cancellati {cancelled}, FALLITI {len(failed)}: {failed}")
        else:
            st.success(f"Cancellati tutti i {cancelled} ordini orfani.")
        da.fetch_live_state.clear()
        st.rerun()


# ----------------------------------------------------------------------
# Audit trail
# ----------------------------------------------------------------------

def _render_audit_trail():
    st.subheader("Audit log")
    entries = read_audit(50)
    if not entries:
        st.info("Nessuna azione registrata.")
        return
    df = pd.DataFrame([{
        "Quando (UTC)": e.get("ts_utc", ""),
        "Utente": e.get("user", ""),
        "Azione": e.get("action", ""),
        "Dettagli": str(e.get("details", ""))[:120],
        "Esito": e.get("result", ""),
    } for e in entries])
    st.dataframe(df, hide_index=True, width="stretch")
