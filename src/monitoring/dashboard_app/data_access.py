"""
Strato di accesso dati READ-ONLY per la dashboard.

Fonti:
  - data/journal.db (TradeLogger)  -> storico operazioni + trade aperti lato bot
  - data/macro_core_state.json     -> stato posizione core
  - Deribit REST (private, GET)    -> equity, posizioni, ordini aperti

La dashboard non scrive MAI: sqlite aperto in mode=ro, nessuna chiamata
Deribit che modifichi stato (solo get_*).
"""
import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

JOURNAL_DB = os.getenv("JOURNAL_DB_PATH", "data/journal.db")
MACRO_CORE_STATE = "data/macro_core_state.json"
SCORING_STATE = os.getenv("SCORING_STATE_PATH", "data/scoring_state.json")

# Fee taker Deribit perpetual (0.05%) — usata SOLO per la stima fees nello storico
TAKER_FEE = 0.0005

# Prefissi label ordine -> strategia (label impostate in src/strategies/*)
LABEL_PREFIX_TO_STRATEGY = [
    ("tb_", "TrendBreakdown"),
    ("fs_", "FundingSqueeze"),
    ("mc_", "MacroCore"),
    ("vb_", "VolumeBreakout"),
    ("mr_", "MeanReversion"),
    ("liq_", "LiqSqueeze"),
    ("is_", "ImbalanceScalp"),
    ("wm_", "WMFormation"),
    ("brings_", "Brings"),
    ("smart_money", "SmartMoney"),
    ("sm_", "SmartMoney"),
    ("iron_condor", "IronCondor"),
]


def strategy_from_label(label: str) -> str:
    label = (label or "").lower()
    for prefix, name in LABEL_PREFIX_TO_STRATEGY:
        if label.startswith(prefix):
            return name
    return ""


# ----------------------------------------------------------------------
# journal.db
# ----------------------------------------------------------------------

@st.cache_data(ttl=30)
def load_trades(db_path: str = JOURNAL_DB) -> pd.DataFrame:
    """Tutti i trade dal journal (aperti + chiusi), con colonne derivate."""
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query("SELECT * FROM trades", conn)
    finally:
        conn.close()
    if df.empty:
        return df

    for col in ("entry_time", "exit_time"):
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True, format="ISO8601")

    # Su Deribit perpetual la size e' gia' nozionale in USD
    df["size_usd"] = df["quantity"]
    df["pnl_pct"] = 0.0
    mask = df["quantity"] > 0
    df.loc[mask, "pnl_pct"] = df.loc[mask, "pnl_usd"] / df.loc[mask, "quantity"] * 100
    # Stima fees: entry + exit a taker (entry market; SL stop_market; TP limit
    # sarebbe maker, quindi la stima e' prudenziale per eccesso)
    df["fees_est_usd"] = df["size_usd"] * TAKER_FEE * 2
    df["lato"] = df["direction"].str.lower().map({"buy": "LONG", "sell": "SHORT"})
    return df


def closed_trades(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["status"] == "closed"].sort_values("exit_time", ascending=False)


def open_trades_journal(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["status"] == "open"].sort_values("entry_time", ascending=False)


def aggregate_stats(df: pd.DataFrame) -> Dict[str, float]:
    """Footer aggregato per un set (gia' filtrato) di trade CHIUSI."""
    if df.empty:
        return {"n": 0, "winrate": 0.0, "pnl_usd": 0.0, "fees_est": 0.0,
                "expectancy_usd": 0.0, "expectancy_r": 0.0, "pf": 0.0}
    wins = df[df["pnl_usd"] > 0]["pnl_usd"].sum()
    losses = abs(df[df["pnl_usd"] <= 0]["pnl_usd"].sum())
    return {
        "n": len(df),
        "winrate": (df["pnl_usd"] > 0).mean(),
        "pnl_usd": df["pnl_usd"].sum(),
        "fees_est": df["fees_est_usd"].sum(),
        "expectancy_usd": df["pnl_usd"].mean(),
        "expectancy_r": df["r_multiple"].mean(),
        "pf": (wins / losses) if losses > 0 else float("inf"),
    }


# ----------------------------------------------------------------------
# State files
# ----------------------------------------------------------------------

def load_json_state(path: str) -> Optional[Dict[str, Any]]:
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Dashboard] state file {path} illeggibile: {e}")
    return None


# ----------------------------------------------------------------------
# Deribit REST (read-only)
# ----------------------------------------------------------------------

@st.cache_resource
def get_deribit_client() -> Tuple[Optional[Any], str]:
    """Client Deribit costruito dal .env. Ritorna (client|None, env)."""
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("DERIBIT_API_KEY", "")
    api_secret = os.getenv("DERIBIT_API_SECRET", "")
    env = os.getenv("DERIBIT_ENV", "test")
    if not api_key or not api_secret:
        return None, env
    from src.core.deribit_client import DeribitClient
    return DeribitClient(api_key, api_secret, env), env


