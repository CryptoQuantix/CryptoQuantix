"""
Pagina "Contesto Mercato" — idee 3+4 importate da bitcoin-quant-scanner
(vedi microevolutive/PLAN_SCANNER_IDEAS.md).

SOLO CONTESTO, mai segnali: nessuno di questi numeri muove il trading.
- derivati Binance: funding storico, OI, top trader L/S, taker ratio
  (le serie vengono dall'archivio C8 data/positioning_history.db)
- on-chain: hashrate drawdown, difficulty retarget (mempool.space)
- sentiment: Fear & Greed (alternative.me)
- stato del collector C8 (copertura/staleness)
- AI Export: snapshot JSON completo da incollare in un LLM
"""
import json
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.monitoring.dashboard_app import data_access as da

MEMPOOL_API = "https://mempool.space/api"


# ----------------------------------------------------------------------
# Fetchers (cache; ogni fonte degrada a None senza rompere la pagina)
# ----------------------------------------------------------------------

@st.cache_resource
def _collector():
    from src.data.positioning_collector import PositioningCollector
    return PositioningCollector()


def _fetch_json(url: str, timeout: float = 10.0):
    try:
        import urllib.request
        from src.data.kline_provider import _build_ssl_context
        ctx = _build_ssl_context()
        try:
            with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r:
                return json.loads(r.read())
        except Exception as ex:
            if "SSL" in str(ex).upper() or "CERTIFICATE" in str(ex).upper():
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r:
                    return json.loads(r.read())
            raise
    except Exception:
        return None


