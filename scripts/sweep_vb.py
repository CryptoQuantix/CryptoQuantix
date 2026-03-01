#!/usr/bin/env python3
"""
Parameter sweep — VolumeBreakoutStrategy.

Testa tutte le combinazioni di:
  - volume_zscore_threshold : [1.5, 1.7, 2.0, 2.3, 2.5]
  - imbalance_threshold     : [0.50, 0.52, 0.55, 0.58]
  - rr_ratio                : [1.5, 2.0, 2.5, 3.0]

Per ogni combinazione calcola: trades, WR%, Sharpe, Calmar, P&L%, Profit Factor.
Ordina e stampa i migliori 20 + il confronto con i parametri di default.

Usa la cache di real_backtest.py — nessun re-download se fresca.
"""
import json
import logging
import os
import sys
import time
from itertools import product
from typing import Dict, List

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger_root = logging.getLogger()
logger_root.setLevel(logging.WARNING)
logging.getLogger("src").setLevel(logging.WARNING)
logging.getLogger("strategy").setLevel(logging.WARNING)

# Importa utilità dal real_backtest
from scripts.real_backtest import (
    load_or_download_candles, run_strategy_backtest,
    full_report, SYMBOL, DAYS, INITIAL_EQUITY,
)

# ------------------------------------------------------------------ #
# Grid
# ------------------------------------------------------------------ #
GRID = {
    "volume_zscore_threshold": [1.5, 1.8, 2.0, 2.3, 2.5],
    "imbalance_threshold":     [0.50, 0.52, 0.55],
    "rr_ratio":                [1.5, 2.0, 2.5],
}
# Parametri fissi
FIXED = {
    "breakout_lookback":  20,
    "sl_atr_multiplier":  1.5,
    "symbol":             SYMBOL,
    "instrument":         "BTC-PERPETUAL",
}


def make_config(vol_z: float, imb: float, rr: float):
    from config import VolumeBreakoutConfig
    return VolumeBreakoutConfig(
        name=f"VB_z{vol_z}_i{imb}_rr{rr}",
        volume_zscore_threshold=vol_z,
        imbalance_threshold=imb,
        rr_ratio=rr,
        **FIXED,
    )


def run_single(vol_z: float, imb: float, rr: float, candles: List[Dict]) -> Dict:
    from src.strategies.volume_breakout import VolumeBreakoutStrategy
    config  = make_config(vol_z, imb, rr)
    trades  = run_strategy_backtest(VolumeBreakoutStrategy, config, candles, SYMBOL)
    metrics = full_report(trades)
    return {
        "vol_z":  vol_z,
        "imb":    imb,
        "rr":     rr,
        "trades": len(trades),
        "wr":     metrics.get("winrate_pct", 0.0),
        "sharpe": metrics.get("sharpe", 0.0),
        "calmar": metrics.get("calmar", 0.0),
        "pnl_pct": metrics.get("total_return_pct", 0.0),
        "pf":     metrics.get("profit_factor", 0.0),
        "exp_r":  metrics.get("expectancy_r", 0.0),
        "max_dd": metrics.get("max_drawdown_pct", 0.0),
        "error":  metrics.get("error", ""),
    }


def main():
    print("\nVolumeBreakout Parameter Sweep")
    print("=" * 60)

    candles = load_or_download_candles(SYMBOL, DAYS)
    print(f"Dataset: {len(candles):,} candles — {candles[0]['timestamp_ms']} -> {candles[-1]['timestamp_ms']}")

    combos = list(product(
        GRID["volume_zscore_threshold"],
        GRID["imbalance_threshold"],
        GRID["rr_ratio"],
    ))
    total = len(combos)
    print(f"Combinations: {total}  (each ~25-35s)")
    print(f"Estimated time: {total * 30 / 60:.0f} min\n")
    print("Running", flush=True)

    results = []
    t_start = time.time()
    for idx, (vol_z, imb, rr) in enumerate(combos, 1):
        r = run_single(vol_z, imb, rr, candles)
        results.append(r)
        elapsed = time.time() - t_start
        eta     = elapsed / idx * (total - idx)
        print(
            f"  [{idx:3d}/{total}] z={vol_z} imb={imb} rr={rr} "
            f"-> {r['trades']} trades  WR={r['wr']:.1f}%  "
            f"E={r['exp_r']:+.3f}R  ETA {eta/60:.1f}min",
            flush=True,
        )

    # Filtra run con almeno 20 trade
    valid = [r for r in results if r["trades"] >= 20 and not r["error"]]
    valid.sort(key=lambda x: x["exp_r"], reverse=True)

    # ---- Top 20 per expectancy_R ----
    print(f"\n{'='*80}")
    print("TOP 20 — sorted by Expectancy R  (filter: trades >= 20)")
    print(f"{'='*80}")
    hdr = (f"{'vol_z':>6} {'imb':>5} {'rr':>4} | "
           f"{'Trades':>6} {'WR%':>6} {'E(R)':>7} {'Sharpe':>7} "
           f"{'Calmar':>7} {'PF':>6} {'MaxDD%':>7}")
    print(hdr)
    print("-" * 80)
    for r in valid[:20]:
        print(
            f"  {r['vol_z']:>4.1f}  {r['imb']:>5.2f}  {r['rr']:>3.1f} | "
            f"{r['trades']:>6d} {r['wr']:>5.1f}% {r['exp_r']:>+7.4f} "
            f"{r['sharpe']:>7.3f} {r['calmar']:>7.3f} "
            f"{min(r['pf'],99.9):>6.2f} {r['max_dd']:>6.2f}%"
        )

    # ---- Baseline (default params) ----
    base = next((r for r in results if r["vol_z"] == 2.0 and r["imb"] == 0.55 and r["rr"] == 2.5), None)
    if base:
        print(f"\n--- Default params (z=2.0, imb=0.55, rr=2.5) ---")
        print(
            f"  Trades={base['trades']}  WR={base['wr']:.1f}%  "
            f"E={base['exp_r']:+.4f}R  Sharpe={base['sharpe']:.3f}  "
            f"Calmar={base['calmar']:.3f}  PF={base['pf']:.2f}  MaxDD={base['max_dd']:.2f}%"
        )

    # ---- Best per ogni metrica ----
    if valid:
        best_wr  = max(valid, key=lambda x: x["wr"])
        best_sh  = max(valid, key=lambda x: x["sharpe"])
        best_pf  = max(valid, key=lambda x: min(x["pf"], 99))
        print(f"\n--- Best by metric ---")
        print(f"  WR:     z={best_wr['vol_z']} imb={best_wr['imb']} rr={best_wr['rr']}  "
              f"-> WR={best_wr['wr']:.1f}%  E={best_wr['exp_r']:+.4f}R")
        print(f"  Sharpe: z={best_sh['vol_z']} imb={best_sh['imb']} rr={best_sh['rr']}  "
              f"-> Sharpe={best_sh['sharpe']:.3f}  E={best_sh['exp_r']:+.4f}R")
        print(f"  PF:     z={best_pf['vol_z']} imb={best_pf['imb']} rr={best_pf['rr']}  "
              f"-> PF={best_pf['pf']:.3f}  E={best_pf['exp_r']:+.4f}R")

    # Salva
    out = "sweep_vb_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nAll results saved to: {out}")
    print(f"Total time: {(time.time() - t_start)/60:.1f} min")


if __name__ == "__main__":
    main()
