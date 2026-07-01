#!/usr/bin/env python3
"""
Statistical validation layer on top of existing backtest outputs.

Does NOT modify strategy logic or parameters. Reads / re-runs backtest harnesses
with optional cost scaling and date windows, then reports t-stats, bootstrap CIs,
cost stress, MC beta attribution, portfolio path metrics, DSR, and walk-forward OOS.

Usage: python scripts/stat_validation.py
"""
from __future__ import annotations

import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest_macro_core import run_macro
from backtest_new_strategies import HistoricalKlineProvider, build_candles, run
from config import FundingSqueezeConfig, TrendBreakdownConfig
from equity_sim import simulate_portfolio
from multicycle_research import load_4y, load_funding_4y, resample
from src.strategies.funding_squeeze import FundingSqueezeStrategy
from src.strategies.trend_breakdown import TrendBreakdownStrategy
from strategy_lab import SLIPPAGE, TAKER_FEE

BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 42
ROUNDTRIP_FEE_PCT = 2 * TAKER_FEE * 100  # fee-only component in net_pct (percent points)
OOS_START = pd.Timestamp("2025-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-07-01", tz="UTC")  # through Jun 2026
REPORT_PATH = "data/research/stat_validation_report.md"

# Legs to analyse (prompt specification)
LEG_ORDER = [
    "TB_short_BTC",
    "TB_long_BTC",
    "TB_long_ETH",
    "FS_BTC",
    "FS_ETH",
    "MC_BTC",
    "TB+FS_portfolio",
]


@dataclass
class LegStats:
    leg: str
    n: int = 0
    mean_bps: float = 0.0
    std_bps: float = 0.0
    median_bps: float = 0.0
    win_rate: float = 0.0
    pf: float = 0.0
    t_stat: float = 0.0
    p_value: float = 1.0
    ci_mean_lo: float = 0.0
    ci_mean_hi: float = 0.0
    ci_pf_lo: float = 0.0
    ci_pf_hi: float = 0.0
    pf_ci_includes_1: bool = True
    n_below_30: bool = True
    t_below_2: bool = True
    period: str = "full"
    extra: Dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ #
# STEP 0 — schema helpers
# ------------------------------------------------------------------ #

def net_bps(series: pd.Series) -> pd.Series:
    """net_pct is stored as percent points (e.g. 0.41 = 0.41%); bps = * 100."""
    return series * 100.0


def inspect_existing_outputs() -> str:
    """Print schema summary of files already on disk."""
    lines = ["## STEP 0 — Schema inspection\n"]
    json_path = "data/research/new_strategies_results.json"
    cache_path = "data/research/c4_trades_cache.pkl"

    if os.path.exists(json_path):
        import json
        with open(json_path) as f:
            j = json.load(f)
        lines.append(
            f"- `new_strategies_results.json`: summary only (no per-trade rows). "
            f"Keys: {list(j.keys())}. Fields per strategy: {list(next(iter(j.values())).keys())}."
        )
    else:
        lines.append("- `new_strategies_results.json`: **missing**")

    if os.path.exists(cache_path):
        import pickle
        with open(cache_path, "rb") as f:
            tactical, mc = pickle.load(f)
        lines.append(
            f"- `c4_trades_cache.pkl`: tactical {tactical.shape}, columns {list(tactical.columns)}; "
            f"mc {mc.shape}, columns {list(mc.columns)}."
        )
        lines.append(
            "  - tactical: `direction` -1=short +1=long; `net_pct`/`gross_pct` in **percent points** "
            "(bps = net_pct x 100); `strategy` in {TB, FS}; BTC-only combined run."
        )
        lines.append(
            "  - mc: roundtrip spans with `net_pct` (percent), no direction column."
        )
    else:
        lines.append("- `c4_trades_cache.pkl`: **missing** (will be built during run)")

    lines.append(
        "\nPer-leg ETH / side splits are **not** in cached files — regenerated via "
        "`run()` on BTC/ETH datasets inside this script.\n"
    )
    return "\n".join(lines)


