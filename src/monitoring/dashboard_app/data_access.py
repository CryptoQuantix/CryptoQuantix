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
