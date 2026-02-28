"""
BacktestMetrics — extended performance metrics for backtest results.
Separate from the basic metrics computed inline in BacktestEngine.
"""
import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class BacktestMetrics:
    """Extended performance analysis for backtest results."""

    @staticmethod
    def full_report(trades, initial_equity: float = 10000.0) -> Dict:
        """Compute full metrics suite from a list of BacktestTrade objects."""
        if not trades:
            return {"error": "no trades"}

        pnls = [t.pnl_usd for t in trades]
        r_multiples = [t.r_multiple for t in trades]
        total = len(trades)
        wins = sum(1 for t in trades if t.pnl_usd > 0)

        # Equity curve
        equity = initial_equity
        equity_curve = [equity]
        for t in sorted(trades, key=lambda x: x.entry_ts_ms):
            equity += t.pnl_usd
            equity_curve.append(equity)

        final_equity = equity_curve[-1]

        arr = np.array(equity_curve)
        peak = np.maximum.accumulate(arr)
        dd_arr = (peak - arr) / peak * 100
        max_dd_pct = float(np.max(dd_arr))
        avg_dd_pct = float(np.mean(dd_arr[dd_arr > 0])) if np.any(dd_arr > 0) else 0.0

        r_arr = np.array(r_multiples)
        p_arr = np.array(pnls)

        # Sortino
        downside = r_arr[r_arr < 0]
        downside_std = float(np.std(downside)) if len(downside) > 0 else 1e-9
        sortino = float(np.mean(r_arr)) / downside_std if downside_std > 0 else 0.0

        # Profit factor
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Payoff ratio (avg win / avg loss)
        avg_win = float(np.mean([p for p in pnls if p > 0])) if gross_profit > 0 else 0.0
        avg_loss = float(np.mean([p for p in pnls if p < 0])) if gross_loss > 0 else 0.0
        payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else float("inf")

        # Longest underwater period (consecutive losing trades)
        max_consec_losses = 0
        cur_losses = 0
        for t in trades:
            if t.pnl_usd < 0:
                cur_losses += 1
                max_consec_losses = max(max_consec_losses, cur_losses)
            else:
                cur_losses = 0

        # Calmar
        total_return = (final_equity - initial_equity) / initial_equity * 100
        calmar = total_return / max_dd_pct if max_dd_pct > 0 else 0.0

        # Sharpe (annualized on daily returns if possible, else on R-multiples)
        sharpe = float(np.mean(r_arr) / np.std(r_arr)) if np.std(r_arr) > 0 else 0.0

        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "winrate_pct": wins / total * 100 if total > 0 else 0.0,
            "initial_equity": initial_equity,
            "final_equity": round(final_equity, 2),
            "total_pnl": round(final_equity - initial_equity, 2),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "avg_drawdown_pct": round(avg_dd_pct, 2),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "calmar": round(calmar, 4),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
            "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio != float("inf") else 999.0,
            "expectancy_r": round(float(np.mean(r_arr)), 4),
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "max_consecutive_losses": max_consec_losses,
            "total_fees": round(sum(t.fees_usd for t in trades), 2),
        }

    @staticmethod
    def regime_breakdown(trades) -> Dict[str, Dict]:
        """Performance breakdown per regime."""
        grouped: Dict[str, List] = {}
        for t in trades:
            regime = getattr(t, "regime", "UNKNOWN")
            grouped.setdefault(regime, []).append(t)

        result = {}
        for regime, regime_trades in grouped.items():
            pnls = [t.pnl_usd for t in regime_trades]
            r_mults = [t.r_multiple for t in regime_trades]
            wins = sum(1 for t in regime_trades if t.pnl_usd > 0)
            result[regime] = {
                "trades": len(regime_trades),
                "winrate_pct": wins / len(regime_trades) * 100,
                "avg_pnl": float(np.mean(pnls)),
                "expectancy_r": float(np.mean(r_mults)),
                "total_pnl": float(sum(pnls)),
            }
        return result

    @staticmethod
    def print_report(metrics: Dict, regime_breakdown: Dict = None):
        """Pretty-print backtest metrics to console."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"Trades:          {metrics.get('total_trades', 0)}")
        print(f"Win Rate:        {metrics.get('winrate_pct', 0):.1f}%")
        print(f"Initial Equity:  ${metrics.get('initial_equity', 0):,.2f}")
        print(f"Final Equity:    ${metrics.get('final_equity', 0):,.2f}")
        print(f"Total P&L:       ${metrics.get('total_pnl', 0):+,.2f} ({metrics.get('total_return_pct', 0):+.2f}%)")
        print(f"Max Drawdown:    {metrics.get('max_drawdown_pct', 0):.2f}%")
        print(f"Sharpe:          {metrics.get('sharpe', 0):.3f}")
        print(f"Sortino:         {metrics.get('sortino', 0):.3f}")
        print(f"Calmar:          {metrics.get('calmar', 0):.3f}")
        print(f"Profit Factor:   {metrics.get('profit_factor', 0):.3f}")
        print(f"Expectancy:      {metrics.get('expectancy_r', 0):+.4f}R")
        print(f"Avg Win:         ${metrics.get('avg_win_usd', 0):,.2f}")
        print(f"Avg Loss:        ${metrics.get('avg_loss_usd', 0):,.2f}")
        print(f"Max Loss Streak: {metrics.get('max_consecutive_losses', 0)}")
        print(f"Total Fees:      ${metrics.get('total_fees', 0):,.2f}")

        if regime_breakdown:
            print("\n--- Per Regime ---")
            for regime, stats in sorted(regime_breakdown.items(),
                                        key=lambda x: -x[1].get("expectancy_r", 0)):
                print(
                    f"  {regime:<15} N={stats['trades']:3d} "
                    f"WR={stats['winrate_pct']:.0f}% "
                    f"E={stats['expectancy_r']:+.3f}R "
                    f"P&L=${stats['total_pnl']:+,.2f}"
                )
        print("=" * 60)