def slice_m1(m1: pd.DataFrame, start: Optional[pd.Timestamp],
               end: Optional[pd.Timestamp]) -> pd.DataFrame:
    out = m1
    if start is not None:
        out = out[out.index >= start]
    if end is not None:
        out = out[out.index < end]
    return out


def run_tb_trades(m1: pd.DataFrame, symbol: str, cost_mult: float = 1.0) -> pd.DataFrame:
    sym = symbol.upper()
    h1 = resample(m1, "1h")
    d1 = resample(m1, "1D")
    funding = load_funding_4y(sym)
    if funding is None:
        funding = pd.Series([0.0], index=[m1.index[0]])
    provider = HistoricalKlineProvider(
        build_candles(h1, 3_600_000), build_candles(d1, 86_400_000), funding)
    cfg = TrendBreakdownConfig(name=f"TB {sym}")
    cfg.symbol = f"{sym}USDT"
    cfg.instrument = f"{sym}-PERPETUAL"
    if sym == "ETH":
        cfg.enable_short = False
    t = run(TrendBreakdownStrategy, cfg, m1, provider, cost_mult=cost_mult)
    if len(t):
        t["symbol"] = sym
        t["strategy"] = "TB"
    return t


def run_fs_trades(m1: pd.DataFrame, symbol: str, cost_mult: float = 1.0) -> pd.DataFrame:
    sym = symbol.upper()
    h1 = resample(m1, "1h")
    d1 = resample(m1, "1D")
    funding = load_funding_4y(sym)
    if funding is None:
        raise FileNotFoundError(f"No funding file for {sym}")
    provider = HistoricalKlineProvider(
        build_candles(h1, 3_600_000), build_candles(d1, 86_400_000), funding)
    cfg = FundingSqueezeConfig(name=f"FS {sym}")
    cfg.symbol = f"{sym}USDT"
    cfg.instrument = f"{sym}-PERPETUAL"
    t = run(FundingSqueezeStrategy, cfg, m1, provider, cost_mult=cost_mult)
    if len(t):
        t["symbol"] = sym
        t["strategy"] = "FS"
    return t


def build_leg_dataframes(
    m1_btc: pd.DataFrame,
    m1_eth: pd.DataFrame,
    cost_mult: float = 1.0,
) -> Dict[str, pd.DataFrame]:
    """Run harnesses and split into named legs."""
    legs: Dict[str, pd.DataFrame] = {}

    tb_btc = run_tb_trades(m1_btc, "BTC", cost_mult)
    if len(tb_btc):
        legs["TB_short_BTC"] = tb_btc[tb_btc["direction"] == -1].copy()
        legs["TB_long_BTC"] = tb_btc[tb_btc["direction"] == 1].copy()
    else:
        legs["TB_short_BTC"] = pd.DataFrame()
        legs["TB_long_BTC"] = pd.DataFrame()

    tb_eth = run_tb_trades(m1_eth, "ETH", cost_mult)
    legs["TB_long_ETH"] = tb_eth[tb_eth["direction"] == 1].copy() if len(tb_eth) else pd.DataFrame()

    fs_btc = run_fs_trades(m1_btc, "BTC", cost_mult)
    legs["FS_BTC"] = fs_btc

    fs_eth = run_fs_trades(m1_eth, "ETH", cost_mult)
    legs["FS_ETH"] = fs_eth

    mc_trades, mc_eq = run_macro(m1_btc)
    legs["MC_BTC"] = mc_trades
    legs["_mc_eq"] = mc_eq  # internal

    tactical_parts = [v for k, v in legs.items() if k.startswith(("TB_", "FS_")) and len(v)]
    if tactical_parts:
        port = pd.concat(tactical_parts, ignore_index=True).sort_values("entry_ts")
        # portfolio prompt = TB+FS on BTC from original docs; use BTC TB+FS only
        btc_tactical = pd.concat(
            [legs.get("TB_short_BTC", pd.DataFrame()),
             legs.get("TB_long_BTC", pd.DataFrame()),
             legs.get("FS_BTC", pd.DataFrame())],
            ignore_index=True,
        )
        legs["TB+FS_portfolio"] = btc_tactical.sort_values("entry_ts") if len(btc_tactical) else pd.DataFrame()
    else:
        legs["TB+FS_portfolio"] = pd.DataFrame()

    return legs


