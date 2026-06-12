#!/usr/bin/env python3
"""
C3 — Validazione multi-symbol: esegue i backtest del CODICE REALE
(TrendBreakdown, FundingSqueeze, MacroCore) su un simbolo arbitrario
con gli STESSI parametri validati su BTC (zero ri-ottimizzazione:
e' un test di robustezza dell'edge, non un nuovo fit).

Usage: python scripts/validate_symbol.py --symbol ETH
"""
import argparse
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from multicycle_research import (load_4y, load_funding_4y, resample,
                                 compute_phase, phase_report)
from backtest_new_strategies import (HistoricalKlineProvider, build_candles,
                                     run as run_tactical)
from backtest_macro_core import run_macro
from config import TrendBreakdownConfig, FundingSqueezeConfig
from src.strategies.trend_breakdown import TrendBreakdownStrategy
from src.strategies.funding_squeeze import FundingSqueezeStrategy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETH")
    args = parser.parse_args()
    sym = args.symbol.upper().replace("USDT", "")
    symbol_full = f"{sym}USDT"

    print(f"Loading {sym} 4y dataset...")
    m1 = load_4y(sym)
    bull_daily = compute_phase(m1)
    funding = load_funding_4y(sym)
    print(f"Data: {m1.index[0]:%Y-%m-%d} -> {m1.index[-1]:%Y-%m-%d}  "
          f"({len(m1):,} 1m bars)  price {m1['close'].iloc[0]:,.0f} -> "
          f"{m1['close'].iloc[-1]:,.0f} "
          f"({(m1['close'].iloc[-1]/m1['close'].iloc[0]-1)*100:+.0f}%)")
    if funding is not None:
        print(f"Funding: N={len(funding)}  q50={funding.quantile(0.5):.6f}  "
              f"q90={funding.quantile(0.9):.6f}  max={funding.max():.6f}")

    h1 = resample(m1, "1h")
    d1 = resample(m1, "1D")
    h1c, d1c = build_candles(h1, 3_600_000), build_candles(d1, 86_400_000)

    # ---- tattiche: STESSI parametri di BTC, solo symbol cambiato ----
    for cls, cfg in [
        (TrendBreakdownStrategy,
         TrendBreakdownConfig(name=f"TB {sym}", symbol=symbol_full)),
        (FundingSqueezeStrategy,
         FundingSqueezeConfig(name=f"FS {sym}", symbol=symbol_full)),
    ]:
        provider = HistoricalKlineProvider(h1c, d1c, funding)
        trades = run_tactical(cls, cfg, m1, provider)
        phase_report(trades, bull_daily, cfg.name)
        if len(trades):
            by_dir = trades.groupby("direction")["net_pct"].agg(["count", "mean", "sum"])
            for d, (c_, m_, s_) in by_dir.iterrows():
                side = "LONG" if d > 0 else "SHORT"
                print(f"  {side}: N={int(c_)}  avg={m_*100:+.1f}bps  sum={s_:+.1f}%")

    # ---- MacroCore: stesso k=5, SMA200, vol-target valutato a parte ----
    t, eq = run_macro(m1)
    equity = (1 + t["net_pct"] / 100).prod() if len(t) else 1.0
    peak = eq.cummax()
    mdd = ((peak - eq) / peak).max() * 100
    bh = m1["close"].iloc[-1] / m1["close"].iloc[0] - 1
    print(f"\n--- MacroCore {sym} ---")
    print(f"  Trade: {len(t)}  Equity: {(equity-1)*100:+.1f}%  "
          f"(buy&hold {bh*100:+.1f}%)  maxDD(m2m): {mdd:.1f}%")
    if len(t):
        yearly = eq.resample("YE").last() / eq.resample("YE").first() - 1
        print("  per anno: " + "  ".join(f"{idx.year}:{v*100:+.0f}%"
                                          for idx, v in yearly.items()))
        for _, r in t.iterrows():
            print(f"    {r['entry_ts']:%Y-%m-%d} -> {r['exit_ts']:%Y-%m-%d}  "
                  f"{r['net_pct']:+7.2f}%  ({r['reason']})")


if __name__ == "__main__":
    main()
