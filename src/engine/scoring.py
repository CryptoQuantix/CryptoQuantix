"""
ScoringEngine — regime-aware strategy scoring and activation control.

Computes per-strategy:
  - Rolling 30-day win rate
  - Expectancy (avg R-multiple)
  - Sharpe ratio
  - Overall score = winrate × expectancy × (1 + sharpe_norm)

Regime-aware activation:
  - MeanReversion: OFF in TREND_UP/TREND_DOWN
  - VolumeBreakout: reduced weight in RANGE
  - LiquidationSqueeze: reduced in TREND (needs COMPRESSION/EXPANSION trigger)
  - ImbalanceScalp: active in all regimes but sized down in low confidence

Minimum score threshold for strategy activation (default: 0.3).
"""
import logging
import json
import os
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    """Single completed trade result for scoring."""
    strategy_name: str
    entry_time: str
    exit_time: str
    r_multiple: float       # profit / initial_risk (e.g. 1.5 = 1.5R)
    pnl_usd: float
    regime: str             # regime at entry
    win: bool               # True if profitable


@dataclass
class StrategyScore:
    """Scoring summary for one strategy."""
    strategy_name: str
    active: bool = True
    score: float = 0.0            # overall activation score [0.0, 1.0]

    # Components
    winrate_30d: float = 0.0       # rolling 30-day win rate
    expectancy: float = 0.0        # avg R-multiple per trade
    sharpe: float = 0.0            # Sharpe of R-multiples
    avg_r_multiple: float = 0.0

    # Sample counts
    total_trades: int = 0
    recent_trades: int = 0         # last 30 days

    # Regime-based activation
    regime_multiplier: float = 1.0

    # Timestamps
    last_updated: str = ""


# Regime compatibility rules: {strategy_class_name: (favorable_regimes, disabled_regimes)}
REGIME_RULES: Dict[str, Tuple[List[str], List[str]]] = {
    "MeanReversionStrategy": (
        ["RANGE"],
        ["TREND_UP", "TREND_DOWN"],     # OFF in trend
    ),
    "VolumeBreakoutStrategy": (
        ["TREND_DOWN", "EXPANSION", "COMPRESSION"],
        ["TREND_UP"],     # E=-0.40R in TREND_UP (real backtest 2025-12 -> 2026-03)
    ),
    "LiquidationSqueezeStrategy": (
        ["COMPRESSION", "EXPANSION"],
        [],
    ),
    "ImbalanceScalpStrategy": (
        ["RANGE", "TREND_UP", "TREND_DOWN", "COMPRESSION", "EXPANSION"],
        [],                              # active always
    ),
    "SmartMoneyStrategy": (
        ["TREND_UP", "TREND_DOWN", "RANGE"],
        [],
    ),
    "WMFormationStrategy": (
        ["RANGE", "COMPRESSION"],
        ["EXPANSION"],
    ),
    "BringsStrategy": (
        ["RANGE", "TREND_UP", "TREND_DOWN"],
        [],
    ),
    # Quant-validated strategies (4y multi-cycle dataset, Jun 2022 - Jun 2026).
    # TrendBreakdown is two-sided and macro-gated internally (daily SMA200):
    # shorts fire in macro bear, longs (7d-high breakout) in macro bull —
    # so no hourly regime is disabled here.
    "TrendBreakdownStrategy": (
        ["TREND_DOWN", "TREND_UP", "EXPANSION", "COMPRESSION", "RANGE"],
        [],
    ),
    # FundingSqueeze is short-only; internal macro gate already blocks bull,
    # TREND_UP disabled as a second hourly gate.
    "FundingSqueezeStrategy": (
        ["TREND_DOWN", "EXPANSION", "COMPRESSION", "RANGE"],
        ["TREND_UP"],
    ),
    # MacroCore is a daily regime-following core: hourly regimes are noise
    # at its timescale — no hourly gating.
    "MacroCoreStrategy": (
        ["TREND_DOWN", "TREND_UP", "EXPANSION", "COMPRESSION", "RANGE"],
        [],
    ),
}


