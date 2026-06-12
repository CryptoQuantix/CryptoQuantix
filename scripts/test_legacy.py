#!/usr/bin/env python3
"""
C7 — Validazione strategie LEGACY (mai testate quantitativamente).

Proxy fedeli del nucleo logico, testati su 4 anni con costi 0.20% e
segmentazione bull/bear:

  WM     W/M Formation (15m): >=2 vector ribassiste -> retrace 15-85% ->
         sweep del low (-0.3%) -> reclaim con vector rialzista -> LONG
         (mirror M -> SHORT). SL sotto sweep -0.5%, TP 2R.
  BRINGS NY Brings (5m): vettori nella finestra 15-16 CET; bias = REVERSAL
         (>=2 vector ribassiste -> bias LONG); ingresso 16-20 CET su vector
         di conferma; SL al low/high di sessione -0.2%; TP 1.5R; 1 trade/gg.

Vector candle (PVSRA): vol >= 1.5x media(10) nella direzione della candela.
Usage: python scripts/test_legacy.py [--symbol BTC]
"""
import argparse
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import simulate, atr
from multicycle_research import load_4y, resample, compute_phase, phase_report


def vectors(frame):
    """Bull/bear PVSRA vector flags (vol >= 1.5x avg10, directional)."""
    avg10 = frame["vol"].rolling(10).mean().shift(1)
    big = frame["vol"] >= 1.5 * avg10
    bull = big & (frame["close"] > frame["open"])
    bear = big & (frame["close"] < frame["open"])
    return bull.values, bear.values


def rsi(closes, period=14):
    delta = np.diff(closes, prepend=closes[0])
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    ru = pd.Series(up).ewm(alpha=1 / period, adjust=False).mean().values
    rd = pd.Series(dn).ewm(alpha=1 / period, adjust=False).mean().values
    rs = np.divide(ru, rd, out=np.full_like(ru, 100.0), where=rd > 0)
    return 100 - 100 / (1 + rs)


def wm_events(m15, sweep_buf=0.003, sl_buf=0.005, tp_rr=2.0,
              retr_min=0.15, retr_max=0.85, min_vec=2):
    """State-machine W/M detection on 15m bars -> events DataFrame."""
    o = m15["open"].values; h = m15["high"].values
    l = m15["low"].values; c = m15["close"].values
    bull_v, bear_v = vectors(m15)
    r = rsi(c)
    n = len(m15)
    idx = m15.index
    rows = []
    i = 30
    while i < n - 1:
        made = False
        for kind in ("W", "M"):
            vec = bear_v if kind == "W" else bull_v
            # phase 1: run of >= min_vec directional vectors ending at i
            run = 0
            j = i
            while j >= 0 and vec[j]:
                run += 1
                j -= 1
            if run < min_vec:
                continue
            p1_lo = l[j + 1:i + 1].min()
            p1_hi = h[j + 1:i + 1].max()
            imp = p1_hi - p1_lo
            if imp <= 0:
                continue
            # phase 2: retracement within 12 bars
            p2 = None
            for k in range(i + 1, min(i + 13, n)):
                ratio = (h[k] - p1_lo) / imp if kind == "W" else (p1_hi - l[k]) / imp
                if retr_min <= ratio <= retr_max:
                    p2 = k
                    break
            if p2 is None:
                continue
            # phase 3: sweep within 8 bars
            p3, sweep_px = None, None
            for k in range(p2 + 1, min(p2 + 9, n)):
                if kind == "W" and l[k] < p1_lo * (1 - sweep_buf) and r[k] < 65:
                    p3, sweep_px = k, l[k]
                    break
                if kind == "M" and h[k] > p1_hi * (1 + sweep_buf) and r[k] > 35:
                    p3, sweep_px = k, h[k]
                    break
            if p3 is None:
                continue
            # phase 4: reclaim with confirming vector within 8 bars
            for k in range(p3, min(p3 + 9, n)):
                if kind == "W" and c[k] > p1_lo and bull_v[k]:
                    entry = c[k]
                    sl = sweep_px * (1 - sl_buf)
                    risk = entry - sl
                    if risk > entry * 0.002:
                        rows.append((idx[k], +1, sl, entry + tp_rr * risk))
                        i = k
                        made = True
                    break
                if kind == "M" and c[k] < p1_hi and bear_v[k]:
                    entry = c[k]
                    sl = sweep_px * (1 + sl_buf)
                    risk = sl - entry
                    if risk > entry * 0.002:
                        rows.append((idx[k], -1, sl, entry - tp_rr * risk))
                        i = k
                        made = True
                    break
            if made:
                break
        i += 1
    ev = pd.DataFrame(rows, columns=["ts", "direction", "sl", "tp"]).set_index("ts")
    ev.index = ev.index + pd.Timedelta(minutes=14)  # signal at 15m bar close
    return ev


