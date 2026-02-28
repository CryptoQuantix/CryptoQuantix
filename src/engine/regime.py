"""
RegimeDetector — classifies current market regime from price and orderflow data.

Regimes:
  TREND_UP:     Strong upward momentum, price above key MAs, increasing volume
  TREND_DOWN:   Strong downward momentum, price below key MAs, increasing volume
  RANGE:        Mean-reverting, bounded range, low directional movement
  COMPRESSION:  Narrowing range, decreasing volatility → typically precedes breakout
  EXPANSION:    Breakout from range/compression, volume and volatility surging

Inputs:
  - OHLCV candles (List[dict] or List[CandleFeatures])
  - Optionally: CVD, book_imbalance from OrderflowEngine

Output:
  MarketRegime dataclass with regime + confidence_score [0.0, 1.0]
"""
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    UNKNOWN = "UNKNOWN"


@dataclass
class MarketRegime:
    """Classification result from RegimeDetector."""
    regime: Regime = Regime.UNKNOWN
    confidence: float = 0.0     # [0.0, 1.0]
    symbol: str = ""
    timeframe_minutes: int = 15

    # Supporting metrics
    atr_pct: float = 0.0         # ATR as % of price
    adx_proxy: float = 0.0       # directional index proxy
    range_width_pct: float = 0.0 # high-low range as % of price
    vol_contraction: bool = False # volatility contracting
    trend_strength: float = 0.0  # [0.0, 1.0]
    range_score: float = 0.0     # [0.0, 1.0]
    realized_vol: float = 0.0    # rolling std of log returns

    # Recommended strategy types
    favorable_strategies: List[str] = None

    def __post_init__(self):
        if self.favorable_strategies is None:
            self.favorable_strategies = self._get_favorable_strategies()

    def _get_favorable_strategies(self) -> List[str]:
        mapping = {
            Regime.TREND_UP: ["VolumeBreakout", "ImbalanceScalp"],
            Regime.TREND_DOWN: ["VolumeBreakout", "ImbalanceScalp"],
            Regime.RANGE: ["MeanReversion", "ImbalanceScalp"],
            Regime.COMPRESSION: ["VolumeBreakout", "LiquidationSqueeze"],
            Regime.EXPANSION: ["VolumeBreakout", "LiquidationSqueeze"],
            Regime.UNKNOWN: [],
        }
        return mapping.get(self.regime, [])


