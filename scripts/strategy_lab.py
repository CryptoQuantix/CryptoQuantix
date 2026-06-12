#!/usr/bin/env python3
"""
Strategy lab — realistic trade-by-trade simulation on 1m bars.

Entries are generated on coarse bars (5m/15m/1h), execution happens on the
NEXT 1m bar open (no lookahead). SL/TP are checked intrabar on 1m high/low
(SL has priority when both hit in the same bar — conservative). Costs:
taker fee + slippage on both legs.

Used to validate candidate rules with in-sample / out-of-sample split before
implementing them as live Strategy classes.
"""
import gzip
import json
import os

import numpy as np
import pandas as pd

KLINES_PATH = "data/research/btc_1m_research.json.gz"
FUNDING_PATH = "data/research/btc_funding.json"

TAKER_FEE = 0.0005
SLIPPAGE = 0.0005
ROUND_TRIP_COST = 2 * (TAKER_FEE + SLIPPAGE)   # 0.20% — worst case, both legs taker
IS_FRAC = 0.70


def load_1m():
    with gzip.open(KLINES_PATH, "rt") as f:
        raw = json.load(f)
    df = pd.DataFrame(raw)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close",
                            "v": "vol", "bv": "buy_vol"})
    df["buy_ratio"] = np.where(df["vol"] > 0, df["buy_vol"] / df["vol"], 0.5)
    return df


def load_funding():
    if not os.path.exists(FUNDING_PATH):
        return None
    with open(FUNDING_PATH) as f:
        raw = json.load(f)
    fr = pd.DataFrame(raw)
    fr["ts"] = pd.to_datetime(fr["t"], unit="ms", utc=True)
    return fr.set_index("ts").sort_index()["rate"]


def resample(df, rule):
    agg = df.resample(rule).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), vol=("vol", "sum"), buy_vol=("buy_vol", "sum"),
    ).dropna()
    agg["buy_ratio"] = np.where(agg["vol"] > 0, agg["buy_vol"] / agg["vol"], 0.5)
    agg["ret"] = agg["close"].pct_change()
    return agg


def atr(df, n=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate(
    m1: pd.DataFrame,
    events: pd.DataFrame,
    max_hold_min: int = 24 * 60,
    cooldown_min: int = 0,
):
    """
    events: DataFrame indexed by signal bar close-time with columns:
      direction (+1/-1), sl (price), tp (price, 0 = none)
      trail (optional, price distance): chandelier trailing stop — the stop
        ratchets to extreme_since_entry -/+ trail and replaces the static SL
        once tighter. Checked against the PREVIOUS bars' extreme (the stop is
        never moved by the same bar that hits it).
    Entry: next 1m open after the event timestamp, with slippage.
    Returns trades DataFrame.
    """
    opens = m1["open"].values
    highs = m1["high"].values
    lows = m1["low"].values
    closes = m1["close"].values
    idx = m1.index
    has_trail = "trail" in events.columns

    trades = []
    last_exit_time = None

    # positions of entry bars (next 1m bar strictly after the event ts)
    entry_pos = idx.searchsorted(events.index, side="right")

    for k, (ts, ev) in enumerate(events.iterrows()):
        p0 = entry_pos[k]
        if p0 >= len(idx) - 1:
            continue
        if last_exit_time is not None and idx[p0] < last_exit_time:
            continue  # still in a trade (one position at a time)
        if cooldown_min and last_exit_time is not None and \
                idx[p0] < last_exit_time + pd.Timedelta(minutes=cooldown_min):
            continue

        d = int(ev["direction"])
        entry = opens[p0] * (1 + d * SLIPPAGE)
        sl = float(ev["sl"])
        tp = float(ev["tp"])
        trail = float(ev["trail"]) if has_trail and not np.isnan(ev["trail"]) else 0.0
        risk = abs(entry - sl)
        if risk <= 0 or entry <= 0:
            continue

        p_end = min(p0 + max_hold_min, len(idx) - 1)
        exit_price, exit_reason, p_exit = None, "time", p_end
        ext = entry  # extreme favorable price since entry (for trailing)
        for p in range(p0, p_end):
            if d > 0:
                if lows[p] <= sl:
                    exit_price, exit_reason, p_exit = sl, "sl", p
                    break
                if tp > 0 and highs[p] >= tp:
                    exit_price, exit_reason, p_exit = tp, "tp", p
                    break
                if trail > 0:
                    ext = max(ext, highs[p])
                    sl = max(sl, ext - trail)
            else:
                if highs[p] >= sl:
                    exit_price, exit_reason, p_exit = sl, "sl", p
                    break
                if tp > 0 and lows[p] <= tp:
                    exit_price, exit_reason, p_exit = tp, "tp", p
                    break
                if trail > 0:
                    ext = min(ext, lows[p])
                    sl = min(sl, ext + trail)
        if exit_price is None:
            exit_price = closes[p_end]
        exit_price *= (1 - d * SLIPPAGE)

        gross = d * (exit_price - entry) / entry
        net = gross - 2 * TAKER_FEE
        r_mult = d * (exit_price - entry) / risk
        trades.append({
            "entry_ts": idx[p0], "exit_ts": idx[p_exit],
            "direction": d, "entry": entry, "exit": exit_price,
            "reason": exit_reason, "gross_pct": gross * 100,
            "net_pct": net * 100, "r": r_mult,
            "hold_min": (idx[p_exit] - idx[p0]).total_seconds() / 60,
        })
        last_exit_time = idx[p_exit]

    return pd.DataFrame(trades)


def report(trades: pd.DataFrame, label: str, split_ts=None):
    def _stats(t):
        if len(t) == 0:
            return "  no trades"
        wins = (t["net_pct"] > 0).sum()
        wr = wins / len(t) * 100
        exp_r = t["r"].mean()
        net = t["net_pct"]
        pf = net[net > 0].sum() / abs(net[net < 0].sum()) if (net < 0).any() else 999
        eq = (1 + net / 100).cumprod()
        peak = eq.cummax()
        mdd = ((peak - eq) / peak).max() * 100
        sharpe = net.mean() / net.std() if net.std() > 0 else 0
        total = (eq.iloc[-1] - 1) * 100
        return (f"  N={len(t):4d}  WR={wr:5.1f}%  E[R]={exp_r:+.3f}  "
                f"avg_net={net.mean()*100:+7.1f}bps  PF={pf:5.2f}  "
                f"total={total:+7.1f}%  maxDD={mdd:5.1f}%  shrp/tr={sharpe:+.3f}")

    print(f"\n--- {label} ---")
    if len(trades) == 0:
        print("  no trades")
        return
    if split_ts is not None:
        is_t = trades[trades["entry_ts"] < split_ts]
        oos_t = trades[trades["entry_ts"] >= split_ts]
        print(f"  IS : {_stats(is_t)}")
        print(f"  OOS: {_stats(oos_t)}")
    print(f"  ALL: {_stats(trades)}")
    by_reason = trades.groupby("reason")["net_pct"].agg(["count", "mean"])
    print("  exits: " + "  ".join(
        f"{r}={int(c)} ({m*100:+.0f}bps)" for r, (c, m) in by_reason.iterrows()))
