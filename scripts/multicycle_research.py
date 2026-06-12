#!/usr/bin/env python3
"""
Multi-cycle validation of the EXISTING strategies' core logic (proxy form)
on 4 years of BTCUSDT data (bear 2022, bull 2023-2025, bear 2025-2026).

Goal: find the conditioning (direction gating, thresholds, exits) that makes
each strategy profitable in BOTH bull and bear phases — or that cleanly
deactivates it in the adverse phase.

Phase definition (no lookahead): BULL if daily close > SMA200(daily),
computed on the PREVIOUS day's close; BEAR otherwise.

Strategies tested (OHLCV proxy of their core signal, same proxies as
scripts/real_backtest.py):
  VB  VolumeBreakout : vol_z spike + N-bar breakout + flow confirm
  MR  MeanReversion  : fade z-extreme vs rolling VWAP, low-vol filter
  IS  ImbalanceScalp : strong directional flow continuation scalp
  LS  LiqSqueeze     : extreme directional volume cascade (ride direction)
  TBL TrendBreakdown LONG mirror (for bull readiness)
  FSL FundingSqueeze LONG mirror (negative funding + uptrend)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gzip
import json
import numpy as np
import pandas as pd

from strategy_lab import simulate, atr, TAKER_FEE, SLIPPAGE

KLINES_4Y_DIR = "data/research/btc_1m_4y"      # yearly chunks (committed)
KLINES_4Y = "data/research/btc_1m_4y.csv.gz"   # legacy single file (fallback)
FUNDING_4Y = "data/research/btc_funding_4y.json"


# ------------------------------------------------------------------ #
# Data
# ------------------------------------------------------------------ #

def load_4y(symbol: str = "BTC"):
    """Load a 4y dataset from yearly chunks (repo-friendly <11MB files).
    symbol: 'BTC' | 'ETH' | ... (matches data/research/<sym>_1m_4y/)."""
    import glob
    sym = symbol.replace("USDT", "").lower()
    chunks = sorted(glob.glob(
        os.path.join(f"data/research/{sym}_1m_4y", f"{sym}_1m_*.csv.gz")))
    if chunks:
        df = pd.concat(
            [pd.read_csv(p, compression="gzip") for p in chunks],
            ignore_index=True,
        )
    elif sym == "btc" and os.path.exists(KLINES_4Y):
        df = pd.read_csv(KLINES_4Y, compression="gzip")
    else:
        raise FileNotFoundError(
            f"no 4y dataset for {symbol} — run "
            f"scripts/download_multicycle.py --symbol {sym.upper()}USDT")
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                            "c": "close", "v": "vol", "bv": "buy_vol"})
    df["buy_ratio"] = np.where(df["vol"] > 0, df["buy_vol"] / df["vol"], 0.5)
    return df


def load_funding_4y(symbol: str = "BTC"):
    sym = symbol.replace("USDT", "").lower()
    path = f"data/research/{sym}_funding_4y.json"
    if not os.path.exists(path):
        return None
    with open(path) as f:
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


def compute_phase(m1):
    """Daily series: True=BULL. Shifted 1 day (known at day start)."""
    d1 = m1["close"].resample("1D").last().dropna()
    sma200 = d1.rolling(200).mean()
    bull = (d1 > sma200).shift(1).fillna(False)
    return bull


def phase_of(ts_series, bull_daily):
    """Map entry timestamps to BULL/BEAR labels."""
    days = ts_series.dt.floor("D")
    return days.map(lambda d: "BULL" if bool(bull_daily.get(d, False)) else "BEAR")


# ------------------------------------------------------------------ #
# Reporting
# ------------------------------------------------------------------ #

def _stats(t):
    if len(t) == 0:
        return "N=   0"
    net = t["net_pct"]
    wins = (net > 0).sum()
    pf = net[net > 0].sum() / abs(net[net < 0].sum()) if (net < 0).any() else 999
    return (f"N={len(t):5d}  WR={wins/len(t)*100:5.1f}%  "
            f"avg={net.mean()*100:+7.1f}bps  PF={pf:5.2f}  "
            f"sum={net.sum():+8.1f}%")


def phase_report(trades, bull_daily, label):
    print(f"\n--- {label} ---")
    if len(trades) == 0:
        print("  no trades")
        return
    ph = phase_of(trades["entry_ts"], bull_daily)
    for phase in ["BULL", "BEAR"]:
        sub = trades[ph.values == phase]
        print(f"  {phase}: {_stats(sub)}")
    print(f"  ALL : {_stats(trades)}")
    yr = trades.groupby(trades["entry_ts"].dt.year)["net_pct"].agg(["count", "sum"])
    print("  years: " + "  ".join(f"{y}:{int(c)}tr/{s:+.0f}%"
                                  for y, (c, s) in yr.iterrows()))


def make_events(sig, direction, entry_ref, sl_dist, rr, bar_minutes, tp_ref=None):
    """Events at bar close (left-label resample -> shift bar_minutes-1)."""
    ts = sig[sig].index
    entry = entry_ref.loc[ts]
    dist = sl_dist.loc[ts]
    ev = pd.DataFrame(index=ts)
    ev["direction"] = direction
    ev["sl"] = entry + dist * (1 if direction < 0 else -1)
    if tp_ref is not None:
        ev["tp"] = tp_ref.loc[ts]
    else:
        ev["tp"] = (entry - dist * rr) if direction < 0 else (entry + dist * rr)
        if rr <= 0:
            ev["tp"] = 0.0
    ev = ev.dropna()
    ev = ev[ev["sl"] > 0]
    ev.index = ev.index + pd.Timedelta(minutes=bar_minutes - 1)
    return ev


def run_both_sides(m1, sig_long, sig_short, ref, sl_dist, rr, bar_min,
                   hold_min, bull_daily, label):
    evs = []
    if sig_long is not None and sig_long.any():
        evs.append(make_events(sig_long, +1, ref, sl_dist, rr, bar_min))
    if sig_short is not None and sig_short.any():
        evs.append(make_events(sig_short, -1, ref, sl_dist, rr, bar_min))
    if not evs:
        print(f"\n--- {label} ---\n  no signals")
        return None
    ev = pd.concat(evs).sort_index()
    tr = simulate(m1, ev, max_hold_min=hold_min)
    phase_report(tr, bull_daily, label)
    return tr


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main():
    print("Loading 4y dataset...")
    m1 = load_4y()
    bull_daily = compute_phase(m1)
    bull_pct = bull_daily.mean() * 100
    print(f"Data: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}  "
          f"({len(m1):,} 1m bars)  BULL days: {bull_pct:.0f}%")
    print(f"Price: {m1['close'].iloc[0]:,.0f} -> {m1['close'].iloc[-1]:,.0f}")

    m5 = resample(m1, "5min")
    m15 = resample(m1, "15min")
    h1 = resample(m1, "1h")
    atr5 = atr(m5, 14)
    atr15 = atr(m15, 14)
    atr1h = atr(h1, 14)

    # trend reference on 1h, forward-filled to 5m/15m (bar-close aligned)
    sma48h = h1["close"].rolling(48).mean()
    sma48_closed = sma48h.copy()
    sma48_closed.index = sma48_closed.index + pd.Timedelta(hours=1)

    def trend_up_at(frame_idx, bar_minutes):
        """True where last CLOSED 1h bar close > SMA48 (no lookahead)."""
        px = h1["close"].copy()
        px.index = px.index + pd.Timedelta(hours=1)
        bar_close = frame_idx + pd.Timedelta(minutes=bar_minutes)
        up = (px.reindex(bar_close, method="ffill")
              > sma48_closed.reindex(bar_close, method="ffill"))
        up.index = frame_idx
        return up

    # ============================================================== #
    print("\n" + "#" * 72)
    print("# VB — VOLUME BREAKOUT (proxy)")
    print("#" * 72)
    for frame, atr_f, bar_min, label_tf in [(m5, atr5, 5, "5m"), (m15, atr15, 15, "15m")]:
        volz = (frame["vol"] - frame["vol"].rolling(20).mean()) / frame["vol"].rolling(20).std()
        hi20 = frame["high"].rolling(20).max().shift(1)
        lo20 = frame["low"].rolling(20).min().shift(1)
        up = trend_up_at(frame.index, bar_min)
        for vz_th in [2.5, 3.0]:
            base_l = (frame["close"] > hi20) & (volz >= vz_th) & (frame["buy_ratio"] > 0.55)
            base_s = (frame["close"] < lo20) & (volz >= vz_th) & (frame["buy_ratio"] < 0.45)
            for gate in [False, True]:
                sl = base_l & up if gate else base_l
                ss = base_s & ~up if gate else base_s
                run_both_sides(m1, sl, ss, frame["close"], atr_f * 1.5, 2.5,
                               bar_min, 24 * 60, bull_daily,
                               f"VB {label_tf} vz>{vz_th} gate={gate}")

    # ============================================================== #
    print("\n" + "#" * 72)
    print("# MR — MEAN REVERSION vs rolling VWAP (proxy)")
    print("#" * 72)
    # rolling 24h VWAP on 5m bars
    pv = (m5["close"] * m5["vol"]).rolling(288).sum()
    vv = m5["vol"].rolling(288).sum()
    vwap = pv / vv
    dev = m5["close"] - vwap
    z = dev / dev.rolling(288).std()
    volz5 = (m5["vol"] - m5["vol"].rolling(288).mean()) / m5["vol"].rolling(288).std()
    quiet = volz5 < 1.5
    up5 = trend_up_at(m5.index, 5)
    for z_th in [2.0, 2.5]:
        base_l = (z < -z_th) & quiet
        base_s = (z > z_th) & quiet
        for gate_mode in ["none", "with_trend"]:
            if gate_mode == "with_trend":
                sl_, ss_ = base_l & up5, base_s & ~up5
            else:
                sl_, ss_ = base_l, base_s
            for sl_mult, hold_h in [(1.2, 8), (2.0, 24)]:
                run_both_sides(m1, sl_, ss_, m5["close"], atr5 * sl_mult, 1.5,
                               5, hold_h * 60, bull_daily,
                               f"MR z>{z_th} gate={gate_mode} sl={sl_mult} hold={hold_h}h")

    # ============================================================== #
    print("\n" + "#" * 72)
    print("# IS — IMBALANCE SCALP continuation (proxy)")
    print("#" * 72)
    volz5 = (m5["vol"] - m5["vol"].rolling(288).mean()) / m5["vol"].rolling(288).std()
    up5 = trend_up_at(m5.index, 5)
    for br_th in [0.65, 0.70]:
        base_l = (m5["buy_ratio"] > br_th) & (volz5 < 1.8)
        base_s = (m5["buy_ratio"] < 1 - br_th) & (volz5 < 1.8)
        for gate in [False, True]:
            sl_ = base_l & up5 if gate else base_l
            ss_ = base_s & ~up5 if gate else base_s
            for tp_pct, sl_pct, hold_m in [(0.005, 0.003, 60), (0.012, 0.006, 240)]:
                # fixed-pct exits: emulate via sl_dist = sl_pct*price, rr = tp/sl
                run_both_sides(m1, sl_, ss_, m5["close"], m5["close"] * sl_pct,
                               tp_pct / sl_pct, 5, hold_m, bull_daily,
                               f"IS br>{br_th} gate={gate} tp={tp_pct*100:.1f}% "
                               f"sl={sl_pct*100:.1f}% hold={hold_m}m")

    # ============================================================== #
    print("\n" + "#" * 72)
    print("# LS — LIQ CASCADE ride (proxy: extreme directional vol)")
    print("#" * 72)
    volz5 = (m5["vol"] - m5["vol"].rolling(288).mean()) / m5["vol"].rolling(288).std()
    up5 = trend_up_at(m5.index, 5)
    cascade_buy = (volz5 > 2.5) & (m5["buy_ratio"] > 0.70)   # short squeeze
    cascade_sell = (volz5 > 2.5) & (m5["buy_ratio"] < 0.30)  # long dump
    for gate in [False, True]:
        sl_ = cascade_buy & up5 if gate else cascade_buy
        ss_ = cascade_sell & ~up5 if gate else cascade_sell
        for sl_mult, rr in [(0.8, 1.5), (1.5, 2.0)]:
            run_both_sides(m1, sl_, ss_, m5["close"], atr5 * sl_mult, rr,
                           5, 240, bull_daily,
                           f"LS ride gate={gate} sl={sl_mult} rr={rr}")

    # ============================================================== #
    print("\n" + "#" * 72)
    print("# TBL — TREND BREAKDOWN LONG MIRROR (bull readiness)")
    print("#" * 72)
    hi48 = h1["high"].rolling(48).max().shift(1)
    lo48 = h1["low"].rolling(48).min().shift(1)
    sma48 = h1["close"].rolling(48).mean()
    sig_long = (h1["close"] > hi48) & (h1["close"] > sma48) & (h1["buy_ratio"] > 0.50)
    sig_short = (h1["close"] < lo48) & (h1["close"] < sma48) & (h1["buy_ratio"] < 0.50)
    for rr in [2.0, 3.0]:
        ev = make_events(sig_long, +1, h1["close"], atr1h * 2.0, rr, 60)
        tr = simulate(m1, ev, max_hold_min=24 * 60)
        phase_report(tr, bull_daily, f"TBL LONG lb=48 sl=2xATR rr={rr} hold=24h")
    # short side on 4y for reference
    ev = make_events(sig_short, -1, h1["close"], atr1h * 2.0, 2.0, 60)
    tr = simulate(m1, ev, max_hold_min=24 * 60)
    phase_report(tr, bull_daily, "TB SHORT (4y reference)")

    # ============================================================== #
    print("\n" + "#" * 72)
    print("# FSL — FUNDING SQUEEZE LONG MIRROR + 4y short reference")
    print("#" * 72)
    fr = load_funding_4y()
    if fr is not None:
        atr_closed = atr1h.copy(); atr_closed.index = atr_closed.index + pd.Timedelta(hours=1)
        px_closed = h1["close"].copy(); px_closed.index = px_closed.index + pd.Timedelta(hours=1)
        sma_closed2 = sma48h.copy(); sma_closed2.index = sma_closed2.index + pd.Timedelta(hours=1)
        px_at = px_closed.reindex(fr.index, method="ffill")
        sma_at = sma_closed2.reindex(fr.index, method="ffill")
        atr_at = atr_closed.reindex(fr.index, method="ffill")
        print(f"  funding: N={len(fr)}  q10={fr.quantile(0.1):.6f}  q90={fr.quantile(0.9):.6f}")
        # LONG mirror: very negative funding (shorts crowded) + price above trend
        for th in [-0.00005, -0.0001]:
            idx = fr[(fr < th) & (px_at > sma_at)].index
            ev = pd.DataFrame(index=idx)
            ev["direction"] = 1
            ev["sl"] = px_at.loc[idx] - atr_at.loc[idx] * 3.0
            ev["tp"] = 0.0
            ev = ev.dropna()
            tr = simulate(m1, ev, max_hold_min=24 * 60)
            phase_report(tr, bull_daily, f"FSL LONG funding<{th*100:.3f}% trend_up")
        # SHORT on 4y for reference
        idx = fr[(fr > 0.00005) & (px_at < sma_at)].index
        ev = pd.DataFrame(index=idx)
        ev["direction"] = -1
        ev["sl"] = px_at.loc[idx] + atr_at.loc[idx] * 3.0
        ev["tp"] = 0.0
        ev = ev.dropna()
        tr = simulate(m1, ev, max_hold_min=24 * 60)
        phase_report(tr, bull_daily, "FS SHORT (4y reference)")


if __name__ == "__main__":
    main()
