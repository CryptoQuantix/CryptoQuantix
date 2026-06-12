"""
Pagina "Rischio & Esposizione" — Fase 2 del piano dashboard.

1. Esposizione lorda corrente vs cap MAX_GROSS_EXPOSURE (barra + breakdown)
2. Kill switch giornaliero: P&L oggi vs MAX_DAILY_LOSS_PCT
3. Vol-target MacroCore: bucket corrente e vol realizzata 30d
4. Stato macro per simbolo + matrice strategia x lato abilitato ADESSO

I numeri replicano le formule del RiskManager e dei macro-gate delle
strategie (stesse fonti dati: venue REST, klines daily Binance, journal).
"""
import pandas as pd
import streamlit as st

from src.monitoring.dashboard_app import data_access as da


def render():
    st.header("Rischio & Esposizione")

    live = da.fetch_live_state()
    if not live["ok"]:
        st.error(f"Connessione Deribit non disponibile: {live['error']}")
        return
    cfg = da.load_risk_env()
    all_trades = da.load_trades()
    closed = da.closed_trades(all_trades)
    journal_open = da.open_trades_journal(all_trades)

    _render_gross_exposure(live, cfg, journal_open)
    st.divider()
    _render_kill_switch(live, cfg, closed)
    st.divider()
    _render_vol_target()
    st.divider()
    _render_macro_matrix()


# ----------------------------------------------------------------------
# 1. Esposizione lorda vs cap
# ----------------------------------------------------------------------

