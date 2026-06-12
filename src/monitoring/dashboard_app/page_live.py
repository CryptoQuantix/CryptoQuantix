"""
Pagina "Trade in corso" — posizioni e ordini aperti dal venue (Deribit REST,
sola lettura) con riconciliazione: ordini orfani e posizioni senza SL
evidenziati in rosso.
"""
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.monitoring.dashboard_app import data_access as da


def render():
    st.header("Trade in corso")

    live = da.fetch_live_state()
    env_badge = "PROD" if live["env"] == "prod" else "TESTNET"
    col_l, col_r = st.columns([3, 1])
    with col_l:
        st.caption(f"Venue: Deribit **{env_badge}** | snapshot REST ogni 10s")
    with col_r:
        if st.button("Aggiorna ora"):
            da.fetch_live_state.clear()
            st.rerun()

    if not live["ok"]:
        st.error(f"Connessione Deribit non disponibile: {live['error']}")
        return

    # ------------------------------------------------------------------
    # Equity
    # ------------------------------------------------------------------
    cols = st.columns(max(len(live["accounts"]), 1) + 1)
    total_usd = 0.0
    for i, (cur, acct) in enumerate(sorted(live["accounts"].items())):
        idx = live["index_usd"].get(cur, 0.0)
        usd = acct["equity"] * idx
        total_usd += usd
        cols[i].metric(f"Equity {cur}", f"{acct['equity']:.6f} {cur}",
                       delta=f"${usd:,.2f}", delta_color="off")
    cols[-1].metric("Equity totale (stima)", f"${total_usd:,.2f}")

    # ------------------------------------------------------------------
    # Riconciliazione: PRIMA i problemi, ben visibili
    # ------------------------------------------------------------------
    recon = da.reconcile(live["positions"], live["orders"])
    if recon["issues"]:
        st.error(f"RICONCILIAZIONE: {len(recon['issues'])} problema/i rilevato/i")
        st.dataframe(
            pd.DataFrame(recon["issues"]),
            hide_index=True, width="stretch",
        )
    else:
        st.success(
            "Riconciliazione OK: nessun ordine orfano, ogni posizione ha uno stop attivo."
        )

    # ------------------------------------------------------------------
    # Posizioni aperte
    # ------------------------------------------------------------------
    st.subheader(f"Posizioni aperte ({len(live['positions'])})")
    journal_open = da.open_trades_journal(da.load_trades())
    if not live["positions"]:
        st.info("Nessuna posizione aperta sul venue.")
    else:
        rows = []
        naked_flags = []
        for p in live["positions"]:
            instr = p["instrument_name"]
            orders_here = recon["orders_by_instr"].get(instr, [])
            strat, entry_time = da.attribute_strategy(instr, orders_here, journal_open)
            mark = p.get("mark_price", 0.0) or 0.0
            idx = live["index_usd"].get(da.position_currency(instr), mark)
            pnl_usd = (p.get("floating_profit_loss", 0.0) or 0.0) * idx

            sl_dist, tp_dist = _sl_tp_distance(orders_here, mark)
            age = _age_str(entry_time)
            naked = not any(da.is_stop_order(o) for o in orders_here)
            naked_flags.append(naked)
            rows.append({
                "Strumento": instr,
                "Lato": "LONG" if p.get("direction") == "buy" else "SHORT",
                "Size USD": abs(p.get("size", 0.0)),
                "Prezzo medio": p.get("average_price", 0.0),
                "Mark": mark,
                "P&L non realizzato $": pnl_usd,
                "Strategia": strat,
                "Eta": age,
                "Dist. SL %": sl_dist,
                "Dist. TP %": tp_dist,
                "SL attivo": "NO — NUDA" if naked else "si",
            })
        df_pos = pd.DataFrame(rows)
        st.dataframe(
            df_pos.style.apply(
                lambda row: [
                    "background-color: #5c1a1a" if naked_flags[row.name] else ""
                ] * len(row),
                axis=1,
            ),
            hide_index=True, width="stretch",
            column_config={
                "Size USD": st.column_config.NumberColumn(format="$%.0f"),
                "Prezzo medio": st.column_config.NumberColumn(format="%.2f"),
                "Mark": st.column_config.NumberColumn(format="%.2f"),
                "P&L non realizzato $": st.column_config.NumberColumn(format="$%.2f"),
                "Dist. SL %": st.column_config.NumberColumn(format="%.2f%%"),
                "Dist. TP %": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

    # ------------------------------------------------------------------
    # Ordini aperti sul venue
    # ------------------------------------------------------------------
    st.subheader(f"Ordini aperti sul venue ({len(live['orders'])})")
    if not live["orders"]:
        st.info("Nessun ordine aperto.")
    else:
        orphan_instr = {
            i["strumento"] for i in recon["issues"] if i["problema"] == "ORDINE ORFANO"
        }
        rows = []
        orphan_flags = []
        for o in live["orders"]:
            instr = o.get("instrument_name", "?")
            is_orphan = instr in orphan_instr
            orphan_flags.append(is_orphan)
            rows.append({
                "Strumento": instr,
                "Tipo": o.get("order_type", "?"),
                "Lato": (o.get("direction") or "?").upper(),
                "Size USD": o.get("amount", 0.0),
                "Prezzo": o.get("price") if not da.is_stop_order(o) else None,
                "Trigger": o.get("trigger_price"),
                "Reduce-only": "si" if o.get("reduce_only") else "no",
                "Label": o.get("label", ""),
                "Strategia": da.strategy_from_label(o.get("label", "")) or "?",
                "Stato": "ORFANO" if is_orphan else "ok",
            })
        df_ord = pd.DataFrame(rows)
        st.dataframe(
            df_ord.style.apply(
                lambda row: [
                    "background-color: #5c1a1a" if orphan_flags[row.name] else ""
                ] * len(row),
                axis=1,
            ),
            hide_index=True, width="stretch",
            column_config={
                "Size USD": st.column_config.NumberColumn(format="$%.0f"),
                "Prezzo": st.column_config.NumberColumn(format="%.2f"),
                "Trigger": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    # ------------------------------------------------------------------
    # Trade aperti secondo il journal (vista bot, per confronto)
    # ------------------------------------------------------------------
    st.subheader(f"Trade aperti secondo il journal ({len(journal_open)})")
    if journal_open.empty:
        st.info("Il journal non registra trade aperti.")
    else:
        jview = journal_open[[
            "entry_time", "strategy", "instrument", "lato",
            "size_usd", "entry_price", "sl_price", "tp_price",
        ]].copy()
        jview.columns = ["Entrata (UTC)", "Strategia", "Strumento", "Lato",
                         "Size USD", "Prezzo entrata", "SL", "TP"]
        st.dataframe(
            jview, hide_index=True, width="stretch",
            column_config={
                "Entrata (UTC)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Size USD": st.column_config.NumberColumn(format="$%.0f"),
            },
        )
        venue_instr = {p["instrument_name"] for p in live["positions"]}
        ghost = journal_open[~journal_open["instrument"].isin(venue_instr)]
        if not ghost.empty:
            st.warning(
                f"{len(ghost)} trade 'open' nel journal SENZA posizione sul venue "
                "(chiusi via SL/TP e non ancora riconciliati dall'outcome tracker, "
                "oppure desincronizzati)."
            )


def _sl_tp_distance(orders_on_instr, mark: float):
    """Distanza % di SL (stop) e TP (limit reduce-only) dal mark price."""
    sl_dist = tp_dist = None
    if mark <= 0:
        return sl_dist, tp_dist
    for o in orders_on_instr:
        if da.is_stop_order(o) and o.get("trigger_price"):
            sl_dist = (o["trigger_price"] - mark) / mark * 100
        elif o.get("reduce_only") and o.get("price"):
            tp_dist = (o["price"] - mark) / mark * 100
    return sl_dist, tp_dist


def _age_str(entry_time) -> str:
    if entry_time is None or pd.isna(entry_time):
        return "?"
    delta = datetime.now(timezone.utc) - entry_time.to_pydatetime()
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{delta.total_seconds() / 60:.0f} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} gg"
