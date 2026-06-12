"""
Pagina "Storico Operazioni" — tutte le operazioni chiuse dal journal.db
con importi precisi per operazione, filtri, aggregati ed export CSV.
"""
from typing import Dict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.monitoring.dashboard_app import data_access as da

# Colonne mostrate in tabella: (colonna df, intestazione)
TABLE_COLUMNS = [
    ("entry_time", "Entrata (UTC)"),
    ("exit_time", "Uscita (UTC)"),
    ("strategy", "Strategia"),
    ("instrument", "Strumento"),
    ("lato", "Lato"),
    ("size_usd", "Size USD"),
    ("entry_price", "Prezzo entrata"),
    ("exit_price", "Prezzo uscita"),
    ("pnl_usd", "P&L $"),
    ("pnl_pct", "P&L %"),
    ("r_multiple", "R"),
    ("exit_reason", "Motivo uscita"),
    ("duration_minutes", "Durata (min)"),
]


def render():
    st.header("Storico Operazioni")

    all_trades = da.load_trades()
    if all_trades.empty:
        st.info(
            "Nessun trade nel journal (data/journal.db assente o vuoto). "
            "Il file viene creato dal bot al primo trade."
        )
        return
    closed = da.closed_trades(all_trades)
    if closed.empty:
        st.info(f"{len(all_trades)} trade nel journal ma nessuno ancora chiuso.")
        return

    # ------------------------------------------------------------------
    # Filtri
    # ------------------------------------------------------------------
    with st.sidebar:
        st.subheader("Filtri storico")
        strategies = sorted(closed["strategy"].dropna().unique())
        instruments = sorted(closed["instrument"].dropna().unique())
        f_strat = st.multiselect("Strategia", strategies, default=strategies)
        f_instr = st.multiselect("Strumento", instruments, default=instruments)
        f_esito = st.radio("Esito", ["Tutti", "Solo win", "Solo loss"], horizontal=True)
        min_day = closed["exit_time"].min().date()
        max_day = closed["exit_time"].max().date()
        f_period = st.date_input(
            "Periodo (data uscita)", value=(min_day, max_day),
            min_value=min_day, max_value=max_day,
        )

    df = closed[closed["strategy"].isin(f_strat) & closed["instrument"].isin(f_instr)]
    if f_esito == "Solo win":
        df = df[df["pnl_usd"] > 0]
    elif f_esito == "Solo loss":
        df = df[df["pnl_usd"] <= 0]
    if isinstance(f_period, tuple) and len(f_period) == 2:
        start = pd.Timestamp(f_period[0], tz="UTC")
        end = pd.Timestamp(f_period[1], tz="UTC") + pd.Timedelta(days=1)
        df = df[(df["exit_time"] >= start) & (df["exit_time"] < end)]

    # ------------------------------------------------------------------
    # Aggregati: complessivo + filtro corrente
    # ------------------------------------------------------------------
    _render_stats_row("Complessivo (tutti i trade chiusi)", da.aggregate_stats(closed))
    if len(df) != len(closed):
        _render_stats_row("Filtro corrente", da.aggregate_stats(df))

    # ------------------------------------------------------------------
    # Tabella con importi precisi
    # ------------------------------------------------------------------
    st.subheader(f"Operazioni chiuse ({len(df)})")
    if df.empty:
        st.warning("Nessun trade corrisponde ai filtri.")
        return

    view = df[[c for c, _ in TABLE_COLUMNS]].copy()
    view.columns = [h for _, h in TABLE_COLUMNS]
    st.dataframe(
        view,
        width="stretch",
        hide_index=True,
        column_config={
            "Entrata (UTC)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Uscita (UTC)": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            "Size USD": st.column_config.NumberColumn(format="$%.0f"),
            "Prezzo entrata": st.column_config.NumberColumn(format="%.2f"),
            "Prezzo uscita": st.column_config.NumberColumn(format="%.2f"),
            "P&L $": st.column_config.NumberColumn(format="$%.2f"),
            "P&L %": st.column_config.NumberColumn(format="%.3f%%"),
            "R": st.column_config.NumberColumn(format="%.2f"),
            "Durata (min)": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    st.download_button(
        "Esporta CSV (filtro corrente)",
        data=view.to_csv(index=False).encode("utf-8"),
        file_name="storico_operazioni.csv",
        mime="text/csv",
    )

    # ------------------------------------------------------------------
    # Equity curve ricostruita dai trade chiusi
    # ------------------------------------------------------------------
    st.subheader("Equity curve (P&L cumulato dai trade chiusi)")
    curve = df.sort_values("exit_time").copy()
    curve["pnl_cum"] = curve["pnl_usd"].cumsum()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=curve["exit_time"], y=curve["pnl_cum"],
        mode="lines", name="P&L cumulato $", line=dict(color="#888"),
    ))
    for strat, grp in curve.groupby("strategy"):
        fig.add_trace(go.Scatter(
            x=grp["exit_time"], y=grp["pnl_cum"],
            mode="markers", name=strat,
            hovertemplate=(
                "%{x|%Y-%m-%d %H:%M}<br>" + strat +
                "<br>P&L trade: $%{customdata:+.2f}<br>Cumulato: $%{y:.2f}"
            ),
            customdata=grp["pnl_usd"],
        ))
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_title="P&L cumulato $")
    st.plotly_chart(fig, width="stretch")

    # P&L per strategia
    by_strat = (
        df.groupby("strategy")
        .agg(trades=("pnl_usd", "size"), pnl_usd=("pnl_usd", "sum"),
             winrate=("win", "mean"), avg_r=("r_multiple", "mean"))
        .reset_index()
    )
    st.subheader("P&L per strategia (filtro corrente)")
    fig2 = px.bar(by_strat, x="strategy", y="pnl_usd", color="strategy",
                  labels={"pnl_usd": "P&L $", "strategy": ""})
    fig2.update_layout(height=300, showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.plotly_chart(fig2, width="stretch")
    with col_b:
        tbl = by_strat.copy()
        tbl.columns = ["Strategia", "Trade", "P&L $", "Win rate", "R medio"]
        st.dataframe(
            tbl, hide_index=True, width="stretch",
            column_config={
                "P&L $": st.column_config.NumberColumn(format="$%.2f"),
                "Win rate": st.column_config.NumberColumn(format="percent"),
                "R medio": st.column_config.NumberColumn(format="%.2f"),
            },
        )


def _render_stats_row(title: str, s: Dict[str, float]):
    st.caption(title)
    cols = st.columns(6)
    pf_txt = "inf" if s["pf"] == float("inf") else f"{s['pf']:.2f}"
    cols[0].metric("Trade", f"{s['n']}")
    cols[1].metric("Win rate", f"{s['winrate']:.1%}")
    cols[2].metric("P&L totale", f"${s['pnl_usd']:+,.2f}")
    cols[3].metric("Fees stimate", f"${s['fees_est']:,.2f}")
    cols[4].metric("Expectancy", f"${s['expectancy_usd']:+,.2f} ({s['expectancy_r']:+.2f}R)")
    cols[5].metric("Profit Factor", pf_txt)