def brings_events(m5, sl_buf=0.002, tp_rr=1.5):
    """NY Brings reversal on 5m bars (CET windows) -> events DataFrame."""
    local = m5.index.tz_convert("Europe/Rome")
    bull_v, bear_v = vectors(m5)
    h = m5["high"].values; l = m5["low"].values; c = m5["close"].values
    o = m5["open"].values
    df = pd.DataFrame({
        "hour": local.hour, "day": local.date,
        "bull_v": bull_v, "bear_v": bear_v,
        "high": h, "low": l, "close": c, "open": o,
    }, index=m5.index)

    rows = []
    for day, sub in df.groupby("day"):
        sess = sub[sub["hour"] == 15]              # 15:00-16:00 CET
        if len(sess) < 6:
            continue
        n_bull = int(sess["bull_v"].sum())
        n_bear = int(sess["bear_v"].sum())
        if n_bear >= 2 and n_bear > n_bull:
            bias = +1                               # reversal del dump
        elif n_bull >= 2 and n_bull > n_bear:
            bias = -1                               # reversal del pump
        else:
            continue
        sess_hi, sess_lo = sess["high"].max(), sess["low"].min()
        win = sub[(sub["hour"] >= 16) & (sub["hour"] < 20)]
        for ts, rrow in win.iterrows():
            if bias > 0 and rrow["bull_v"] and rrow["close"] > rrow["open"]:
                entry = rrow["close"]
                sl = sess_lo * (1 - sl_buf)
                risk = entry - sl
                if risk > entry * 0.001:
                    rows.append((ts, +1, sl, entry + tp_rr * risk))
                break                               # 1 trade per day
            if bias < 0 and rrow["bear_v"] and rrow["close"] < rrow["open"]:
                entry = rrow["close"]
                sl = sess_hi * (1 + sl_buf)
                risk = sl - entry
                if risk > entry * 0.001:
                    rows.append((ts, -1, sl, entry - tp_rr * risk))
                break
    ev = pd.DataFrame(rows, columns=["ts", "direction", "sl", "tp"]).set_index("ts")
    ev.index = ev.index + pd.Timedelta(minutes=4)   # signal at 5m bar close
    return ev


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC")
    args = parser.parse_args()

    m1 = load_4y(args.symbol)
    bull_daily = compute_phase(m1)
    m15 = resample(m1, "15min")
    m5 = resample(m1, "5min")
    print(f"{args.symbol}: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}")

    # ---------------- W/M ----------------
    print("\n" + "#" * 70)
    print("# WM FORMATION (proxy fedele, parametri config)")
    print("#" * 70)
    ev = wm_events(m15)
    print(f"  segnali: {len(ev)}  (long {int((ev['direction']>0).sum())}, "
          f"short {int((ev['direction']<0).sum())})")
    for hold_h, lab in [(24, "hold 24h"), (8, "hold 8h")]:
        tr = simulate(m1, ev, max_hold_min=hold_h * 60)
        phase_report(tr, bull_daily, f"WM base {lab}")

    # variante: gating macro direzionale (W solo in bull, M solo in bear)
    bull_at = bull_daily.reindex(ev.index.floor("D")).fillna(False).values
    ev_g = ev[((ev["direction"] > 0) & bull_at) | ((ev["direction"] < 0) & ~bull_at)]
    tr = simulate(m1, ev_g, max_hold_min=24 * 60)
    phase_report(tr, bull_daily, "WM macro-gated (W=bull, M=bear) hold 24h")

    # ---------------- BRINGS ----------------
    print("\n" + "#" * 70)
    print("# NY BRINGS (proxy fedele, parametri config)")
    print("#" * 70)
    ev = brings_events(m5)
    print(f"  segnali: {len(ev)}  (long {int((ev['direction']>0).sum())}, "
          f"short {int((ev['direction']<0).sum())})")
    for hold_h, lab in [(8, "hold 8h (fine giornata)"), (24, "hold 24h")]:
        tr = simulate(m1, ev, max_hold_min=hold_h * 60)
        phase_report(tr, bull_daily, f"BRINGS base {lab}")

    bull_at = bull_daily.reindex(ev.index.floor("D")).fillna(False).values
    ev_g = ev[((ev["direction"] > 0) & bull_at) | ((ev["direction"] < 0) & ~bull_at)]
    tr = simulate(m1, ev_g, max_hold_min=8 * 60)
    phase_report(tr, bull_daily, "BRINGS macro-gated hold 8h")


if __name__ == "__main__":
    main()