# ------------------------------------------------------------------ #
# A1–A3 statistics
# ------------------------------------------------------------------ #

def profit_factor(bps: np.ndarray) -> float:
    wins = bps[bps > 0].sum()
    losses = bps[bps < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / abs(losses))


def bootstrap_ci(values: np.ndarray, stat_fn, n: int = BOOTSTRAP_N,
                 seed: int = BOOTSTRAP_SEED) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    if len(values) == 0:
        return 0.0, 0.0
    boots = np.empty(n)
    for i in range(n):
        sample = values[rng.integers(0, len(values), len(values))]
        boots[i] = stat_fn(sample)
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def analyse_leg(leg: str, trades: pd.DataFrame, period: str = "full") -> LegStats:
    st = LegStats(leg=leg, period=period)
    if trades is None or len(trades) == 0:
        return st

    if leg == "MC_BTC":
        bps = trades["net_pct"].values * 100.0
    else:
        bps = net_bps(trades["net_pct"]).values

    st.n = len(bps)
    st.mean_bps = float(np.mean(bps))
    st.std_bps = float(np.std(bps, ddof=1)) if st.n > 1 else 0.0
    st.median_bps = float(np.median(bps))
    st.win_rate = float((bps > 0).mean() * 100)
    st.pf = profit_factor(bps)

    if st.n > 1 and st.std_bps > 0:
        st.t_stat = float(st.mean_bps / (st.std_bps / np.sqrt(st.n)))
        st.p_value = float(2 * stats.t.sf(abs(st.t_stat), df=st.n - 1))
    st.n_below_30 = st.n < 30
    st.t_below_2 = abs(st.t_stat) < 2.0

    st.ci_mean_lo, st.ci_mean_hi = bootstrap_ci(bps, np.mean)
    st.ci_pf_lo, st.ci_pf_hi = bootstrap_ci(bps, profit_factor)
    st.pf_ci_includes_1 = st.ci_pf_lo <= 1.0 <= st.ci_pf_hi
    return st


def stress_costs_fallback(trades: pd.DataFrame, mults: List[float]) -> Dict[float, Dict[str, float]]:
    """Re-scale fee component; slippage already in gross_pct at 1×."""
    if trades is None or len(trades) == 0:
        return {m: {"mean_bps": 0.0, "pf": 0.0} for m in mults}

    gross = trades["gross_pct"].values if "gross_pct" in trades.columns else trades["net_pct"].values
    results = {}
    for m in mults:
        fee_pct = ROUNDTRIP_FEE_PCT * m
        if "gross_pct" in trades.columns:
            net_pct = gross - fee_pct
        else:
            # MC trades: only net_pct; approximate stress by scaling fee drag
            net_pct = trades["net_pct"].values - (ROUNDTRIP_FEE_PCT * (m - 1.0))
        bps = net_pct * 100.0
        results[m] = {"mean_bps": float(np.mean(bps)), "pf": profit_factor(bps)}
    return results


def stress_costs_from_legs(
    legs: Dict[str, pd.DataFrame],
    mults: List[float],
) -> Dict[str, Dict[float, Dict[str, float]]]:
    """Apply fee scaling fallback on trades already run at 1× (gross_pct available)."""
    out: Dict[str, Dict[float, Dict[str, float]]] = {}
    for leg in LEG_ORDER:
        t = legs.get(leg, pd.DataFrame())
        out[leg] = stress_costs_fallback(t, mults)
        if leg != "MC_BTC" and len(t) and "gross_pct" in t.columns:
            be = breakeven_cost_mult(t)
            for m in mults:
                out[leg][m]["be_mult"] = be
    return out


def stress_costs_rerun(
    legs_at_1x: Dict[str, pd.DataFrame],
    mults: List[float],
) -> Dict[str, Dict[float, Dict[str, float]]]:
    """Stress costs via fallback on 1× trades (slippage in gross; fee scaled)."""
    return stress_costs_from_legs(legs_at_1x, mults)