class ScoringEngine:
    """
    Tracks strategy performance and computes activation scores.

    Usage:
        scoring = ScoringEngine()
        # After each trade closes:
        scoring.record_result(TradeResult(...))
        # Before each scan:
        score = scoring.get_score("VolumeBreakoutStrategy", current_regime)
        if score.active and score.score >= 0.3:
            strategy.scan()
    """

    def __init__(
        self,
        min_activation_score: float = 0.25,
        rolling_window_days: int = 30,
        min_trades_for_scoring: int = 5,
        persistence_path: str = "data/scoring_state.json",
    ):
        self.min_activation_score = min_activation_score
        self.rolling_window_days = rolling_window_days
        self.min_trades_for_scoring = min_trades_for_scoring
        self.persistence_path = persistence_path

        # {strategy_name: deque of TradeResult}
        self._history: Dict[str, deque] = {}
        self._scores: Dict[str, StrategyScore] = {}

        # Load saved state if exists
        self._load_state()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_result(self, result: TradeResult):
        """Record a completed trade result."""
        name = result.strategy_name
        if name not in self._history:
            self._history[name] = deque(maxlen=500)
        self._history[name].append(result)

        # Recompute score
        self._compute_score(name)

        # Persist periodically
        self._save_state()

        logger.info(
            f"[ScoringEngine] {name}: R={result.r_multiple:.2f} "
            f"win={result.win} regime={result.regime} "
            f"-> score={self._scores.get(name, StrategyScore(name)).score:.3f}"
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_score(self, strategy_name: str):
        """Recompute score for a strategy from its trade history."""
        history = list(self._history.get(strategy_name, []))
        if not history:
            self._scores[strategy_name] = StrategyScore(
                strategy_name=strategy_name,
                active=True,
                score=0.5,   # default until enough data
                last_updated=datetime.now(timezone.utc).isoformat(),
            )
            return

        # Filter to rolling window
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.rolling_window_days)
        recent = [
            t for t in history
            if datetime.fromisoformat(t.entry_time) > cutoff
        ]

        if len(recent) < self.min_trades_for_scoring:
            # Not enough data — use default score (give benefit of the doubt)
            self._scores[strategy_name] = StrategyScore(
                strategy_name=strategy_name,
                active=True,
                score=0.5,
                total_trades=len(history),
                recent_trades=len(recent),
                last_updated=datetime.now(timezone.utc).isoformat(),
            )
            return

        r_multiples = np.array([t.r_multiple for t in recent])
        wins = sum(1 for t in recent if t.win)

        winrate = wins / len(recent)
        expectancy = float(np.mean(r_multiples))
        sharpe = float(np.mean(r_multiples) / np.std(r_multiples)) if np.std(r_multiples) > 0 else 0.0

        # Normalize Sharpe to [0, 1]
        sharpe_norm = max(0.0, min(sharpe / 3.0, 1.0))

        # Overall score
        score = winrate * max(0.0, expectancy) * (1.0 + sharpe_norm)
        score = min(score, 1.0)  # cap at 1.0

        self._scores[strategy_name] = StrategyScore(
            strategy_name=strategy_name,
            active=score >= self.min_activation_score,
            score=score,
            winrate_30d=winrate,
            expectancy=expectancy,
            sharpe=sharpe,
            avg_r_multiple=float(np.mean(r_multiples)),
            total_trades=len(history),
            recent_trades=len(recent),
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    def get_score(
        self,
        strategy_name: str,
        current_regime: str = "UNKNOWN",
    ) -> StrategyScore:
        """
        Get activation score for a strategy given current regime.

        Returns:
            StrategyScore with .active and .score adjusted for regime
        """
        score = self._scores.get(strategy_name)
        if score is None:
            # First time — activate with default
            score = StrategyScore(
                strategy_name=strategy_name,
                active=True,
                score=0.5,
                regime_multiplier=1.0,
            )
            self._scores[strategy_name] = score

        # Apply regime rules
        rules = REGIME_RULES.get(strategy_name, ([], []))
        favorable_regimes, disabled_regimes = rules

        if current_regime in disabled_regimes:
            # Hard disable
            adjusted = StrategyScore(**{**vars(score)})
            adjusted.active = False
            adjusted.regime_multiplier = 0.0
            adjusted.score = 0.0
            return adjusted

        if favorable_regimes and current_regime in favorable_regimes:
            multiplier = 1.2  # boost in favorable regime
        elif favorable_regimes:
            multiplier = 0.7  # reduce in non-optimal regime
        else:
            multiplier = 1.0

        adjusted = StrategyScore(**{**vars(score)})
        adjusted.regime_multiplier = multiplier
        adjusted.score = min(score.score * multiplier, 1.0)
        adjusted.active = adjusted.score >= self.min_activation_score
        return adjusted

    def should_trade(self, strategy_name: str, current_regime: str = "UNKNOWN") -> Tuple[bool, str]:
        """
        Quick check: should this strategy trade now?

        Returns:
            (allowed, reason)
        """
        score = self.get_score(strategy_name, current_regime)
        if not score.active:
            return False, f"score={score.score:.3f} below threshold or regime-disabled"
        return True, f"score={score.score:.3f} regime={current_regime}"

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def get_all_scores(self, current_regime: str = "UNKNOWN") -> Dict[str, StrategyScore]:
        """Get scores for all known strategies in current regime."""
        return {
            name: self.get_score(name, current_regime)
            for name in self._history.keys()
        }

    def get_summary_table(self, current_regime: str = "UNKNOWN") -> List[Dict]:
        """Get scores as list of dicts for logging/dashboard."""
        rows = []
        for name, score in self.get_all_scores(current_regime).items():
            rows.append({
                "strategy": name,
                "active": score.active,
                "score": round(score.score, 3),
                "winrate_30d": round(score.winrate_30d, 3),
                "expectancy": round(score.expectancy, 3),
                "sharpe": round(score.sharpe, 3),
                "trades_30d": score.recent_trades,
                "regime_mult": score.regime_multiplier,
            })
        return sorted(rows, key=lambda x: -x["score"])

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.persistence_path) or ".", exist_ok=True)
            state = {
                name: [asdict(t) for t in trades]
                for name, trades in self._history.items()
            }
            with open(self.persistence_path, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.debug(f"[ScoringEngine] Save error: {e}")

    def _load_state(self):
        if not os.path.exists(self.persistence_path):
            return
        try:
            with open(self.persistence_path) as f:
                state = json.load(f)
            for name, trades in state.items():
                self._history[name] = deque(
                    [TradeResult(**t) for t in trades], maxlen=500
                )
                self._compute_score(name)
            logger.info(
                f"[ScoringEngine] Loaded {sum(len(v) for v in self._history.values())} "
                f"historical trades for {len(self._history)} strategies"
            )
        except Exception as e:
            logger.warning(f"[ScoringEngine] Load error: {e}")