@st.cache_data(ttl=600)
def fetch_funding_history(symbol: str = "BTCUSDT", limit: int = 1000):
    """Funding storico (8h): 1000 punti = ~333 giorni."""
    return _fetch_json(
        f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit={limit}")


@st.cache_data(ttl=1800)
def fetch_fear_greed():
    data = _fetch_json("https://api.alternative.me/fng/?limit=1")
    try:
        d = data["data"][0]
        return {"value": int(d["value"]), "classification": d["value_classification"]}
    except Exception:
        return None


@st.cache_data(ttl=3600)
def fetch_hashrate():
    data = _fetch_json(f"{MEMPOOL_API}/v1/mining/hashrate/1y")
    try:
        return data["hashrates"]
    except Exception:
        return None


@st.cache_data(ttl=1800)
def fetch_difficulty():
    return _fetch_json(f"{MEMPOOL_API}/v1/difficulty-adjustment")


@st.cache_data(ttl=120)
def positioning_series(metric: str, symbol: str):
    return _collector().get_series(metric, symbol, last_n=2000)


@st.cache_data(ttl=120)
def positioning_status():
    return _collector().status()


# ----------------------------------------------------------------------
# Render
# ----------------------------------------------------------------------

def render():
    st.header("Contesto Mercato")
    st.caption(
        "Solo contesto informativo: NESSUNO di questi indicatori muove il "
        "trading (le strategie usano esclusivamente i segnali validati). "
        "Serie posizionamento dall'archivio C8 — vedi "
        "microevolutive/C8_POSITIONING_EXTREMES.md"
    )

    symbol = st.radio("Simbolo", ["BTCUSDT", "ETHUSDT"], horizontal=True)

    # --- KPI row ---
    kp = da.get_kline_provider()
    funding_now = kp.get_funding_rate(symbol)
    fng = fetch_fear_greed()
    macro = da.fetch_macro_state((symbol,)).get(symbol, {})
    hashrates = fetch_hashrate()
    hash_dd = _hashrate_drawdown(hashrates)
    diff_adj = fetch_difficulty()

    cols = st.columns(5)
    cols[0].metric("Funding corrente (8h)",
                   f"{funding_now * 100:.4f}%" if funding_now is not None else "n/d")
    cols[1].metric("Fear & Greed",
                   f"{fng['value']}" if fng else "n/d",
                   delta=fng["classification"] if fng else None, delta_color="off")
    if macro.get("ok"):
        cols[2].metric("Fase macro", "BULL" if macro["bull"] else "BEAR",
                       delta=f"{macro['dist_pct']:+.1f}% da SMA200d", delta_color="off")
        cols[3].metric("Vol realizzata 30d", f"{macro['realized_vol']:.0%}"
                       if macro.get("realized_vol") else "n/d")
    cols[4].metric("Hashrate drawdown",
                   f"{hash_dd:.1f}%" if hash_dd is not None else "n/d",
                   delta="capitolazione" if (hash_dd or 0) < -10 else None,
                   delta_color="inverse")

    # --- Derivati (archivio C8) ---
    st.subheader("Posizionamento derivati (archivio C8)")
    c1, c2 = st.columns(2)
    with c1:
        _plot_series("top_ls_positions", symbol,
                     "Top Trader L/S Ratio (per size posizioni)", hline=1.0)
        _plot_series("open_interest", symbol, "Open Interest (USD)")
    with c2:
        _plot_series("taker_ratio", symbol, "Taker Buy/Sell Ratio", hline=1.0)
        _plot_series("global_ls_accounts", symbol,
                     "Global L/S Accounts (retail incluso)", hline=1.0)

    # --- Funding storico ---
    st.subheader("Funding storico (~333 giorni)")
    hist = fetch_funding_history(symbol)
    if hist:
        df = pd.DataFrame(hist)
        df["fundingRate"] = df["fundingRate"].astype(float) * 100
        df["t"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        fig = go.Figure(go.Bar(
            x=df["t"], y=df["fundingRate"],
            marker_color=["#d62728" if v > 0 else "#2ca02c" for v in df["fundingRate"]]))
        fig.add_hline(y=0.01, line_dash="dot", line_color="orange",
                      annotation_text="soglia FS (0.01%)")
        fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title="% per 8h")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Funding storico non disponibile.")

    # --- On-chain ---
    st.subheader("On-chain (mempool.space)")
    c3, c4 = st.columns([2, 1])
    with c3:
        if hashrates:
            dfh = pd.DataFrame(hashrates)
            dfh["t"] = pd.to_datetime(dfh["timestamp"], unit="s", utc=True)
            dfh["ehs"] = dfh["avgHashrate"] / 1e18
            dfh["dd"] = (dfh["ehs"] - dfh["ehs"].cummax()) / dfh["ehs"].cummax() * 100
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=dfh["t"], y=dfh["ehs"], name="Hashrate EH/s",
                                     fill="tozeroy"))
            fig.add_trace(go.Scatter(x=dfh["t"], y=dfh["dd"], name="Drawdown %",
                                     yaxis="y2", line=dict(color="red")))
            fig.update_layout(
                height=280, margin=dict(l=0, r=0, t=10, b=0),
                yaxis2=dict(overlaying="y", side="right", title="DD %"))
            st.plotly_chart(fig, width="stretch")
    with c4:
        if diff_adj:
            st.metric("Prossimo retarget difficolta'",
                      f"{diff_adj.get('difficultyChange', 0):+.2f}%",
                      delta="capitolazione miner" if diff_adj.get("difficultyChange", 0) < -3
                      else None, delta_color="inverse")
            st.metric("Progresso epoca", f"{diff_adj.get('progressPercent', 0):.1f}%")

    # --- Stato collector C8 ---
    st.subheader("Archivio C8 — stato collector")
    status = positioning_status()
    if not status:
        st.warning("Archivio vuoto: eseguire `python scripts/collect_positioning.py`")
    else:
        dfs = pd.DataFrame(status)
        dfs["primo dato"] = pd.to_datetime(dfs["first_ts_ms"], unit="ms", utc=True)
        dfs["ultimo dato"] = pd.to_datetime(dfs["last_ts_ms"], unit="ms", utc=True)
        view = dfs[["metric", "symbol", "rows", "days_covered", "primo dato",
                    "ultimo dato", "stale_hours"]]
        view.columns = ["Metrica", "Simbolo", "Righe", "Giorni coperti",
                        "Primo dato", "Ultimo dato", "Staleness (h)"]
        st.dataframe(
            view, hide_index=True, width="stretch",
            column_config={
                "Primo dato": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                "Ultimo dato": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
            })
        worst_stale = max(s["stale_hours"] for s in status)
        if worst_stale > 48:
            st.error(
                f"COLLECTOR STALE: ultimo dato {worst_stale:.0f}h fa. Oltre "
                "~20 giorni il buco diventa PERMANENTE — eseguire subito "
                "`python scripts/collect_positioning.py` e verificare il bot."
            )
        else:
            st.success(f"Collector attivo (staleness max {worst_stale:.0f}h). "
                       "Validazione C8 pianificata: giugno 2027.")

    # --- AI Export ---
    st.divider()
    _render_ai_export()


def _hashrate_drawdown(hashrates) -> float:
    """Drawdown % dell'hashrate dal massimo della finestra (1y)."""
    if not hashrates:
        return None
    try:
        values = [h["avgHashrate"] for h in hashrates]
        peak, last = max(values), values[-1]
        return (last - peak) / peak * 100 if peak > 0 else None
    except Exception:
        return None


