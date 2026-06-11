#!/usr/bin/env python3
"""
Quantitative research on BTCUSDT 1m futures data.

Goal: find statistically robust edges BEFORE writing any strategy.
Method: in-sample (first 70%) discovery, out-of-sample (last 30%) confirmation.
All forward returns reported NET of nothing (raw) — costs applied explicitly
in the strategy-level backtests (roundtrip cost ~0.20% taker, ~0.10% maker).

Analyses:
  A. Variance ratio per horizon          -> trend vs mean-reversion structure
  B. Hour-of-day / day-of-week returns   -> seasonality
  C. Short-term reversal (15m z-score)   -> fade extreme moves?
  D. Time-series momentum (4h-24h)       -> follow the trend?
  E. Volume spike continuation/fade      -> what happens after vol z > 3?
  F. Taker buy ratio extremes            -> orderflow predictive power
  G. Donchian breakout (1h)              -> classic trend entry viability
  H. Bollinger-band fade (1h)            -> range reversion viability
  I. Funding rate extremes               -> positioning contrarian signal
"""
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd

KLINES_PATH = "data/research/btc_1m_research.json.gz"
FUNDING_PATH = "data/research/btc_funding.json"
IS_FRAC = 0.70   # in-sample fraction

pd.set_option("display.width", 160)
pd.set_option("display.float_format", lambda x: f"{x:,.4f}")


def load_data():
    with gzip.open(KLINES_PATH, "rt") as f:
        raw = json.load(f)
    df = pd.DataFrame(raw)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close",
                            "v": "vol", "bv": "buy_vol"})
    df["sell_vol"] = df["vol"] - df["buy_vol"]
    df["buy_ratio"] = np.where(df["vol"] > 0, df["buy_vol"] / df["vol"], 0.5)
    return df


def resample(df, rule):
    agg = df.resample(rule).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), vol=("vol", "sum"), buy_vol=("buy_vol", "sum"),
    ).dropna()
    agg["buy_ratio"] = np.where(agg["vol"] > 0, agg["buy_vol"] / agg["vol"], 0.5)
    agg["ret"] = agg["close"].pct_change()
    return agg