class RegimeDetector:
    """
    Classifies market regime from OHLCV + orderflow data.

    Usage:
        detector = RegimeDetector()
        candles = engine.get_candle_history("BTCUSDT", interval_seconds=900, n=50)
        regime = detector.detect(candles, symbol="BTCUSDT")
    """

    def __init__(
        self,
        atr_period: int = 14,
        adx_period: int = 14,
        trend_ma_fast: int = 8,
        trend_ma_slow: int = 21,
        compression_lookback: int = 20,
        min_candles: int = 30,
    ):
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.trend_ma_fast = trend_ma_fast
        self.trend_ma_slow = trend_ma_slow
        self.compression_lookback = compression_lookback
        self.min_candles = min_candles

        self._last_regimes: Dict[str, MarketRegime] = {}

    def detect(
        self,
        candles: List,
        symbol: str = "",
        timeframe_minutes: int = 15,
        cvd: float = 0.0,
        book_imbalance: float = 0.5,
    ) -> MarketRegime:
        """
        Detect market regime from candle data.

        Args:
            candles: List of candle dicts/objects with open/high/low/close/volume
            symbol: e.g. "BTCUSDT"
            timeframe_minutes: candle interval in minutes
            cvd: Cumulative Volume Delta (from OrderflowEngine)
            book_imbalance: from OrderBookEngine

        Returns:
            MarketRegime with regime type and confidence
        """
        if len(candles) < self.min_candles:
            regime = MarketRegime(
                regime=Regime.UNKNOWN,
                confidence=0.0,
                symbol=symbol,
                timeframe_minutes=timeframe_minutes,
            )
            self._last_regimes[symbol] = regime
            return regime

        # Extract price arrays
        closes = np.array([self._get_field(c, "close") for c in candles], dtype=float)
        highs = np.array([self._get_field(c, "high") for c in candles], dtype=float)
        lows = np.array([self._get_field(c, "low") for c in candles], dtype=float)
        volumes = np.array([self._get_field(c, "volume") for c in candles], dtype=float)

        # Compute indicators
        atr = self._compute_atr(highs, lows, closes, self.atr_period)
        atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0.0
        realized_vol = self._compute_realized_vol(closes, window=20)
        adx_proxy = self._compute_adx_proxy(highs, lows, closes, self.adx_period)
        range_width_pct = (highs[-self.compression_lookback:].max() -
                           lows[-self.compression_lookback:].min()) / closes[-1] * 100

        # Moving averages for trend
        ma_fast = self._sma(closes, self.trend_ma_fast)
        ma_slow = self._sma(closes, self.trend_ma_slow)

        # Vol contraction: ATR decreasing over last N candles
        if len(candles) >= 20:
            recent_atrs = [
                self._compute_atr(highs[max(0, i-14):i+1], lows[max(0, i-14):i+1],
                                  closes[max(0, i-14):i+1], min(14, i+1))
                for i in range(len(closes) - 10, len(closes))
            ]
            vol_contraction = (len(recent_atrs) >= 5 and
                               recent_atrs[-1] < recent_atrs[0] * 0.8)
        else:
            vol_contraction = False

        # Volume trend: recent volume vs older volume
        vol_expansion = (np.mean(volumes[-5:]) > np.mean(volumes[-20:-5]) * 1.5
                         if len(volumes) >= 20 else False)

        # Classify regime
        regime, confidence, trend_strength, range_score = self._classify(
            closes=closes,
            atr_pct=atr_pct,
            adx_proxy=adx_proxy,
            range_width_pct=range_width_pct,
            vol_contraction=vol_contraction,
            vol_expansion=vol_expansion,
            ma_fast=ma_fast,
            ma_slow=ma_slow,
            cvd=cvd,
            book_imbalance=book_imbalance,
        )

        result = MarketRegime(
            regime=regime,
            confidence=confidence,
            symbol=symbol,
            timeframe_minutes=timeframe_minutes,
            atr_pct=atr_pct,
            adx_proxy=adx_proxy,
            range_width_pct=range_width_pct,
            vol_contraction=vol_contraction,
            trend_strength=trend_strength,
            range_score=range_score,
            realized_vol=realized_vol,
        )
        self._last_regimes[symbol] = result
        return result

    def _classify(
        self,
        closes: np.ndarray,
        atr_pct: float,
        adx_proxy: float,
        range_width_pct: float,
        vol_contraction: bool,
        vol_expansion: bool,
        ma_fast: float,
        ma_slow: float,
        cvd: float,
        book_imbalance: float,
    ) -> Tuple[Regime, float, float, float]:
        """
        Multi-factor regime classification.
        Returns: (regime, confidence, trend_strength, range_score)
        """
        last_close = closes[-1]

        # --- Trend score ---
        # Higher ADX + MA alignment + CVD alignment → stronger trend
        ma_bullish = ma_fast > ma_slow
        ma_bearish = ma_fast < ma_slow
        price_above_slow = last_close > ma_slow
        price_below_slow = last_close < ma_slow

        trend_score = 0.0
        if adx_proxy > 25:
            trend_score += 0.4
        elif adx_proxy > 15:
            trend_score += 0.2

        if ma_bullish and price_above_slow:
            trend_score += 0.3
        elif ma_bearish and price_below_slow:
            trend_score += 0.3

        if cvd > 0 and ma_bullish:
            trend_score += 0.2
        elif cvd < 0 and ma_bearish:
            trend_score += 0.2

        if vol_expansion:
            trend_score += 0.1

        trend_score = min(trend_score, 1.0)

        # --- Range score ---
        # Low ADX + narrow range + oscillating price → ranging
        range_score = 0.0
        if adx_proxy < 20:
            range_score += 0.4
        if range_width_pct < 3.0:
            range_score += 0.3
        if not vol_expansion:
            range_score += 0.2
        if 0.4 < book_imbalance < 0.6:
            range_score += 0.1

        range_score = min(range_score, 1.0)

        # --- Compression score ---
        compression_score = 0.0
        if vol_contraction:
            compression_score += 0.5
        if range_width_pct < 2.0:
            compression_score += 0.3
        if adx_proxy < 15:
            compression_score += 0.2

        compression_score = min(compression_score, 1.0)

        # --- Expansion score ---
        expansion_score = 0.0
        if vol_expansion:
            expansion_score += 0.4
        if atr_pct > 1.5:
            expansion_score += 0.3
        if adx_proxy > 20:
            expansion_score += 0.3

        expansion_score = min(expansion_score, 1.0)

        # --- Decision ---
        # Check expansion first (highest priority — breaks other conditions)
        if expansion_score > 0.6 and vol_expansion:
            return Regime.EXPANSION, expansion_score, trend_score, range_score

        if compression_score > 0.6 and vol_contraction:
            return Regime.COMPRESSION, compression_score, trend_score, range_score

        if trend_score > 0.5:
            if ma_bullish:
                return Regime.TREND_UP, trend_score, trend_score, range_score
            else:
                return Regime.TREND_DOWN, trend_score, trend_score, range_score

        if range_score > 0.5:
            return Regime.RANGE, range_score, trend_score, range_score

        # Default: lower confidence RANGE
        best_score = max(trend_score, range_score, compression_score, expansion_score)
        if best_score > 0.3:
            if trend_score == best_score:
                regime = Regime.TREND_UP if ma_bullish else Regime.TREND_DOWN
            elif range_score == best_score:
                regime = Regime.RANGE
            elif compression_score == best_score:
                regime = Regime.COMPRESSION
            else:
                regime = Regime.EXPANSION
            return regime, best_score * 0.7, trend_score, range_score

        return Regime.UNKNOWN, 0.0, trend_score, range_score

    # ------------------------------------------------------------------
    # Technical indicators
    # ------------------------------------------------------------------

    @staticmethod
    def _get_field(candle, field: str) -> float:
        """Get field from dict or dataclass."""
        if isinstance(candle, dict):
            return float(candle.get(field, 0.0))
        return float(getattr(candle, field, 0.0))

    @staticmethod
    def _sma(prices: np.ndarray, period: int) -> float:
        if len(prices) < period:
            return float(prices[-1]) if len(prices) > 0 else 0.0
        return float(np.mean(prices[-period:]))

    @staticmethod
    def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
        """Average True Range."""
        if len(closes) < 2:
            return float(highs[-1] - lows[-1]) if len(highs) > 0 else 0.0
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        if len(tr) == 0:
            return 0.0
        return float(np.mean(tr[-period:]))

    @staticmethod
    def _compute_realized_vol(closes: np.ndarray, window: int = 20) -> float:
        """Annualized realized volatility from log returns."""
        if len(closes) < 2:
            return 0.0
        log_returns = np.diff(np.log(closes[-window:] + 1e-10))
        return float(np.std(log_returns) * np.sqrt(252 * 24 * 4))  # annualized (15m candles)

    @staticmethod
    def _compute_adx_proxy(
        highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int
    ) -> float:
        """
        ADX proxy: directional movement index.
        Simplified implementation using directional differences.
        """
        if len(closes) < period + 1:
            return 0.0

        up_moves = np.diff(highs)
        down_moves = -np.diff(lows)

        dm_plus = np.where((up_moves > down_moves) & (up_moves > 0), up_moves, 0.0)
        dm_minus = np.where((down_moves > up_moves) & (down_moves > 0), down_moves, 0.0)

        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )

        tr_sum = np.sum(tr[-period:]) + 1e-10
        di_plus = np.sum(dm_plus[-period:]) / tr_sum * 100
        di_minus = np.sum(dm_minus[-period:]) / tr_sum * 100

        dx = abs(di_plus - di_minus) / (di_plus + di_minus + 1e-10) * 100
        return float(dx)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def get_last_regime(self, symbol: str) -> Optional[MarketRegime]:
        return self._last_regimes.get(symbol.upper())

    def is_trending(self, symbol: str) -> bool:
        r = self._last_regimes.get(symbol.upper())
        return r is not None and r.regime in (Regime.TREND_UP, Regime.TREND_DOWN)

    def is_ranging(self, symbol: str) -> bool:
        r = self._last_regimes.get(symbol.upper())
        return r is not None and r.regime == Regime.RANGE

    def is_compressing(self, symbol: str) -> bool:
        r = self._last_regimes.get(symbol.upper())
        return r is not None and r.regime == Regime.COMPRESSION