def _render_gross_exposure(live, cfg, journal_open):
    st.subheader("Esposizione lorda vs cap")

    equity = da.equity_like_bot(live)
    gross = sum(abs(p.get("size", 0.0)) for p in live["positions"])
    cap = equity * cfg["max_gross_exposure"]
    available = max(0.0, cap - gross)
    util = min(1.0, gross / cap) if cap > 0 else 0.0

    cols = st.columns(4)
    cols[0].metric("Equity (per sizing)", f"${equity:,.2f}")
    cols[1].metric("Esposizione lorda", f"${gross:,.2f}")
    cols[2].metric(f"Cap ({cfg['max_gross_exposure']:.1f}x equity)", f"${cap:,.2f}")
    cols[3].metric("Margine apribile", f"${available:,.2f}")

    st.progress(util, text=f"Utilizzo cap: {util:.0%}")
    if util >= 1.0:
        st.error("Cap esposizione lorda RAGGIUNTO — nuove entry bloccate dal RiskManager")
    elif util >= 0.8:
        st.warning("Utilizzo cap sopra l'80%")

    n_open = len(live["positions"])
    st.markdown(
        f"**Posizioni aperte**: {n_open}/{cfg['max_open_trades']} "
        f"(`MAX_OPEN_TRADES`) — oltre il limite `can_open_new_position` blocca"
    )

    if live["positions"]:
        recon = da.reconcile(live["positions"], live["orders"])
        rows = []
        for p in live["positions"]:
            instr = p["instrument_name"]
            strat, _ = da.attribute_strategy(
                instr, recon["orders_by_instr"].get(instr, []), journal_open)
            size = abs(p.get("size", 0.0))
            rows.append({
                "Strumento": instr,
                "Strategia": strat,
                "Lato": "LONG" if p.get("direction") == "buy" else "SHORT",
                "Nozionale USD": size,
                "% del cap": size / cap * 100 if cap > 0 else 0.0,
                "% equity": size / equity * 100 if equity > 0 else 0.0,
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={
                "Nozionale USD": st.column_config.NumberColumn(format="$%.0f"),
                "% del cap": st.column_config.NumberColumn(format="%.1f%%"),
                "% equity": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
    else:
        st.info("Nessuna posizione aperta — esposizione lorda $0.")


# ----------------------------------------------------------------------
# 2. Kill switch giornaliero
# ----------------------------------------------------------------------

def _render_kill_switch(live, cfg, closed):
    st.subheader("Kill switch giornaliero")

    equity = da.equity_like_bot(live)
    daily = da.daily_pnl_from_journal(closed)
    budget = equity * cfg["max_daily_loss_pct"]
    remaining = budget + daily["pnl_usd"]
    triggered = daily["pnl_usd"] <= -budget

    cols = st.columns(4)
    cols[0].metric("P&L oggi (da journal)", f"${daily['pnl_usd']:+,.2f}",
                   delta=f"{daily['n_trades']} trade chiusi oggi",
                   delta_color="off")
    cols[1].metric(f"Max perdita ({cfg['max_daily_loss_pct']:.0%} equity)",
                   f"${budget:,.2f}")
    cols[2].metric("Budget perdita residuo", f"${max(0.0, remaining):,.2f}")
    cols[3].metric("Kill switch", "ATTIVO" if triggered else "inattivo")

    if triggered:
        st.error("KILL SWITCH: perdita giornaliera oltre il limite — il bot "
                 "sospende i nuovi ingressi fino a mezzanotte")
    if budget > 0:
        used = min(1.0, max(0.0, -daily["pnl_usd"] / budget))
        st.progress(used, text=f"Budget perdita usato: {used:.0%}")
    st.caption(
        "Ricostruito dai trade chiusi oggi nel journal (data locale, come il "
        "reset giornaliero del RiskManager). Lo stato autoritativo vive nel "
        "processo del bot."
    )


# ----------------------------------------------------------------------
# 3. Vol-target MacroCore
# ----------------------------------------------------------------------

def _render_vol_target():
    st.subheader("Vol-target MacroCore")

    instances = da.load_strategy_instances()
    mc_instances = [i for i in instances if i["class"] == "MacroCoreConfig"]
    if not mc_instances:
        st.info("MacroCore non abilitato nel .env (MC_ENABLED).")
        return

    macro = da.fetch_macro_state(tuple(i["symbol"] for i in mc_instances))
    rows = []
    for inst in mc_instances:
        m = macro.get(inst["symbol"], {})
        realized = m.get("realized_vol") if m.get("ok") else None
        target_bucket = da.vol_target_bucket(realized, inst["vol_target"] or 0)
        state = da.load_json_state(inst["state_path"]) if inst["state_path"] else None
        open_trade = (state or {}).get("open_trade")
        rows.append({
            "Istanza": inst["name"],
            "Simbolo": inst["symbol"],
            "Vol target": inst["vol_target"],
            "Vol realizzata 30d": realized,
            "Bucket target ORA": target_bucket,
            "Bucket posizione": (open_trade or {}).get("exposure"),
            "In posizione": "si" if open_trade else "no",
            "Quota equity (exposure_fraction)": inst["exposure_fraction"],
        })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "Vol target": st.column_config.NumberColumn(format="percent"),
            "Vol realizzata 30d": st.column_config.NumberColumn(format="percent"),
            "Bucket target ORA": st.column_config.NumberColumn(format="%.2f"),
            "Bucket posizione": st.column_config.NumberColumn(format="%.2f"),
            "Quota equity (exposure_fraction)": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.caption(
        "Bucket = clip(vol_target / vol_realizzata, 0, 1) quantizzato a 0.25 "
        "(stessa formula di MacroCore._target_exposure). Se il bucket target "
        "differisce da quello della posizione, il bot ribilancia al prossimo "
        "daily close."
    )


# ----------------------------------------------------------------------
# 4. Stato macro per simbolo + matrice strategia x lato
# ----------------------------------------------------------------------

def _render_macro_matrix():
    st.subheader("Stato macro e abilitazioni correnti")

    instances = da.load_strategy_instances()
    if not instances:
        st.warning("Impossibile caricare le strategie dal config (.env).")
        return
    symbols = tuple(sorted({i["symbol"] for i in instances if i["symbol"] != "?"}))
    macro = da.fetch_macro_state(symbols)

    # --- Stato macro per simbolo ---
    rows = []
    for sym in symbols:
        m = macro.get(sym, {})
        if not m.get("ok"):
            rows.append({"Simbolo": sym, "Fase macro": "dati non disponibili"})
            continue
        rows.append({
            "Simbolo": sym,
            "Fase macro": "BULL" if m["bull"] else "BEAR",
            "Close daily": m["close"],
            "SMA200d": m["sma200"],
            "Distanza da SMA200d": m["dist_pct"] / 100,
            "SMA200d in discesa (30d)": "si" if m["sma_declining"] else "no",
            "Funding corrente": m["funding"],
        })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, width="stretch",
        column_config={
            "Close daily": st.column_config.NumberColumn(format="%.2f"),
            "SMA200d": st.column_config.NumberColumn(format="%.2f"),
            "Distanza da SMA200d": st.column_config.NumberColumn(format="percent"),
            "Funding corrente": st.column_config.NumberColumn(format="%.6f"),
        },
    )

    # --- Matrice: chi puo' tradare cosa ADESSO ---
    st.markdown("**Matrice abilitazioni** — lato apribile ai gate macro correnti")
    matrix = []
    for inst in instances:
        m = macro.get(inst["symbol"], {})
        if not m.get("ok"):
            matrix.append({"Istanza": inst["name"], "Simbolo": inst["symbol"],
                           "LONG": "?", "SHORT": "?", "Gate": "dati macro mancanti"})
            continue
        long_txt, short_txt, gate = _instance_gates(inst, m)
        matrix.append({
            "Istanza": inst["name"],
            "Simbolo": inst["symbol"],
            "LONG": long_txt,
            "SHORT": short_txt,
            "Gate": gate,
        })
    st.dataframe(pd.DataFrame(matrix), hide_index=True, width="stretch")
    st.caption(
        "Replica dei macro-gate nel codice strategia (SMA200d daily). Sopra "
        "questi agiscono anche le REGIME_RULES orarie dello ScoringEngine e "
        "lo scoring rolling — un lato 'attivo' qui puo' comunque essere "
        "bloccato a livello orario."
    )


def _instance_gates(inst, m):
    """Replica dei gate: TB (bull->long, bear->short), FS (bear accelerante
    + funding al cap), MC (long sopra SMA200d)."""
    bull = m["bull"]
    cls = inst["class"]
    if cls == "TrendBreakdownConfig":
        if inst["enable_long"] and bull:
            long_txt = "ATTIVO (macro BULL)"
        elif not inst["enable_long"]:
            long_txt = "disabilitato (config)"
        else:
            long_txt = "in attesa (serve macro BULL)"
        if inst["enable_short"] and not bull:
            short_txt = "ATTIVO (macro BEAR)"
        elif not inst["enable_short"]:
            short_txt = "disabilitato (config — non validato qui)"
        else:
            short_txt = "in attesa (serve macro BEAR)"
        return long_txt, short_txt, "close daily vs SMA200d"

    if cls == "FundingSqueezeConfig":
        funding_ok = (m["funding"] is not None and inst["funding_threshold"]
                      and m["funding"] >= inst["funding_threshold"])
        bear_ok = (not bull) and m["sma_declining"]
        if bear_ok and funding_ok:
            short_txt = "ATTIVO (bear accelerante + funding al cap)"
        elif not bear_ok:
            short_txt = "in attesa (serve BEAR con SMA200d in discesa)"
        else:
            short_txt = (f"in attesa (funding {m['funding']:.6f} < soglia "
                         f"{inst['funding_threshold']:.6f})")
        return "—", short_txt, "SMA200d in discesa + funding >= cap"

    if cls == "MacroCoreConfig":
        long_txt = "ATTIVO (macro BULL)" if bull else "in attesa (serve macro BULL)"
        return long_txt, "—", "close daily > SMA200d, chandelier exit"

    return "?", "?", "gate non modellato per questa strategia"
