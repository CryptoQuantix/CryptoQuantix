"""
JournalAnalytics — analysis and reporting from trade journal.

Reports:
  - Overall P&L, drawdown, Sharpe, win rate
  - Per-strategy performance breakdown
  - Per-regime performance (which setups work in which regimes)
  - R-multiple distribution
  - Consecutive win/loss streaks
  - Best/worst times of day
  - ML-ready feature export
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


class JournalAnalytics:
    """
    Analytics engine for trade journal data.

    Usage:
        analytics = JournalAnalytics(trade_logger)
        report = analytics.generate_report()
        print(report)
    """

    def __init__(self, trade_logger=None, trades: List[Dict] = None):
        self.trade_logger = trade_logger
        self._trades = trades  # optional: inject directly

    def _get_trades(self) -> List[Dict]:
        if self._trades:
            return self._trades
        if self.trade_logger:
            return self.trade_logger.get_recent_trades(n=10000, status="closed")
        return []

    # ------------------------------------------------------------------
    # Core metrics
    # ------------------------------------------------------------------

    def compute_basic_stats(self, trades: List[Dict] = None) -> Dict:
        """Compute basic P&L and trade statistics."""
        trades = trades or self._get_trades()
        if not trades:
            return {"error": "no trades"}

        r_multiples = [t.get("r_multiple", 0) for t in trades]
        pnls = [t.get("pnl_usd", 0) for t in trades]
        wins = [t for t in trades if t.get("win", False)]

        total = len(trades)
        win_count = len(wins)
        total_pnl = sum(pnls)

        # Equity curve
        equity_curve = [0.0]
        for p in pnls:
            equity_curve.append(equity_curve[-1] + p)

        max_dd, max_dd_pct = self._compute_max_drawdown(equity_curve)
        sharpe = self._compute_sharpe(r_multiples)
        sortino = self._compute_sortino(r_multiples)
        expectancy = float(np.mean(r_multiples)) if r_multiples else 0.0

        # Streaks
        max_win_streak, max_loss_streak = self._compute_streaks(trades)

        return {
            "total_trades": total,
            "wins": win_count,
            "losses": total - win_count,
            "winrate": win_count / total if total > 0 else 0.0,
            "total_pnl_usd": round(total_pnl, 2),
            "avg_pnl_usd": round(total_pnl / total, 2) if total > 0 else 0.0,
            "expectancy_r": round(expectancy, 4),
            "avg_win_r": round(
                float(np.mean([r for r in r_multiples if r > 0])) if any(r > 0 for r in r_multiples) else 0.0, 4
            ),
            "avg_loss_r": round(
                float(np.mean([r for r in r_multiples if r < 0])) if any(r < 0 for r in r_multiples) else 0.0, 4
            ),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "max_drawdown_usd": round(max_dd, 2),
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
        }

    def by_strategy(self, trades: List[Dict] = None) -> Dict[str, Dict]:
        """Performance breakdown per strategy."""
        trades = trades or self._get_trades()
        grouped: Dict[str, List] = {}
        for t in trades:
            name = t.get("strategy", "unknown")
            grouped.setdefault(name, []).append(t)

        result = {}
        for name, group_trades in grouped.items():
            result[name] = self.compute_basic_stats(group_trades)
        return result

    def by_regime(self, trades: List[Dict] = None) -> Dict[str, Dict]:
        """Performance breakdown per market regime."""
        trades = trades or self._get_trades()
        grouped: Dict[str, List] = {}
        for t in trades:
            regime = t.get("regime", "UNKNOWN")
            grouped.setdefault(regime, []).append(t)

        result = {}
        for regime, group_trades in grouped.items():
            result[regime] = self.compute_basic_stats(group_trades)
        return result

    def r_multiple_distribution(self, trades: List[Dict] = None) -> Dict:
        """Compute R-multiple distribution statistics."""
        trades = trades or self._get_trades()
        r_multiples = [t.get("r_multiple", 0) for t in trades]
        if not r_multiples:
            return {}

        percentiles = [10, 25, 50, 75, 90]
        perc_values = {
            f"p{p}": round(float(np.percentile(r_multiples, p)), 3)
            for p in percentiles
        }

        return {
            "mean": round(float(np.mean(r_multiples)), 4),
            "std": round(float(np.std(r_multiples)), 4),
            "min": round(float(np.min(r_multiples)), 4),
            "max": round(float(np.max(r_multiples)), 4),
            "positive_pct": round(sum(1 for r in r_multiples if r > 0) / len(r_multiples), 3),
            **perc_values,
        }

    def generate_report(self, output_path: str = None) -> str:
        """Generate a full text report."""
        trades = self._get_trades()
        if not trades:
            return "No closed trades found."

        basic = self.compute_basic_stats(trades)
        by_strat = self.by_strategy(trades)
        by_regime = self.by_regime(trades)
        r_dist = self.r_multiple_distribution(trades)

        lines = [
            "=" * 60,
            "TRADE JOURNAL REPORT",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "=" * 60,
            "",
            "--- OVERALL PERFORMANCE ---",
            f"Total Trades:    {basic.get('total_trades', 0)}",
            f"Win Rate:        {basic.get('winrate', 0):.1%}",
            f"Total P&L:       ${basic.get('total_pnl_usd', 0):,.2f}",
            f"Expectancy:      {basic.get('expectancy_r', 0):+.3f}R",
            f"Sharpe:          {basic.get('sharpe', 0):.3f}",
            f"Sortino:         {basic.get('sortino', 0):.3f}",
            f"Max Drawdown:    ${basic.get('max_drawdown_usd', 0):,.2f}",
            f"Max Win Streak:  {basic.get('max_win_streak', 0)}",
            f"Max Loss Streak: {basic.get('max_loss_streak', 0)}",
            "",
            "--- R-MULTIPLE DISTRIBUTION ---",
            f"Mean R:  {r_dist.get('mean', 0):+.3f}",
            f"Median:  {r_dist.get('p50', 0):+.3f}",
            f"Min:     {r_dist.get('min', 0):+.3f}",
            f"Max:     {r_dist.get('max', 0):+.3f}",
            "",
            "--- BY STRATEGY ---",
        ]

        for strat, stats in sorted(by_strat.items(), key=lambda x: -x[1].get("expectancy_r", 0)):
            lines.append(
                f"  {strat}: WR={stats.get('winrate', 0):.1%} "
                f"E={stats.get('expectancy_r', 0):+.3f}R "
                f"N={stats.get('total_trades', 0)}"
            )

        lines += ["", "--- BY REGIME ---"]
        for regime, stats in sorted(by_regime.items(), key=lambda x: -x[1].get("expectancy_r", 0)):
            lines.append(
                f"  {regime}: WR={stats.get('winrate', 0):.1%} "
                f"E={stats.get('expectancy_r', 0):+.3f}R "
                f"N={stats.get('total_trades', 0)}"
            )

        lines.append("=" * 60)
        report = "\n".join(lines)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w") as f:
                f.write(report)
            logger.info(f"[Analytics] Report saved to {output_path}")

        return report

    def export_ml_dataset(self, output_path: str = "data/ml_dataset.json") -> str:
        """
        Export ML-ready dataset: each trade as a feature vector.
        Features: regime, orderflow (CVD, imbalance, aggr, vol_z, vwap_z, oi_change),
                  market_impact, strategy → label: win (bool) + r_multiple (float)
        """
        trades = self._get_trades()
        ml_data = []

        for t in trades:
            ml_data.append({
                # Features
                "regime": t.get("regime", "UNKNOWN"),
                "cvd_1m": t.get("cvd_1m", 0),
                "cvd_5m": t.get("cvd_5m", 0),
                "book_imbalance": t.get("book_imbalance", 0.5),
                "aggression_ratio": t.get("aggression_ratio", 0.5),
                "volume_zscore": t.get("volume_zscore", 0),
                "vwap_z": t.get("vwap_z", 0),
                "oi_change_pct": t.get("oi_change_pct", 0),
                "kyle_lambda": t.get("kyle_lambda", 0),
                "is_absorption": int(t.get("is_absorption", 0)),
                "liq_vacuum": int(t.get("liq_vacuum", 0)),
                "regime_confidence": t.get("regime_confidence", 0),
                "strategy": t.get("strategy", ""),
                "direction": t.get("direction", ""),
                # Labels
                "win": int(t.get("win", 0)),
                "r_multiple": t.get("r_multiple", 0),
                "pnl_usd": t.get("pnl_usd", 0),
                "exit_reason": t.get("exit_reason", ""),
            })

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(ml_data, f, indent=2, default=str)

        logger.info(f"[Analytics] ML dataset exported: {len(ml_data)} samples -> {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Internal metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_max_drawdown(equity_curve: List[float]) -> Tuple[float, float]:
        if not equity_curve:
            return 0.0, 0.0
        arr = np.array(equity_curve)
        peak = np.maximum.accumulate(arr)
        dd = peak - arr
        max_dd = float(np.max(dd))
        initial = equity_curve[0] if equity_curve[0] != 0 else 1.0
        max_dd_pct = max_dd / abs(initial) * 100 if initial != 0 else 0.0
        return max_dd, max_dd_pct

    @staticmethod
    def _compute_sharpe(r_multiples: List[float], rf: float = 0.0) -> float:
        if len(r_multiples) < 2:
            return 0.0
        arr = np.array(r_multiples)
        std = np.std(arr)
        return float((np.mean(arr) - rf) / std) if std > 0 else 0.0

    @staticmethod
    def _compute_sortino(r_multiples: List[float], rf: float = 0.0) -> float:
        if len(r_multiples) < 2:
            return 0.0
        arr = np.array(r_multiples)
        downside = arr[arr < rf]
        if len(downside) == 0:
            return float("inf")
        downside_std = float(np.std(downside))
        return float((np.mean(arr) - rf) / downside_std) if downside_std > 0 else 0.0

    @staticmethod
    def _compute_streaks(trades: List[Dict]) -> Tuple[int, int]:
        max_win = 0
        max_loss = 0
        cur_win = 0
        cur_loss = 0
        for t in trades:
            if t.get("win", False):
                cur_win += 1
                cur_loss = 0
                max_win = max(max_win, cur_win)
            else:
                cur_loss += 1
                cur_win = 0
                max_loss = max(max_loss, cur_loss)
        return max_win, max_loss