def tstat(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 3 or np.std(x) == 0:
        return 0.0
    return float(np.mean(x) / (np.std(x, ddof=1) / np.sqrt(len(x))))


def bucket_report(signal, fwd, label, n_buckets=5):
    """signal/fwd: aligned Series. Print mean fwd ret (bps) per signal quantile."""
    dfb = pd.DataFrame({"sig": signal, "fwd": fwd}).dropna()
    if len(dfb) < 100:
        print(f"  {label}: insufficient data ({len(dfb)})")
        return
    dfb["bucket"] = pd.qcut(dfb["sig"], n_buckets, labels=False, duplicates="drop")
    g = dfb.groupby("bucket")["fwd"]
    out = pd.DataFrame({
        "N": g.count(),
        "mean_bps": g.mean() * 1e4,
        "t": g.apply(tstat),
        "hit%": g.apply(lambda x: (x > 0).mean() * 100),
    })
    print(f"  {label}")
    print(out.to_string(float_format=lambda v: f"{v:8.2f}"))


def split(df):
    n = int(len(df) * IS_FRAC)
    return df.iloc[:n], df.iloc[n:]


# ===================================================================== #

def a_variance_ratio(m1):
    print("\n" + "=" * 70)
    print("A. VARIANCE RATIO (VR<1 = mean reversion, VR>1 = momentum)")
    print("=" * 70)
    lr = np.log(m1["close"]).diff().dropna()
    var1 = lr.var()
    for q in [5, 15, 60, 240, 1440]:
        lrq = np.log(m1["close"]).diff(q).dropna()
        vr = lrq.var() / (q * var1)
        print(f"  horizon {q:>5}m : VR = {vr:.3f}")


def b_seasonality(h1, d1):
    print("\n" + "=" * 70)
    print("B. SEASONALITY")
    print("=" * 70)
    is_, oos = split(h1)
    for name, d in [("IS", is_), ("OOS", oos)]:
        by_hour = d.groupby(d.index.hour)["ret"]
        stats = pd.DataFrame({
            "mean_bps": by_hour.mean() * 1e4,
            "t": by_hour.apply(tstat),
        })
        sig = stats[abs(stats["t"]) > 2.0]
        print(f"  [{name}] hours with |t|>2:")
        print(sig.to_string(float_format=lambda v: f"{v:7.2f}") if len(sig) else "    none")
    by_dow = d1.groupby(d1.index.dayofweek)["ret"]
    stats = pd.DataFrame({"mean_bps": by_dow.mean() * 1e4, "t": by_dow.apply(tstat)})
    print("  Day-of-week (full sample, 0=Mon):")
    print(stats.to_string(float_format=lambda v: f"{v:7.2f}"))


def c_reversal(m15):
    print("\n" + "=" * 70)
    print("C. SHORT-TERM REVERSAL — 15m return z-score vs forward returns")
    print("=" * 70)
    z = m15["ret"] / m15["ret"].rolling(96).std()
    for horizon in [1, 2, 4]:
        fwd = m15["close"].pct_change(horizon).shift(-horizon)
        is_idx, oos_idx = split(m15.index.to_series())
        for name, idx in [("IS", is_idx.index), ("OOS", oos_idx.index)]:
            bucket_report(z.loc[idx], fwd.loc[idx],
                          f"[{name}] z(15m ret) -> fwd {horizon*15}m")


def d_momentum(h1):
    print("\n" + "=" * 70)
    print("D. TIME-SERIES MOMENTUM — trailing return -> forward return (1h bars)")
    print("=" * 70)
    for lb in [4, 12, 24, 48]:
        trail = h1["close"].pct_change(lb)
        for horizon in [1, 4, 8]:
            fwd = h1["close"].pct_change(horizon).shift(-horizon)
            is_idx, oos_idx = split(h1.index.to_series())
            d = pd.DataFrame({"tr": trail, "fwd": fwd}).dropna()
            for name, idx in [("IS", is_idx.index), ("OOS", oos_idx.index)]:
                sub = d.loc[d.index.intersection(idx)]
                up = sub[sub["tr"] > 0]["fwd"]
                dn = sub[sub["tr"] < 0]["fwd"]
                print(f"  [{name}] trail {lb:>2}h -> fwd {horizon}h | "
                      f"after UP: {up.mean()*1e4:7.2f}bps (t={tstat(up):5.2f} N={len(up):5d}) | "
                      f"after DN: {dn.mean()*1e4:7.2f}bps (t={tstat(dn):5.2f} N={len(dn):5d})")


def e_volume_spike(m5):
    print("\n" + "=" * 70)
    print("E. VOLUME SPIKE (5m vol z>3) — continuation or fade?")
    print("=" * 70)
    volz = (m5["vol"] - m5["vol"].rolling(288).mean()) / m5["vol"].rolling(288).std()
    spike = volz > 3
    direction = np.sign(m5["ret"])
    for horizon in [1, 3, 6, 12]:
        fwd = m5["close"].pct_change(horizon).shift(-horizon)
        signed_fwd = fwd * direction  # >0 means continuation
        is_idx, oos_idx = split(m5.index.to_series())
        for name, idx in [("IS", is_idx.index), ("OOS", oos_idx.index)]:
            sel = signed_fwd[spike].dropna()
            sel = sel.loc[sel.index.intersection(idx)]
            print(f"  [{name}] fwd {horizon*5:>3}m signed-by-spike-dir: "
                  f"{sel.mean()*1e4:7.2f}bps  t={tstat(sel):5.2f}  N={len(sel)}")


def f_buy_ratio(m15):
    print("\n" + "=" * 70)
    print("F. TAKER BUY RATIO EXTREMES (15m) -> forward returns")
    print("=" * 70)
    br = m15["buy_ratio"]
    for horizon in [1, 4]:
        fwd = m15["close"].pct_change(horizon).shift(-horizon)
        is_idx, oos_idx = split(m15.index.to_series())
        for name, idx in [("IS", is_idx.index), ("OOS", oos_idx.index)]:
            bucket_report(br.loc[idx], fwd.loc[idx],
                          f"[{name}] buy_ratio -> fwd {horizon*15}m")


def g_donchian(h1):
    print("\n" + "=" * 70)
    print("G. DONCHIAN BREAKOUT (1h bars) — vectorized event study")
    print("=" * 70)
    for lb in [24, 48, 72]:
        hi = h1["high"].rolling(lb).max().shift(1)
        lo = h1["low"].rolling(lb).min().shift(1)
        long_sig = h1["close"] > hi
        short_sig = h1["close"] < lo
        for horizon in [4, 12, 24]:
            fwd = h1["close"].pct_change(horizon).shift(-horizon)
            is_idx, oos_idx = split(h1.index.to_series())
            for name, idx in [("IS", is_idx.index), ("OOS", oos_idx.index)]:
                fl = fwd[long_sig].dropna(); fl = fl.loc[fl.index.intersection(idx)]
                fs = -fwd[short_sig].dropna(); fs = fs.loc[fs.index.intersection(idx)]
                print(f"  [{name}] N={lb}h fwd={horizon}h | "
                      f"LONG brk: {fl.mean()*1e4:7.2f}bps (t={tstat(fl):5.2f} N={len(fl):4d}) | "
                      f"SHORT brk: {fs.mean()*1e4:7.2f}bps (t={tstat(fs):5.2f} N={len(fs):4d})")


def h_bollinger(h1):
    print("\n" + "=" * 70)
    print("H. BOLLINGER FADE (1h) — z-score of close vs 20-period band")
    print("=" * 70)
    ma = h1["close"].rolling(20).mean()
    sd = h1["close"].rolling(20).std()
    z = (h1["close"] - ma) / sd
    for horizon in [4, 8, 24]:
        fwd = h1["close"].pct_change(horizon).shift(-horizon)
        is_idx, oos_idx = split(h1.index.to_series())
        for name, idx in [("IS", is_idx.index), ("OOS", oos_idx.index)]:
            hi_z = fwd[z > 2].dropna(); hi_z = hi_z.loc[hi_z.index.intersection(idx)]
            lo_z = fwd[z < -2].dropna(); lo_z = lo_z.loc[lo_z.index.intersection(idx)]
            print(f"  [{name}] fwd {horizon}h | z>+2 (fade=short): {hi_z.mean()*1e4:7.2f}bps "
                  f"(t={tstat(hi_z):5.2f} N={len(hi_z):4d}) | z<-2 (fade=long): "
                  f"{lo_z.mean()*1e4:7.2f}bps (t={tstat(lo_z):5.2f} N={len(lo_z):4d})")


def i_funding(h1):
    print("\n" + "=" * 70)
    print("I. FUNDING RATE EXTREMES -> forward 8h/24h returns")
    print("=" * 70)
    if not os.path.exists(FUNDING_PATH):
        print("  no funding data")
        return
    with open(FUNDING_PATH) as f:
        raw = json.load(f)
    fr = pd.DataFrame(raw)
    fr["ts"] = pd.to_datetime(fr["t"], unit="ms", utc=True)
    fr = fr.set_index("ts").sort_index()["rate"]
    # align: at each funding event, look at forward return
    px = h1["close"]
    for horizon_h in [8, 24]:
        rows = []
        for ts, rate in fr.items():
            t0 = px.index.asof(ts)
            t1 = px.index.asof(ts + pd.Timedelta(hours=horizon_h))
            if pd.isna(t0) or pd.isna(t1) or t0 == t1:
                continue
            rows.append((ts, rate, px[t1] / px[t0] - 1))
        d = pd.DataFrame(rows, columns=["ts", "rate", "fwd"]).set_index("ts")
        is_, oos = split(d)
        for name, sub in [("IS", is_), ("OOS", oos)]:
            bucket_report(sub["rate"], sub["fwd"],
                          f"[{name}] funding rate -> fwd {horizon_h}h", n_buckets=5)


def main():
    if not os.path.exists(KLINES_PATH):
        print(f"missing {KLINES_PATH} — run download_research_data.py first")
        sys.exit(1)
    df = load_data()
    print(f"Loaded {len(df):,} 1m candles  {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}")
    print(f"Price: {df['close'].iloc[0]:,.0f} -> {df['close'].iloc[-1]:,.0f} "
          f"({(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:+.1f}%)")
    split_ts = df.index[int(len(df) * IS_FRAC)]
    print(f"IS/OOS split at: {split_ts:%Y-%m-%d}")

    m5 = resample(df, "5min")
    m15 = resample(df, "15min")
    h1 = resample(df, "1h")
    d1 = resample(df, "1D")

    a_variance_ratio(df)
    b_seasonality(h1, d1)
    c_reversal(m15)
    d_momentum(h1)
    e_volume_spike(m5)
    f_buy_ratio(m15)
    g_donchian(h1)
    h_bollinger(h1)
    i_funding(h1)


if __name__ == "__main__":
    main()