def _plot_series(metric: str, symbol: str, title: str, hline=None):
    rows = positioning_series(metric, symbol)
    if not rows:
        st.info(f"{title}: nessun dato in archivio")
        return
    df = pd.DataFrame(rows, columns=["ts_ms", "value"])
    df["t"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    fig = go.Figure(go.Scatter(x=df["t"], y=df["value"], name=metric))
    if hline is not None:
        fig.add_hline(y=hline, line_dash="dash", line_color="gray")
    fig.update_layout(title=title, height=240, margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig, width="stretch")


# ----------------------------------------------------------------------
# AI Export (idea 4): snapshot completo per analisi LLM
# ----------------------------------------------------------------------

def _render_ai_export():
    st.subheader("AI Export — snapshot per analisi LLM")
    st.caption(
        "JSON con lo stato completo del sistema (conto, posizioni, macro, "
        "posizionamento, performance) da incollare in Claude/GPT per "
        "un'analisi. Nessun secret incluso."
    )
    if not st.button("Genera snapshot"):
        return

    snap = _build_snapshot()
    payload = json.dumps(snap, indent=2, ensure_ascii=True, default=str)
    st.code(payload, language="json")
    st.download_button(
        "Scarica JSON", data=payload.encode("utf-8"),
        file_name=f"coinmaker_snapshot_{datetime.now(timezone.utc):%Y%m%d_%H%M}.json",
        mime="application/json")


def _build_snapshot() -> dict:
    snap = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "note": ("Snapshot read-only del bot coinmaker-quant. Strategie "
                 "validate: TrendBreakdown, FundingSqueeze, MacroCore."),
    }
    try:
        live = da.fetch_live_state()
        cfg = da.load_risk_env()
        equity = da.equity_like_bot(live)
        gross = sum(abs(p.get("size", 0)) for p in live["positions"])
        recon = da.reconcile(live["positions"], live["orders"])
        journal_open = da.open_trades_journal(da.load_trades())
        snap["account"] = {
            "deribit_env": live["env"],
            "equity_usd_for_sizing": round(equity, 2),
            "gross_exposure_usd": round(gross, 2),
            "gross_cap_usd": round(equity * cfg["max_gross_exposure"], 2),
            "max_open_trades": cfg["max_open_trades"],
        }
        snap["positions"] = [{
            "instrument": p["instrument_name"],
            "side": "long" if p.get("direction") == "buy" else "short",
            "size_usd": abs(p.get("size", 0)),
            "avg_price": p.get("average_price"),
            "mark_price": p.get("mark_price"),
            "strategy": da.attribute_strategy(
                p["instrument_name"],
                recon["orders_by_instr"].get(p["instrument_name"], []),
                journal_open)[0],
        } for p in live["positions"]]
        snap["reconciliation_issues"] = recon["issues"]
    except Exception as e:
        snap["account_error"] = str(e)

    try:
        from src.core import flags
        snap["kill_switch_manual"] = flags.flag_active(flags.KILL_SWITCH_FLAG)
    except Exception:
        pass

    try:
        instances = da.load_strategy_instances()
        symbols = tuple(sorted({i["symbol"] for i in instances if i["symbol"] != "?"}))
        snap["macro_state"] = da.fetch_macro_state(symbols)
        snap["strategy_instances"] = [
            {k: v for k, v in i.items() if k != "state_path"} for i in instances]
    except Exception as e:
        snap["macro_error"] = str(e)

    try:
        closed = da.closed_trades(da.load_trades())
        if not closed.empty:
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30)
            recent = closed[closed["exit_time"] >= cutoff]
            snap["performance_30d"] = {
                "trades": int(len(recent)),
                "pnl_usd": round(float(recent["pnl_usd"].sum()), 2),
                "winrate": round(float((recent["pnl_usd"] > 0).mean()), 3)
                if len(recent) else None,
                "by_strategy": {
                    s: {"trades": int(g.shape[0]),
                        "pnl_usd": round(float(g["pnl_usd"].sum()), 2)}
                    for s, g in recent.groupby("strategy")
                },
            }
    except Exception as e:
        snap["performance_error"] = str(e)

    try:
        latest = {}
        for s in positioning_status():
            key = f"{s['metric']}/{s['symbol']}"
            series = positioning_series(s["metric"], s["symbol"])
            if series:
                latest[key] = series[-1][1]
        snap["positioning_latest"] = latest
    except Exception:
        pass

    try:
        fng = fetch_fear_greed()
        if fng:
            snap["fear_greed"] = fng
        diff_adj = fetch_difficulty()
        if diff_adj:
            snap["difficulty_change_est_pct"] = diff_adj.get("difficultyChange")
    except Exception:
        pass

    return snap