def breakeven_cost_mult(trades: pd.DataFrame) -> Optional[float]:
    if trades is None or len(trades) == 0 or "gross_pct" not in trades.columns:
        return None
    gross_bps = trades["gross_pct"].values * 100.0
    mean_gross = float(np.mean(gross_bps))
    if ROUNDTRIP_FEE_PCT <= 0:
        return None
    # mean_net_bps = mean_gross_bps - ROUNDTRIP_FEE_PCT*100 * mult  (fee_pct in percent -> *100 for bps)
    fee_bps_per_mult = ROUNDTRIP_FEE_PCT * 100.0
    if fee_bps_per_mult == 0:
        return None
    return mean_gross / fee_bps_per_mult


# ------------------------------------------------------------------ #
# A5 MC beta attribution
# ------------------------------------------------------------------ #

def mc_beta_attribution(m1_btc: pd.DataFrame, mc_eq: pd.Series) -> Dict[str, Any]:
    daily = resample(m1_btc, "1D")["close"]
    btc_ret = daily.pct_change().dropna()
    mc_ret = mc_eq.pct_change().dropna()
    aligned = pd.concat([mc_ret.rename("mc"), btc_ret.rename("btc")], axis=1).dropna()
    if len(aligned) < 30:
        return {"error": "insufficient daily observations"}

    y = aligned["mc"].values
    x = aligned["btc"].values
    X = np.column_stack([np.ones(len(x)), x])
    coef, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha_d, beta = float(coef[0]), float(coef[1])
    resid = y - X @ coef
    dof = len(y) - 2
    mse = np.sum(resid ** 2) / dof
    cov = mse * np.linalg.inv(X.T @ X)
    se_alpha = np.sqrt(cov[0, 0])
    t_alpha = alpha_d / se_alpha if se_alpha > 0 else 0.0
    p_alpha = 2 * stats.t.sf(abs(t_alpha), df=dof)

    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum(resid ** 2) / ss_tot if ss_tot > 0 else 0.0

    alpha_ann_pct = alpha_d * 365 * 100
    hedged = aligned["mc"] - beta * aligned["btc"]
    alpha_cum = (1 + hedged).cumprod()
    alpha_cum_total = (alpha_cum.iloc[-1] - 1) * 100

    mc_total = (mc_eq.iloc[-1] / mc_eq.iloc[0] - 1) * 100
    btc_total = (daily.iloc[-1] / daily.iloc[0] - 1) * 100
    beta_contrib_approx = beta * btc_total

    return {
        "beta": beta,
        "alpha_daily": alpha_d,
        "alpha_annualized_pct": alpha_ann_pct,
        "t_alpha": t_alpha,
        "p_alpha": p_alpha,
        "r2": r2,
        "mc_total_pct": mc_total,
        "btc_bh_pct": btc_total,
        "beta_contrib_approx_pct": beta_contrib_approx,
        "alpha_cum_pct": alpha_cum_total,
        "n_days": len(aligned),
    }


# ------------------------------------------------------------------ #
# A6 portfolio path metrics
# ------------------------------------------------------------------ #

def path_metrics(equity: pd.Series) -> Dict[str, float]:
    daily_rets = equity.pct_change().dropna()
    if len(daily_rets) == 0:
        return {}
    mean_d = daily_rets.mean()
    std_d = daily_rets.std(ddof=1)
    sharpe = mean_d / std_d * np.sqrt(365) if std_d > 0 else 0.0
    downside = daily_rets[daily_rets < 0]
    dd_std = downside.std(ddof=1) if len(downside) > 1 else 0.0
    sortino = mean_d / dd_std * np.sqrt(365) if dd_std > 0 else 0.0
    peak = equity.cummax()
    mdd = ((peak - equity) / peak).max() * 100
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    calmar = cagr / mdd if mdd > 0 else 0.0
    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "maxdd_pct": mdd,
        "cagr_pct": cagr,
        "calmar": calmar,
        "total_pct": (equity.iloc[-1] / equity.iloc[0] - 1) * 100,
    }