@st.cache_data(ttl=10)
def fetch_live_state(currencies: Tuple[str, ...] = ("BTC", "ETH")) -> Dict[str, Any]:
    """
    Snapshot live dal venue: equity per valuta, posizioni future/perp
    aperte, ordini aperti, prezzo indice per conversione USD.
    """
    client, env = get_deribit_client()
    out: Dict[str, Any] = {
        "env": env, "ok": False, "error": None,
        "accounts": {}, "positions": [], "orders": [], "index_usd": {},
    }
    if client is None:
        out["error"] = "DERIBIT_API_KEY / DERIBIT_API_SECRET non impostate nel .env"
        return out
    try:
        for cur in currencies:
            acct = client.get_account_summary(cur)
            if acct:
                out["accounts"][cur] = {
                    "equity": acct.get("equity", 0.0),
                    "balance": acct.get("balance", 0.0),
                    "available_funds": acct.get("available_funds", 0.0),
                }
            tick = client.get_ticker(f"{cur}-PERPETUAL")
            if tick:
                out["index_usd"][cur] = (
                    tick.get("index_price") or tick.get("mark_price") or 0.0
                )
            for p in client.get_futures_positions(cur):
                if abs(p.get("size", 0)) > 0:
                    out["positions"].append(p)
            out["orders"].extend(client.get_open_orders(currency=cur, kind="future") or [])
        out["ok"] = True
    except Exception as e:
        out["error"] = str(e)
    return out


def position_currency(instrument_name: str) -> str:
    return (instrument_name or "").split("-")[0].upper()


def is_stop_order(order: Dict[str, Any]) -> bool:
    otype = (order.get("order_type") or "").lower()
    return "stop" in otype or bool(order.get("trigger"))


def reconcile(positions: List[Dict], orders: List[Dict]) -> Dict[str, Any]:
    """
    Riconciliazione posizioni <-> ordini sul venue.

    Problemi rilevati:
      - ORDINE ORFANO: ordine aperto su strumento SENZA posizione
      - POSIZIONE SENZA SL: posizione aperta senza alcuno stop order
    """
    pos_by_instr = {p["instrument_name"]: p for p in positions}
    orders_by_instr: Dict[str, List[Dict]] = {}
    for o in orders:
        orders_by_instr.setdefault(o.get("instrument_name", "?"), []).append(o)

    issues: List[Dict[str, str]] = []
    for instr, olist in orders_by_instr.items():
        if instr not in pos_by_instr:
            for o in olist:
                issues.append({
                    "problema": "ORDINE ORFANO",
                    "strumento": instr,
                    "dettaglio": (
                        f"{(o.get('order_type') or '?')} {(o.get('direction') or '?').upper()} "
                        f"{o.get('amount', 0):,.0f} USD | label={o.get('label', '')} "
                        f"| id={o.get('order_id', '')}"
                    ),
                })
    for instr in pos_by_instr:
        olist = orders_by_instr.get(instr, [])
        if not any(is_stop_order(o) for o in olist):
            issues.append({
                "problema": "POSIZIONE SENZA SL",
                "strumento": instr,
                "dettaglio": "nessuno stop order attivo su questo strumento",
            })
    return {
        "pos_by_instr": pos_by_instr,
        "orders_by_instr": orders_by_instr,
        "issues": issues,
    }


# ----------------------------------------------------------------------
# Rischio / esposizione (Fase 2) — stessi numeri del RiskManager
# ----------------------------------------------------------------------

def load_risk_env() -> Dict[str, float]:
    """Parametri rischio dal .env, stessi nomi e default di async_trading_bot."""
    from dotenv import load_dotenv
    load_dotenv()
    return {
        "max_gross_exposure": float(os.getenv("MAX_GROSS_EXPOSURE", 1.5)),
        "max_daily_loss_pct": float(os.getenv("MAX_DAILY_LOSS_PCT", 0.03)),
        "max_open_trades": int(os.getenv("MAX_OPEN_TRADES", 3)),
        "base_risk_pct": float(os.getenv("BASE_RISK_PCT", 0.01)),
        "initial_equity": float(os.getenv("INITIAL_EQUITY", 10000)),
    }


def equity_like_bot(live: Dict[str, Any]) -> float:
    """Equity totale USD come RiskManager.get_total_equity: somma BTC+ETH
    convertita al prezzo indice, con il cap testnet di $50k sul sizing."""
    total = sum(
        acct["equity"] * live["index_usd"].get(cur, 0.0)
        for cur, acct in live["accounts"].items()
    )
    if live["env"] == "test" and total > 50000.0:
        total = 50000.0
    return total


