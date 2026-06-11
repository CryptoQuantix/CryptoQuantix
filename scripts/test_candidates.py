#!/usr/bin/env python3
"""
Candidate strategy tests — trade-by-trade simulation with costs.

Candidates (from quant_research.py findings):
  S1  Breakdown momentum SHORT : 1h close < N-bar low + below SMA trend filter
  S1L Mirror LONG               : 1h close > N-bar high + above SMA (sanity check)
  S2  Bull-trap fade SHORT      : 1h close > N-bar high while below slow SMA
  S3  Funding extreme SHORT     : funding rate in top trailing percentile
  S4  Pump fade SHORT (15m)     : 15m ret z > Z and buy_ratio > BR
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from strategy_lab import (load_1m, load_funding, resample, atr, simulate,
                          report, IS_FRAC)


def make_events(sig, direction, entry_ref, sl_dist, rr, bar_minutes):
    """
    Build events frame: sl/tp from reference price and distance.
    CRITICAL: pandas resample labels bars by LEFT edge — the signal is only
    known at bar CLOSE, so event timestamps are shifted by bar_minutes.
    """
    ts = sig[sig].index
    entry = entry_ref.loc[ts]
    dist = sl_dist.loc[ts]
    ev = pd.DataFrame(index=ts)
    ev["direction"] = direction
    # short: SL above entry; long: SL below entry
    ev["sl"] = entry + dist * (1 if direction < 0 else -1)
    ev["tp"] = (entry - dist * rr) if direction < 0 else (entry + dist * rr)
    if rr <= 0:
        ev["tp"] = 0.0
    ev = ev.dropna()
    ev = ev[ev["sl"] > 0]
    ev.index = ev.index + pd.Timedelta(minutes=bar_minutes - 1)  # entry on next 1m bar
    return ev


def main():
    m1 = load_1m()
    split_ts = m1.index[int(len(m1) * IS_FRAC)]
    print(f"Data: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}  split {split_ts:%Y-%m-%d}")

    h1 = resample(m1, "1h")
    m15 = resample(m1, "15min")
    atr_h1 = atr(h1, 14)
    atr_m15 = atr(m15, 14)

    # ================= S1: breakdown momentum SHORT =================
    print("\n" + "#" * 70)
    print("# S1 — BREAKDOWN MOMENTUM SHORT (1h)")
    print("#" * 70)
    for lb in [24, 48]:
        lo_n = h1["low"].rolling(lb).min().shift(1)
        sma = h1["close"].rolling(lb).mean()
        sig = (h1["close"] < lo_n) & (h1["close"] < sma)
        for sl_mult in [1.5, 2.0]:
            for rr in [2.0, 3.0, 0]:
                for hold_h in [12, 24]:
                    ev = make_events(sig, -1, h1["close"], atr_h1 * sl_mult, rr, 60)
                    tr = simulate(m1, ev, max_hold_min=hold_h * 60)
                    report(tr, f"S1 lb={lb} sl={sl_mult}xATR rr={rr} hold={hold_h}h",
                           split_ts)

    # ================= S1L: mirror LONG (sanity) =================
    print("\n" + "#" * 70)
    print("# S1L — BREAKOUT LONG mirror (expect bad in bear sample)")
    print("#" * 70)
    lb = 48
    hi_n = h1["high"].rolling(lb).max().shift(1)
    sma = h1["close"].rolling(lb).mean()
    sig = (h1["close"] > hi_n) & (h1["close"] > sma)
    ev = make_events(sig, +1, h1["close"], atr_h1 * 2.0, 3.0, 60)
    tr = simulate(m1, ev, max_hold_min=24 * 60)
    report(tr, "S1L lb=48 sl=2xATR rr=3 hold=24h", split_ts)

    # ================= S2: bull-trap fade SHORT =================
    print("\n" + "#" * 70)
    print("# S2 — BULL-TRAP FADE SHORT (upside breakout below slow SMA)")
    print("#" * 70)
    for lb in [24, 48]:
        hi_n = h1["high"].rolling(lb).max().shift(1)
        for sma_n in [120, 168]:
            sma_slow = h1["close"].rolling(sma_n).mean()
            sig = (h1["close"] > hi_n) & (h1["close"] < sma_slow)
            for sl_mult in [1.5, 2.0]:
                for rr in [2.0, 0]:
                    ev = make_events(sig, -1, h1["close"], atr_h1 * sl_mult, rr, 60)
                    tr = simulate(m1, ev, max_hold_min=24 * 60)
                    report(tr, f"S2 lb={lb} sma={sma_n} sl={sl_mult} rr={rr} hold=24h",
                           split_ts)

    # ================= S3: funding extreme SHORT =================
    print("\n" + "#" * 70)
    print("# S3 — FUNDING EXTREME SHORT")
    print("#" * 70)
    fr = load_funding()
    if fr is not None:
        # index 1h bars by their CLOSE time to avoid lookahead in ffill
        atr_closed = atr_h1.copy(); atr_closed.index = atr_closed.index + pd.Timedelta(hours=1)
        px_closed = h1["close"].copy(); px_closed.index = px_closed.index + pd.Timedelta(hours=1)
        atr_at = atr_closed.reindex(fr.index, method="ffill")
        px_at = px_closed.reindex(fr.index, method="ffill")
        for q in [0.8, 0.9]:
            thresh = fr.rolling(90, min_periods=30).quantile(q).shift(1)
            sig_idx = fr[(fr > thresh) & (fr > 0)].index
            for sl_mult in [2.0, 3.0]:
                for hold_h in [8, 24]:
                    ev = pd.DataFrame(index=sig_idx)
                    ev["direction"] = -1
                    ev["sl"] = px_at.loc[sig_idx] + atr_at.loc[sig_idx] * sl_mult
                    ev["tp"] = 0.0
                    ev = ev.dropna()
                    tr = simulate(m1, ev, max_hold_min=hold_h * 60)
                    report(tr, f"S3 q={q} sl={sl_mult}xATR hold={hold_h}h", split_ts)

    # ================= S4: pump fade SHORT (15m) =================
    print("\n" + "#" * 70)
    print("# S4 — PUMP FADE SHORT (15m z-score + buy ratio)")
    print("#" * 70)
    z = m15["ret"] / m15["ret"].rolling(96).std()
    for z_th in [2.0, 2.5, 3.0]:
        for br_th in [0.60, 0.65]:
            sig = (z > z_th) & (m15["buy_ratio"] > br_th)
            for sl_mult in [1.0, 1.5]:
                for rr in [1.5, 2.0]:
                    for hold_m in [120, 240]:
                        ev = make_events(sig, -1, m15["close"], atr_m15 * sl_mult, rr, 15)
                        tr = simulate(m1, ev, max_hold_min=hold_m)
                        report(tr, f"S4 z>{z_th} br>{br_th} sl={sl_mult} rr={rr} "
                                   f"hold={hold_m}m", split_ts)


if __name__ == "__main__":
    main()
