"""
MonteCarloSimulator — bootstrap resampling of trade returns.

Computes:
  - Distribution of expected P&L (percentiles)
  - Distribution of max drawdown
  - Ruin probability (equity drops below threshold)
  - Confidence intervals for Sharpe, expectancy
  - Path visualization data

Usage:
    mc = MonteCarloSimulator(n_simulations=1000)
    results = mc.run(trades, initial_equity=10000)
    mc.print_summary(results)
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResults:
    """Results from a Monte Carlo simulation run."""
    n_simulations: int
    n_trades_per_sim: int
    initial_equity: float

    # Final equity distribution
    equity_p5: float = 0.0
    equity_p25: float = 0.0
    equity_p50: float = 0.0
    equity_p75: float = 0.0
    equity_p95: float = 0.0

    # Max drawdown distribution
    dd_p50: float = 0.0
    dd_p75: float = 0.0
    dd_p95: float = 0.0

    # Probabilities
    ruin_probability: float = 0.0      # P(equity < ruin_threshold)
    profit_probability: float = 0.0    # P(final_equity > initial_equity)

    # Sharpe confidence interval
    sharpe_mean: float = 0.0
    sharpe_ci_low: float = 0.0
    sharpe_ci_high: float = 0.0

    # Sample paths for visualization (list of equity curves)
    sample_paths: List[List[float]] = field(default_factory=list)

    # Run metadata
    run_time_sec: float = 0.0
    actual_winrate: float = 0.0
    actual_expectancy: float = 0.0


class MonteCarloSimulator:
    """
    Bootstrap Monte Carlo simulation of trade sequence variability.

    Resamples historical trades with replacement to estimate:
    - Actual P&L distribution
    - Max drawdown distribution
    - Ruin probability
    """

    def __init__(
        self,
        n_simulations: int = 1000,
        ruin_threshold_pct: float = 0.5,   # lose 50% of equity = ruin
        n_sample_paths: int = 10,
        random_seed: int = None,
    ):
        self.n_simulations = n_simulations
        self.ruin_threshold_pct = ruin_threshold_pct
        self.n_sample_paths = n_sample_paths
        if random_seed is not None:
            np.random.seed(random_seed)

    def run(
        self,
        trades,
        initial_equity: float = 10000.0,
        n_trades: int = None,
    ) -> MonteCarloResults:
        """
        Run Monte Carlo simulation.

        Args:
            trades: List of BacktestTrade or dicts with pnl_usd field
            initial_equity: starting equity for each simulation
            n_trades: number of trades to simulate per run (default: same as history)

        Returns:
            MonteCarloResults
        """
        start = time.time()

        # Extract P&L array
        if not trades:
            logger.warning("[MC] No trades provided")
            return MonteCarloResults(
                n_simulations=self.n_simulations,
                n_trades_per_sim=0,
                initial_equity=initial_equity,
            )

        pnls = np.array([
            (t.pnl_usd if hasattr(t, "pnl_usd") else t.get("pnl_usd", 0))
            for t in trades
        ])

        r_multiples = np.array([
            (t.r_multiple if hasattr(t, "r_multiple") else t.get("r_multiple", 0))
            for t in trades
        ])

        n_trades = n_trades or len(pnls)
        ruin_threshold = initial_equity * self.ruin_threshold_pct

        logger.info(
            f"[MC] Running {self.n_simulations} simulations × "
            f"{n_trades} trades from {len(pnls)} historical trades"
        )

        final_equities = np.zeros(self.n_simulations)
        max_drawdowns = np.zeros(self.n_simulations)
        sharpes = np.zeros(self.n_simulations)
        sample_paths = []

        for i in range(self.n_simulations):
            # Resample with replacement
            sim_pnls = np.random.choice(pnls, size=n_trades, replace=True)
            sim_r = np.random.choice(r_multiples, size=n_trades, replace=True)

            # Compute equity path
            equity_path = np.concatenate([[initial_equity], initial_equity + np.cumsum(sim_pnls)])
            final_equities[i] = equity_path[-1]

            # Max drawdown
            peak = np.maximum.accumulate(equity_path)
            dd = (peak - equity_path) / peak * 100
            max_drawdowns[i] = np.max(dd)

            # Sharpe
            std_r = np.std(sim_r)
            sharpes[i] = np.mean(sim_r) / std_r if std_r > 0 else 0.0

            # Save sample paths
            if i < self.n_sample_paths:
                sample_paths.append(equity_path.tolist())

        # Compute statistics
        ruin_count = np.sum(final_equities < ruin_threshold)
        profit_count = np.sum(final_equities > initial_equity)

        actual_winrate = float(np.mean(pnls > 0))
        actual_expectancy = float(np.mean(r_multiples)) if len(r_multiples) > 0 else 0.0

        results = MonteCarloResults(
            n_simulations=self.n_simulations,
            n_trades_per_sim=n_trades,
            initial_equity=initial_equity,

            equity_p5=float(np.percentile(final_equities, 5)),
            equity_p25=float(np.percentile(final_equities, 25)),
            equity_p50=float(np.percentile(final_equities, 50)),
            equity_p75=float(np.percentile(final_equities, 75)),
            equity_p95=float(np.percentile(final_equities, 95)),

            dd_p50=float(np.percentile(max_drawdowns, 50)),
            dd_p75=float(np.percentile(max_drawdowns, 75)),
            dd_p95=float(np.percentile(max_drawdowns, 95)),

            ruin_probability=float(ruin_count / self.n_simulations),
            profit_probability=float(profit_count / self.n_simulations),

            sharpe_mean=float(np.mean(sharpes)),
            sharpe_ci_low=float(np.percentile(sharpes, 5)),
            sharpe_ci_high=float(np.percentile(sharpes, 95)),

            sample_paths=sample_paths,
            run_time_sec=time.time() - start,
            actual_winrate=actual_winrate,
            actual_expectancy=actual_expectancy,
        )

        logger.info(
            f"[MC] Done in {results.run_time_sec:.2f}s | "
            f"Ruin prob: {results.ruin_probability:.1%} | "
            f"P50 equity: ${results.equity_p50:,.2f} | "
            f"P95 DD: {results.dd_p95:.1f}%"
        )

        return results

    def print_summary(self, results: MonteCarloResults):
        """Print Monte Carlo summary to console."""
        print("\n" + "=" * 60)
        print(f"MONTE CARLO SIMULATION ({results.n_simulations} runs × {results.n_trades_per_sim} trades)")
        print("=" * 60)
        print(f"Initial Equity:     ${results.initial_equity:,.2f}")
        print(f"")
        print(f"--- Final Equity Distribution ---")
        print(f"  P5  (worst 5%):   ${results.equity_p5:,.2f}")
        print(f"  P25:              ${results.equity_p25:,.2f}")
        print(f"  P50 (median):     ${results.equity_p50:,.2f}")
        print(f"  P75:              ${results.equity_p75:,.2f}")
        print(f"  P95 (best 5%):    ${results.equity_p95:,.2f}")
        print(f"")
        print(f"--- Max Drawdown Distribution ---")
        print(f"  P50 (median):     {results.dd_p50:.1f}%")
        print(f"  P75:              {results.dd_p75:.1f}%")
        print(f"  P95 (worst 5%):   {results.dd_p95:.1f}%")
        print(f"")
        print(f"--- Probabilities ---")
        print(f"  Profitable:       {results.profit_probability:.1%}")
        print(f"  Ruin ({self.ruin_threshold_pct:.0%} loss): {results.ruin_probability:.1%}")
        print(f"")
        print(f"--- Sharpe (90% CI) ---")
        print(f"  Mean:             {results.sharpe_mean:.3f}")
        print(f"  Range:            [{results.sharpe_ci_low:.3f}, {results.sharpe_ci_high:.3f}]")
        print(f"")
        print(f"Historical WR:      {results.actual_winrate:.1%}")
        print(f"Historical E[R]:    {results.actual_expectancy:+.4f}")
        print(f"Run time:           {results.run_time_sec:.2f}s")
        print("=" * 60)
