#!/usr/bin/env python3
"""
C4 — Equity simulator con sizing reale (microevolutive/PLAN_BULL_EVOLUTION.md).

Fin qui i backtest erano full-equity per trade. Questo simulatore compone le
TRE strategie su un'unica equity giornaliera con sizing realistico:

  - TB/FS (tattiche): notional = equity * risk_pct / sl_dist  (cap 1x equity);
    P&L accreditato alla data di uscita.
  - MacroCore: esposizione = equity * expo (m2m giornaliero close-to-close,
    costi 0.10% per lato sui cambi di esposizione).

Varianti testate (griglia):
  rischio tattico : fix 1.0% | fix 1.5% | kelly (0.25x su ultimi 30 trade,
                    clamp 0.5-2%)
  de-risk su DD   : off | dimezza tutto sotto -10% di drawdown equity
  expo MacroCore  : fissa 1.0 | vol-target 40% | vol-target 30%
                    (vol-target: clip(volT/vol_realizzata_30d, 0, 1)
                     quantizzata a 0.25, ribilanciata daily)

Gate C4: maxDD < 20% con rendimento >= baseline (1% / off / fissa 1.0).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from multicycle_research import load_4y, resample
from backtest_new_strategies import (HistoricalKlineProvider, build_candles,
                                     run as run_tactical)
from backtest_macro_core import run_macro
from config import TrendBreakdownConfig, FundingSqueezeConfig
from src.strategies.trend_breakdown import TrendBreakdownStrategy
from src.strategies.funding_squeeze import FundingSqueezeStrategy

COST_SIDE = 0.001
TRADES_CACHE = "data/research/c4_trades_cache.pkl"


def get_trade_streams(m1):
    """Run (or load cached) real-code backtests -> tactical trades + MC spans."""
    if os.path.exists(TRADES_CACHE):
        import pickle
        with open(TRADES_CACHE, "rb") as f:
            return pickle.load(f)

    h1 = resample(m1, "1h")
    d1 = resample(m1, "1D")
    funding = __import__("multicycle_research").load_funding_4y()
    h1c, d1c = build_candles(h1, 3_600_000), build_candles(d1, 86_400_000)

    tactical = []
    for cls, cfg in [
        (TrendBreakdownStrategy, TrendBreakdownConfig(name="TB")),
        (FundingSqueezeStrategy, FundingSqueezeConfig(name="FS")),
    ]:
        provider = HistoricalKlineProvider(h1c, d1c, funding)
        t = run_tactical(cls, cfg, m1, provider)
        t["strategy"] = cfg.name
        tactical.append(t)
    tactical = pd.concat(tactical).sort_values("entry_ts").reset_index(drop=True)

    mc_trades, _ = run_macro(m1)

    out = (tactical, mc_trades)
    import pickle
    with open(TRADES_CACHE, "wb") as f:
        pickle.dump(out, f)
    return out


def simulate_portfolio(daily, tactical, mc_trades,
                       risk_mode="fix1", derisk=False, mc_expo_mode="fixed"):
    """Day-by-day portfolio equity. Returns (equity Series, stats dict)."""
    dates = daily.index
    closes = daily["close"]
    rets = closes.pct_change().fillna(0.0)
    realized = (rets.rolling(30).std() * np.sqrt(365)).reindex(dates)

    # MacroCore in-position indicator + entry prices
    mc_in = pd.Series(False, index=dates)
    for _, r in mc_trades.iterrows():
        mc_in.loc[(dates >= r["entry_ts"].floor("D")) &
                  (dates < r["exit_ts"].floor("D"))] = True

    # tactical bookkeeping by date
    entries_by_date = {}
    exits_by_date = {}
    for i, r in tactical.iterrows():
        entries_by_date.setdefault(r["entry_ts"].floor("D"), []).append(i)
        exits_by_date.setdefault(r["exit_ts"].floor("D"), []).append(i)

    equity = 1.0
    peak = 1.0
    eq_hist = []
    open_notional = {}            # trade idx -> notional fraction at entry
    closed_results = []           # net_pct history for kelly
    prev_expo = 0.0

    for d_i, day in enumerate(dates):
        dd_mult = 0.5 if (derisk and equity < 0.90 * peak) else 1.0

        # ---- MacroCore m2m ----
        if mc_in.loc[day]:
            if mc_expo_mode == "fixed":
                expo = 1.0
            else:
                tv = 0.40 if mc_expo_mode == "volT40" else 0.30
                rv = realized.loc[day]
                expo = 1.0 if np.isnan(rv) or rv <= 0 else min(1.0, tv / rv)
                expo = round(expo / 0.25) * 0.25
            expo *= dd_mult
        else:
            expo = 0.0
        cost = abs(expo - prev_expo) * COST_SIDE
        equity *= (1 + expo * rets.iloc[d_i] - cost)
        prev_expo = expo

        # ---- tactical exits (P&L booked today) ----
        for idx in exits_by_date.get(day, []):
            if idx in open_notional:
                nf = open_notional.pop(idx)
                net = tactical.loc[idx, "net_pct"] / 100
                equity *= (1 + nf * net)
                closed_results.append(tactical.loc[idx, "net_pct"])

        # ---- tactical entries (size decided today) ----
        for idx in entries_by_date.get(day, []):
            if risk_mode == "fix1":
                rp = 0.010
            elif risk_mode == "fix15":
                rp = 0.015
            else:  # kelly 0.25x on last 30 closed trades
                rp = 0.010
                if len(closed_results) >= 15:
                    last = np.array(closed_results[-30:])
                    wins, losses = last[last > 0], last[last <= 0]
                    if len(wins) and len(losses):
                        wr = len(wins) / len(last)
                        payoff = wins.mean() / abs(losses.mean())
                        kelly = wr - (1 - wr) / payoff
                        rp = float(np.clip(0.25 * kelly, 0.005, 0.02))
            rp *= dd_mult
            sl_dist = tactical.loc[idx, "sl_dist_pct"] / 100
            if sl_dist > 0:
                open_notional[idx] = min(1.0, rp / sl_dist)

        peak = max(peak, equity)
        eq_hist.append(equity)

    eq = pd.Series(eq_hist, index=dates)
    mdd = ((eq.cummax() - eq) / eq.cummax()).max() * 100
    total = (eq.iloc[-1] - 1) * 100
    years = (dates[-1] - dates[0]).days / 365.25
    cagr = ((eq.iloc[-1]) ** (1 / years) - 1) * 100
    yearly = {}
    for y, sub in eq.groupby(eq.index.year):
        yearly[y] = (sub.iloc[-1] / sub.iloc[0] - 1) * 100
    worst = min(yearly.values())
    return eq, {"total": total, "mdd": mdd, "cagr": cagr,
                "calmar": cagr / mdd if mdd > 0 else 0, "worst_yr": worst,
                "yearly": yearly}


def main():
    print("Loading 4y dataset + real-code trade streams...")
    m1 = load_4y()
    daily = resample(m1, "1D")
    tactical, mc_trades = get_trade_streams(m1)
    print(f"  tactical trades: {len(tactical)} "
          f"(TB {len(tactical[tactical['strategy']=='TB'])}, "
          f"FS {len(tactical[tactical['strategy']=='FS'])})  "
          f"MC spans: {len(mc_trades)}")

    rows = []
    for risk_mode in ["fix1", "fix15", "kelly"]:
        for derisk in [False, True]:
            for mc_mode in ["fixed", "volT40", "volT30"]:
                _, s = simulate_portfolio(daily, tactical, mc_trades,
                                          risk_mode, derisk, mc_mode)
                rows.append({"risk": risk_mode, "derisk": derisk,
                             "mc": mc_mode, **{k: v for k, v in s.items()
                                               if k != "yearly"},
                             "yearly": s["yearly"]})

    base = rows[0]
    print(f"\n{'risk':>6} {'derisk':>6} {'mc':>7} | {'TOT%':>8} {'maxDD%':>7} "
          f"{'CAGR%':>6} {'Calmar':>6} {'worstY%':>7}  gate")
    print("-" * 75)
    for r in rows:
        gate = "PASS" if (r["mdd"] < 20 and r["total"] >= base["total"]) else "    "
        print(f"{r['risk']:>6} {str(r['derisk']):>6} {r['mc']:>7} | "
              f"{r['total']:>+8.1f} {r['mdd']:>7.1f} {r['cagr']:>6.1f} "
              f"{r['calmar']:>6.2f} {r['worst_yr']:>+7.1f}  {gate}")

    print("\nDettaglio per anno (baseline e righe PASS):")
    for r in rows:
        if r is base or (r["mdd"] < 20 and r["total"] >= base["total"]):
            yr = " ".join(f"{y}:{v:+.0f}%" for y, v in r["yearly"].items())
            tag = "BASE" if r is base else "PASS"
            print(f"  [{tag}] {r['risk']}/{r['derisk']}/{r['mc']}: {yr}")


if __name__ == "__main__":
    main()
