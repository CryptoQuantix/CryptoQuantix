#!/usr/bin/env python3
"""
C1 step 1-2 (microevolutive/PLAN_BULL_EVOLUTION.md) — MacroCore sweep.

Baseline (round 6): long se daily close > SMA200d -> +193%/4y, maxDD 31.7%,
2025 -17% (whipsaw al top). Obiettivo: 2025 > -10% senza uccidere 2023-24.

Varianti (stato deciso sulla chiusura daily, posizione dal giorno dopo,
open-to-open, costi 0.10% per lato su ogni switch):
  V0  base                in: c>sma          out: c<sma
  V1b isteresi b          in: c>sma*(1+b)    out: c<sma*(1-b)
  V2  slope               in: c>sma & sma>sma[-30]   out: c<sma
  V3  conferma 2gg        in: 2 chiusure > sma       out: 2 chiusure < sma
  V4k chandelier k        in: c>sma          out: c < maxclose_since_entry - k*ATR20d
  V5  isteresi2% + slope  (combo)
Step 2: vol-targeting sul vincitore (esposizione = target/realized 30d,
quantizzata a step 0.25, costi sui delta di esposizione).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from multicycle_research import load_4y

COST_SIDE = 0.001   # 0.10% per lato (taker + slippage)


def daily_frame(m1):
    d = pd.DataFrame({
        "open": m1["open"].resample("1D").first(),
        "high": m1["high"].resample("1D").max(),
        "low": m1["low"].resample("1D").min(),
        "close": m1["close"].resample("1D").last(),
    }).dropna()
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - d["close"].shift()).abs(),
        (d["low"] - d["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    d["atr20"] = tr.rolling(20).mean()
    d["sma200"] = d["close"].rolling(200).mean()
    d["sma200_30ago"] = d["sma200"].shift(30)
    return d


def run_variant(d, entry_fn, exit_fn, label):
    """
    entry_fn(i, d, state) -> bool   (decided on close of day i)
    exit_fn(i, d, state)  -> bool   (state has 'max_close' since entry)
    Position held from open of day i+1 to open of day after exit signal.
    Returns (daily strat returns Series, n_roundtrips, pos Series).
    """
    n = len(d)
    closes = d["close"].values
    pos = np.zeros(n)          # position during day i (decided at i-1 close)
    in_pos = False
    state = {}
    entries = 0
    pending = 0                # position to apply tomorrow
    for i in range(n - 1):
        # carry today's position decided yesterday
        pos[i + 1] = pending
        if np.isnan(d["sma200"].values[i]):
            continue
        if not in_pos:
            if entry_fn(i, d, state):
                in_pos = True
                entries += 1
                state["max_close"] = closes[i]
                pending = 1.0
                pos[i + 1] = 1.0
        else:
            state["max_close"] = max(state["max_close"], closes[i])
            if exit_fn(i, d, state):
                in_pos = False
                pending = 0.0
                pos[i + 1] = 0.0
    pos_s = pd.Series(pos, index=d.index)
    o2o = d["open"].shift(-1) / d["open"] - 1   # return of day i (open i -> open i+1)
    switches = pos_s.diff().abs().fillna(0)
    ret = pos_s * o2o - switches * COST_SIDE
    return ret.dropna(), entries, pos_s


def report(ret, entries, pos, label):
    eq = (1 + ret).cumprod()
    peak = eq.cummax()
    mdd = ((peak - eq) / peak).max() * 100
    total = (eq.iloc[-1] - 1) * 100
    yrs = {}
    for y, sub in ret.groupby(ret.index.year):
        yrs[y] = ((1 + sub).prod() - 1) * 100
    yr_str = " ".join(f"{y}:{v:+.0f}%" for y, v in yrs.items())
    print(f"  {label:28s} TOT={total:+7.1f}%  maxDD={mdd:5.1f}%  "
          f"trades={entries:2d}  inv={pos.mean()*100:3.0f}%  | {yr_str}")
    return total, mdd, yrs


def main():
    m1 = load_4y()
    d = daily_frame(m1)
    print(f"Daily bars: {len(d)}  {d.index[0]:%Y-%m-%d} -> {d.index[-1]:%Y-%m-%d}")
    bh = (d["close"].iloc[-1] / d["close"].iloc[0] - 1) * 100
    print(f"Buy&hold: {bh:+.1f}%\n")

    c, s, s30, a = d["close"].values, d["sma200"].values, d["sma200_30ago"].values, d["atr20"].values

    results = {}

    # V0 base
    ret, n, pos = run_variant(
        d, lambda i, d_, st: c[i] > s[i], lambda i, d_, st: c[i] < s[i], "V0")
    results["V0 base"] = report(ret, n, pos, "V0 base")

    # V1 hysteresis
    for b in [0.01, 0.02, 0.03]:
        ret, n, pos = run_variant(
            d, lambda i, d_, st, b=b: c[i] > s[i] * (1 + b),
            lambda i, d_, st, b=b: c[i] < s[i] * (1 - b), f"V1 b={b}")
        results[f"V1 hyst {b*100:.0f}%"] = report(ret, n, pos, f"V1 isteresi {b*100:.0f}%")

    # V2 slope
    ret, n, pos = run_variant(
        d, lambda i, d_, st: c[i] > s[i] and s[i] > s30[i],
        lambda i, d_, st: c[i] < s[i], "V2")
    results["V2 slope30"] = report(ret, n, pos, "V2 slope200>30gg fa")

    # V3 confirm 2 days
    ret, n, pos = run_variant(
        d, lambda i, d_, st: i > 0 and c[i] > s[i] and c[i-1] > s[i-1],
        lambda i, d_, st: i > 0 and c[i] < s[i] and c[i-1] < s[i-1], "V3")
    results["V3 conferma2"] = report(ret, n, pos, "V3 conferma 2gg")

    # V4 chandelier
    for k in [3, 4, 5]:
        ret, n, pos = run_variant(
            d, lambda i, d_, st: c[i] > s[i],
            lambda i, d_, st, k=k: (not np.isnan(a[i])) and
                                   c[i] < st["max_close"] - k * a[i], f"V4 k={k}")
        results[f"V4 chand k={k}"] = report(ret, n, pos, f"V4 chandelier k={k}")

    # V5 combo: hysteresis 2% + slope
    ret, n, pos = run_variant(
        d, lambda i, d_, st: c[i] > s[i] * 1.02 and s[i] > s30[i],
        lambda i, d_, st: c[i] < s[i] * 0.98, "V5")
    results["V5 hyst2+slope"] = report(ret, n, pos, "V5 isteresi2% + slope")

    # V6 combo: chandelier k=4 con re-entry filtrato slope
    ret, n, pos = run_variant(
        d, lambda i, d_, st: c[i] > s[i] and s[i] > s30[i],
        lambda i, d_, st: (not np.isnan(a[i])) and
                          (c[i] < st["max_close"] - 4 * a[i] or c[i] < s[i]),
        "V6")
    results["V6 slope+chand4"] = report(ret, n, pos, "V6 slope + chandelier4/sma")

    # ---------------- Step 2: vol targeting sul migliore ----------------
    print("\n--- Step 2: VOL TARGETING (esposizione quantizzata 0.25) ---")
    # ricalcola il migliore per total con 2025 > -10
    o2o = d["open"].shift(-1) / d["open"] - 1
    realized = o2o.rolling(30).std() * np.sqrt(365)
    for vname, (entry_fn, exit_fn) in {
        "V0": (lambda i, d_, st: c[i] > s[i], lambda i, d_, st: c[i] < s[i]),
        "V5": (lambda i, d_, st: c[i] > s[i] * 1.02 and s[i] > s30[i],
               lambda i, d_, st: c[i] < s[i] * 0.98),
    }.items():
        _, n, pos = run_variant(d, entry_fn, exit_fn, vname)
        for tv in [0.30, 0.40]:
            expo = (tv / realized).clip(0, 1)
            expo = (expo / 0.25).round() * 0.25          # quantizza
            expo = (pos * expo).fillna(0)
            switches = expo.diff().abs().fillna(0)
            ret = expo * o2o - switches * COST_SIDE
            ret = ret.dropna()
            eq = (1 + ret).cumprod()
            mdd = ((eq.cummax() - eq) / eq.cummax()).max() * 100
            yrs = " ".join(f"{y}:{((1+sub).prod()-1)*100:+.0f}%"
                           for y, sub in ret.groupby(ret.index.year))
            print(f"  {vname} volT={tv:.0%}: TOT={(eq.iloc[-1]-1)*100:+7.1f}%  "
                  f"maxDD={mdd:5.1f}%  avg_expo={expo[pos>0].mean():.2f} | {yrs}")


if __name__ == "__main__":
    main()