def daily_pnl_from_journal(closed: pd.DataFrame) -> Dict[str, Any]:
    """P&L del giorno corrente ricostruito dal journal (trade chiusi oggi,
    data locale come RiskManager._check_daily_reset che usa date.today())."""
    if closed.empty:
        return {"pnl_usd": 0.0, "n_trades": 0}
    local_tz = datetime.now().astimezone().tzinfo
    today = datetime.now().date()
    exits_local = closed["exit_time"].dt.tz_convert(local_tz)
    today_mask = exits_local.dt.date == today
    return {
        "pnl_usd": float(closed.loc[today_mask, "pnl_usd"].sum()),
        "n_trades": int(today_mask.sum()),
    }


@st.cache_resource
def get_kline_provider():
    from src.data.kline_provider import BinanceKlineProvider
    return BinanceKlineProvider()


@st.cache_data(ttl=60)
def fetch_macro_state(
    symbols: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
    sma_days: int = 200,
    slope_days: int = 30,
    vol_lookback: int = 30,
) -> Dict[str, Dict[str, Any]]:
    """
    Stato macro per simbolo da klines daily Binance (dati pubblici).
    Stessa matematica dei gate nelle strategie:
      - bull: ultimo close daily CHIUSO > SMA(sma_days)        (TB/MC)
      - sma_declining: SMA oggi < SMA slope_days fa            (FS)
      - realized_vol: vol 30d annualizzata sqrt(365)           (MC vol-target)
    """
    kp = get_kline_provider()
    out: Dict[str, Dict[str, Any]] = {}
    for sym in symbols:
        daily = kp.get_klines(sym, "1d", sma_days + slope_days + 2)
        if len(daily) < sma_days + 1:
            out[sym] = {"ok": False}
            continue
        closes = [c["close"] for c in daily]
        close = closes[-1]
        sma_now = sum(closes[-sma_days:]) / sma_days
        sma_past = None
        if len(closes) >= sma_days + slope_days:
            past = closes[-(sma_days + slope_days):-slope_days]
            sma_past = sum(past) / len(past)
        vol = None
        if len(closes) >= vol_lookback + 1:
            cl = closes[-(vol_lookback + 1):]
            rets = [cl[i] / cl[i - 1] - 1 for i in range(1, len(cl))]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            vol = (var ** 0.5) * (365 ** 0.5)
        out[sym] = {
            "ok": True,
            "close": close,
            "sma200": sma_now,
            "bull": close > sma_now,
            "dist_pct": (close - sma_now) / sma_now * 100,
            "sma_declining": sma_past is not None and sma_now < sma_past,
            "funding": kp.get_funding_rate(sym),
            "realized_vol": vol,
        }
    return out


def vol_target_bucket(realized_vol: Optional[float], vol_target: float,
                      step: float = 0.25) -> Optional[float]:
    """Bucket esposizione vol-target, identico a MacroCore._target_exposure."""
    if vol_target <= 0:
        return 1.0
    if not realized_vol or realized_vol <= 0:
        return None
    expo = min(1.0, vol_target / realized_vol)
    expo = round(expo / step) * step
    return max(step, expo)


def load_strategy_instances() -> List[Dict[str, Any]]:
    """Istanze strategia attive ESATTAMENTE come le costruisce il bot
    (Config.load_strategies dal .env). Sola lettura, nessun side effect."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from config import Config
        Config.load_strategies()
        out = []
        for cfg in Config.STRATEGIES:
            out.append({
                "name": getattr(cfg, "name", cfg.__class__.__name__),
                "class": cfg.__class__.__name__,
                "symbol": getattr(cfg, "symbol",
                                  getattr(cfg, "binance_symbol", "?")),
                "instrument": getattr(cfg, "instrument", "?"),
                "enable_long": getattr(cfg, "enable_long", None),
                "enable_short": getattr(cfg, "enable_short", None),
                "funding_threshold": getattr(cfg, "funding_threshold", None),
                "vol_target": getattr(cfg, "vol_target", None),
                "exposure_fraction": getattr(cfg, "exposure_fraction", None),
                "state_path": getattr(cfg, "state_path", None),
            })
        return out
    except Exception as e:
        logger.warning(f"[Dashboard] load_strategies fallita: {e}")
        return []


def attribute_strategy(
    instrument: str,
    orders_on_instr: List[Dict],
    journal_open: pd.DataFrame,
) -> Tuple[str, Optional[pd.Timestamp]]:
    """
    Chi possiede la posizione: (1) trade 'open' nel journal sullo stesso
    strumento, (2) label degli ordini SL/TP attivi, (3) state file MacroCore.
    Ritorna (strategia | '?', entry_time | None).
    """
    if not journal_open.empty:
        match = journal_open[journal_open["instrument"] == instrument]
        if not match.empty:
            row = match.iloc[0]
            return row["strategy"], row["entry_time"]
    for o in orders_on_instr:
        name = strategy_from_label(o.get("label", ""))
        if name:
            return name, None
    mc = load_json_state(MACRO_CORE_STATE)
    if mc and mc.get("open_trade") and mc["open_trade"].get("instrument") == instrument:
        return "MacroCore", None
    return "?", None