def portfolio_metrics_from_legs(legs_full: Dict[str, pd.DataFrame], m1_btc: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    daily = resample(m1_btc, "1D")
    tactical = pd.concat(
        [legs_full.get("TB_short_BTC", pd.DataFrame()),
         legs_full.get("TB_long_BTC", pd.DataFrame()),
         legs_full.get("FS_BTC", pd.DataFrame())],
        ignore_index=True,
    ).sort_values("entry_ts")
    mc_trades = legs_full.get("MC_BTC", pd.DataFrame())

    configs = {
        "baseline_fix1_mc_fixed": ("fix1", False, "fixed"),
        "adopted_fix1_volT30": ("fix1", False, "volT30"),
    }
    out = {}
    for name, (risk, derisk, mc_mode) in configs.items():
        eq, _ = simulate_portfolio(daily, tactical, mc_trades, risk, derisk, mc_mode)
        out[name] = path_metrics(eq)
    return out


# ------------------------------------------------------------------ #
# A7 Deflated Sharpe / trial count
# ------------------------------------------------------------------ #

def count_trials() -> int:
    """Conservative trial count from plan + disabled strategies."""
    disabled = [
        "VolumeBreakout", "MeanReversion", "LiquidationSqueeze", "ImbalanceScalp",
        "NY_Brings", "WM_Formation", "SmartMoney", "IronCondor",
    ]
    plan_variants = [
        "TB_short_baseline", "TB_long_baseline", "TB_long_noTP_168h",
        "FS_naive", "FS_macro_gated", "FS_cap_funding",
        "MC_naive_SMA200", "MC_chandelier_k_sweep",
        "MC_isteresi", "MC_slope", "MC_confirm_2d",
        "TB_trailing_C2", "C4_equity_grid_18", "C5_dip_buy", "C6_FS_long_mirror",
        "ETH_TB_short", "ETH_TB_long", "ETH_FS", "ETH_MC",
    ]
    n = len(disabled) + len(plan_variants)
    # Parse PLAN for explicit bocciate/promosse mentions
    plan_path = "microevolutive/PLAN_BULL_EVOLUTION.md"
    if os.path.exists(plan_path):
        with open(plan_path, encoding="utf-8") as f:
            text = f.read()
        n += len(re.findall(r"BOCCIAT", text, re.I))
    return max(n, 15)


def expected_max_sharpe(n_trials: int, n_obs: int) -> float:
    """Bailey & López de Prado (2014) — expected max SR under null."""
    euler = 0.5772156649
    z1 = stats.norm.ppf(1 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    return ((1 - euler) * z1 + euler * z2) * np.sqrt(max(n_obs - 1, 1)) / np.sqrt(max(n_obs, 1))


def deflated_sharpe_prob(sharpe: float, n_obs: int, n_trials: int,
                         skew: float = 0.0, kurtosis: float = 3.0) -> Dict[str, float]:
  """PSR / DSR: P(true SR > 0) after selection bias."""
  sr_star = expected_max_sharpe(n_trials, n_obs)
  var_sr = (1 + 0.5 * sharpe ** 2 - skew * sharpe + (kurtosis - 3) / 4 * sharpe ** 2)
  var_sr /= max(n_obs - 1, 1)
  if var_sr <= 0:
    return {"dsr_prob": 0.0, "sr_star": sr_star, "stderr_sr": 0.0}
  z = (sharpe - sr_star) / np.sqrt(var_sr)
  return {"dsr_prob": float(stats.norm.cdf(z)), "sr_star": sr_star, "stderr_sr": float(np.sqrt(var_sr))}


# ------------------------------------------------------------------ #
# Verdict
# ------------------------------------------------------------------ #

def classify_leg(
    full: LegStats,
    oos: Optional[LegStats],
    stress_15: Dict[str, float],
    is_mc_beta: bool = False,
) -> str:
    if is_mc_beta:
        r2 = full.extra.get("r2", 0)
        beta = abs(full.extra.get("beta", 0))
        alpha_sig = full.extra.get("alpha_significant", False)
        # Linear beta exposure dominates
        if r2 > 0.5 and beta > 0.5:
            return "BETA"
        # Low R2: not classic beta; few roundtrips -> cannot prove timing skill
        if full.n_below_30 or full.t_below_2:
            return "PLAUSIBILE" if alpha_sig or full.mean_bps > 0 else "RUMORE"
        return "PLAUSIBILE"

    edge_gone = stress_15.get("mean_bps", 0) <= 0
    if full.pf_ci_includes_1 and full.t_below_2 and edge_gone:
        return "RUMORE"
    if (not full.t_below_2 and full.n >= 30 and not full.pf_ci_includes_1
            and oos and not oos.t_below_2 and not oos.pf_ci_includes_1):
        return "PROVATA"
    if full.pf_ci_includes_1 or full.t_below_2 or full.n_below_30 or edge_gone:
        return "PLAUSIBILE" if full.mean_bps > 0 else "RUMORE"
    return "PLAUSIBILE"


# ------------------------------------------------------------------ #
# Formatting
# ------------------------------------------------------------------ #

def fmt_leg_table(rows: List[LegStats], title: str) -> str:
    lines = [f"\n### {title}\n"]
    hdr = f"| {'Leg':<18} | {'N':>4} | {'mean bps':>9} | {'std':>8} | {'WR%':>5} | {'PF':>5} | {'t':>6} | {'p':>6} | {'CI mean':>17} | {'CI PF':>15} | flags |"
    sep = "|" + "-" * 20 + "|" + "-" * 6 + "|" + "-" * 11 + "|" + "-" * 10 + "|" + "-" * 7 + "|" + "-" * 7 + "|" + "-" * 8 + "|" + "-" * 8 + "|" + "-" * 19 + "|" + "-" * 17 + "|" + "-" * 10 + "|"
    lines.extend([hdr, sep])
    for r in rows:
        flags = []
        if r.n_below_30:
            flags.append("N<30")
        if r.t_below_2:
            flags.append("t<2")
        if r.pf_ci_includes_1:
            flags.append("PF~1")
        ci_m = f"[{r.ci_mean_lo:+.0f},{r.ci_mean_hi:+.0f}]"
        ci_p = f"[{r.ci_pf_lo:.2f},{r.ci_pf_hi:.2f}]"
        pf_s = f"{r.pf:.2f}" if np.isfinite(r.pf) else "inf"
        lines.append(
            f"| {r.leg:<18} | {r.n:>4} | {r.mean_bps:>+9.1f} | {r.std_bps:>8.1f} | "
            f"{r.win_rate:>5.1f} | {pf_s:>5} | {r.t_stat:>+6.2f} | {r.p_value:>6.3f} | "
            f"{ci_m:>17} | {ci_p:>15} | {','.join(flags) or '-'} |"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def main():
    print("=" * 72)
    print("CryptoQuantix — Statistical Validation")
    print("=" * 72)

    schema = inspect_existing_outputs()
    print(schema)

    print("\nLoading datasets...")
    m1_btc = load_4y("BTC")
    m1_eth = load_4y("ETH")
    print(f"  BTC: {m1_btc.index[0]:%Y-%m-%d} -> {m1_btc.index[-1]:%Y-%m-%d} ({len(m1_btc):,} bars)")
    print(f"  ETH: {m1_eth.index[0]:%Y-%m-%d} -> {m1_eth.index[-1]:%Y-%m-%d} ({len(m1_eth):,} bars)")

    report_parts = [
        f"# Statistical Validation Report\n",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n",
        schema,
    ]

    # ---- Full sample ----
    print("\nRunning full-sample backtests (cost_mult=1.0)...")
    legs_full = build_leg_dataframes(m1_btc, m1_eth, cost_mult=1.0)
    mc_eq = legs_full.pop("_mc_eq")

    full_stats = []
    for leg in LEG_ORDER:
        st = analyse_leg(leg, legs_full.get(leg, pd.DataFrame()), period="full")
        full_stats.append(st)

    tbl_full = fmt_leg_table(full_stats, "A1-A3 Full sample (2022-06 -> 2026-06)")
    print(tbl_full)
    report_parts.append(tbl_full)

    # ---- A4 stress costs ----
    print("\nA4 - Cost stress (fee scaled 1.0 / 1.5 / 2.0 on 1x trades)...")
    mults = [1.0, 1.5, 2.0]
    stress = stress_costs_rerun(legs_full, mults)
    stress_lines = ["\n### A4 — Cost stress\n", "| Leg | mult | mean bps | PF | BE mult |",
                    "|-----|------|----------|-----|---------|"]
    be_mults = {}
    for leg in LEG_ORDER:
        t = legs_full.get(leg, pd.DataFrame())
        be_mults[leg] = breakeven_cost_mult(t)
        for m in mults:
            s = stress.get(leg, {}).get(m, {})
            be = f"{be_mults[leg]:.2f}" if be_mults[leg] is not None else "n/a"
            stress_lines.append(
                f"| {leg} | {m:.1f} | {s.get('mean_bps', 0):+.1f} | {s.get('pf', 0):.2f} | {be} |"
            )
    stress_block = "\n".join(stress_lines)
    print(stress_block)
    report_parts.append(stress_block)

    # ---- A5 MC beta ----
    print("\nA5 — MC beta attribution...")
    beta_info = mc_beta_attribution(m1_btc, mc_eq)
    beta_lines = ["\n### A5 — MacroCore beta attribution\n"]
    if "error" in beta_info:
        beta_lines.append(f"Error: {beta_info['error']}")
    else:
        beta_lines.extend([
            f"- OLS daily: r_MC = alpha + beta * r_BTC  (n={beta_info['n_days']} days)",
            f"- beta = {beta_info['beta']:.3f}",
            f"- alpha (daily) = {beta_info['alpha_daily']*100:.4f}%",
            f"- alpha (annualized) = {beta_info['alpha_annualized_pct']:+.1f}%",
            f"- t-stat(alpha) = {beta_info['t_alpha']:.2f}, p = {beta_info['p_alpha']:.4f}",
            f"- R² = {beta_info['r2']:.3f}",
            f"- MC total return = {beta_info['mc_total_pct']:+.1f}%",
            f"- BTC buy&hold = {beta_info['btc_bh_pct']:+.1f}%",
            f"- Approx beta contribution = {beta_info['beta_contrib_approx_pct']:+.1f}%",
            f"- Cumulative alpha (hedged) = {beta_info['alpha_cum_pct']:+.1f}%",
            "",
            textwrap.dedent(f"""\
                **Conclusione:** del +{beta_info['mc_total_pct']:.0f}% MC, circa
                {beta_info['beta_contrib_approx_pct']:+.0f}% è spiegabile come esposizione beta
                (beta~{beta_info['beta']:.2f} * B&H BTC); la componente alpha cumulata
                hedged è {beta_info['alpha_cum_pct']:+.1f}% (alpha giornaliero
                {'significativo' if beta_info['p_alpha'] < 0.05 else 'NON significativo'} a 5%).
            """),
        ])
        mc_st = next(s for s in full_stats if s.leg == "MC_BTC")
        mc_st.extra = {
            "alpha_significant": beta_info["p_alpha"] < 0.05,
            "r2": beta_info["r2"],
            **beta_info,
        }
    beta_block = "\n".join(beta_lines)
    print(beta_block)
    report_parts.append(beta_block)

    # ---- A6 portfolio ----
    print("\nA6 — Portfolio path metrics...")
    port = portfolio_metrics_from_legs(legs_full, m1_btc)
    port_lines = ["\n### A6 — Portfolio path-dependent metrics\n",
                  "| Config | Total% | CAGR% | maxDD% | Sharpe | Sortino | Calmar |",
                  "|--------|--------|-------|--------|--------|---------|--------|"]
    for name, m in port.items():
        port_lines.append(
            f"| {name} | {m.get('total_pct', 0):+.1f} | {m.get('cagr_pct', 0):.1f} | "
            f"{m.get('maxdd_pct', 0):.1f} | {m.get('sharpe', 0):.2f} | "
            f"{m.get('sortino', 0):.2f} | {m.get('calmar', 0):.2f} |"
        )
    port_block = "\n".join(port_lines)
    print(port_block)
    report_parts.append(port_block)

    # ---- A7 DSR ----
    n_trials = count_trials()
    adopted_sharpe = port.get("adopted_fix1_volT30", {}).get("sharpe", 0.0)
    n_days = len(resample(m1_btc, "1D"))
    dsr = deflated_sharpe_prob(adopted_sharpe, n_days, n_trials)
    dsr_lines = [
        "\n### A7 — Multiple testing / Deflated Sharpe\n",
        f"- Estimated trials (conservative): **{n_trials}**",
        f"- Portfolio Sharpe (adopted volT30): **{adopted_sharpe:.2f}**",
        f"- Expected max SR under null (SR*): **{dsr['sr_star']:.2f}**",
        f"- DSR P(SR > 0 | selection bias): **{dsr['dsr_prob']:.1%}**",
    ]
    dsr_block = "\n".join(dsr_lines)
    print(dsr_block)
    report_parts.append(dsr_block)

    # ---- B Walk-forward OOS ----
    print("\nB - Walk-forward OOS (TEST: 2025-01 -> 2026-06)...")
    m1_btc_oos = slice_m1(m1_btc, OOS_START, OOS_END)
    m1_eth_oos = slice_m1(m1_eth, OOS_START, OOS_END)
    legs_oos = build_leg_dataframes(m1_btc_oos, m1_eth_oos, cost_mult=1.0)
    legs_oos.pop("_mc_eq", None)

    oos_stats = []
    for leg in LEG_ORDER:
        oos_stats.append(analyse_leg(leg, legs_oos.get(leg, pd.DataFrame()), period="OOS"))

    tbl_oos = fmt_leg_table(oos_stats, "B — OOS TEST period only")
    print(tbl_oos)
    report_parts.append(tbl_oos)

    compare_lines = [
        "\n### B — In-sample vs OOS comparison\n",
        "| Leg | IS mean bps | OOS mean bps | IS PF | OOS PF | IS t | OOS t | degradation |",
        "|-----|-------------|--------------|-------|--------|------|-------|-------------|",
    ]
    for f, o in zip(full_stats, oos_stats):
        deg = "OOS worse" if o.mean_bps < f.mean_bps else "OOS better/similar"
        compare_lines.append(
            f"| {f.leg} | {f.mean_bps:+.1f} | {o.mean_bps:+.1f} | {f.pf:.2f} | {o.pf:.2f} | "
            f"{f.t_stat:+.2f} | {o.t_stat:+.2f} | {deg} |"
        )
    compare_lines.append(
        "\n> **Nota metodologica:** parametri fissi ai default `.env`, scelti vedendo "
        "l'intero storico 2022–2026. Questo OOS è un *sanity check semi-contaminato*, "
        "non prova definitiva di generalizzazione.\n"
    )
    compare_block = "\n".join(compare_lines)
    print(compare_block)
    report_parts.append(compare_block)

    # ---- Final verdict ----
    verdict_lines = ["\n### Verdetto per gamba\n",
                     "| Leg | Verdict | Rationale |",
                     "|-----|---------|-----------|"]
    oos_map = {s.leg: s for s in oos_stats}
    for f in full_stats:
        leg = f.leg
        s15 = stress.get(leg, {}).get(1.5, {})
        verdict = classify_leg(f, oos_map.get(leg), s15, is_mc_beta=(leg == "MC_BTC"))
        reasons = []
        if f.n_below_30:
            reasons.append(f"N={f.n}")
        if f.t_below_2:
            reasons.append(f"t={f.t_stat:.2f}")
        if f.pf_ci_includes_1:
            reasons.append("PF CI includes 1")
        if s15.get("mean_bps", 0) <= 0:
            reasons.append("edge<=0 at 1.5x costs")
        if leg == "MC_BTC" and f.extra.get("p_alpha", 1) >= 0.05:
            reasons.append("alpha n.s.")
        if leg == "MC_BTC" and f.extra.get("r2", 0) < 0.1:
            reasons.append("low R2 vs BTC")
        verdict_lines.append(f"| {leg} | **{verdict}** | {'; '.join(reasons) or 'passes filters'} |")

    verdict_block = "\n".join(verdict_lines)
    print(verdict_block)
    report_parts.append(verdict_block)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(report_parts))
    print(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
