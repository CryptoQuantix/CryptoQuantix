"""
DataQualityLayer — validates and cleans incoming market data.

Responsibilities:
  1. Gap detection in candle time series (missing candles)
  2. UTC timestamp normalization
  3. Outlier detection (price/volume > N sigma)
  4. Candle integrity (high >= open/close, low <= open/close, OHLC > 0)
  5. Timestamp alignment across streams (latency skew detection)
  6. Stale data detection (no update for > threshold seconds)

All methods return (cleaned_data, QualityReport).
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    """Summary of data quality checks for a batch."""
    symbol: str
    checked_at: str
    total_records: int
    gaps_found: int = 0
    gaps_filled: int = 0
    outliers_removed: int = 0
    bad_candles_removed: int = 0
    stale_records: int = 0
    timestamp_skew_ms: float = 0.0
    passed: bool = True
    issues: List[str] = field(default_factory=list)


@dataclass
class CandleRecord:
    """OHLCV candle."""
    symbol: str
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval_seconds: int = 60


class DataQualityLayer:
    """
    Data quality validator for market data streams.

    Usage:
        dq = DataQualityLayer()
        clean_candles, report = dq.validate_candles(candles, symbol="BTCUSDT")
        clean_trades, report = dq.validate_trades(trades, symbol="BTCUSDT")
    """

    def __init__(
        self,
        outlier_sigma: float = 5.0,
        max_stale_seconds: float = 60.0,
        max_gap_fill_candles: int = 5,
        max_timestamp_skew_ms: float = 5000.0,
    ):
        self.outlier_sigma = outlier_sigma
        self.max_stale_seconds = max_stale_seconds
        self.max_gap_fill_candles = max_gap_fill_candles
        self.max_timestamp_skew_ms = max_timestamp_skew_ms

        self._last_trade_ts: Dict[str, int] = {}
        self._cumulative_stats: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Candle validation
    # ------------------------------------------------------------------

    def validate_candles(
        self,
        candles: List[Dict],
        symbol: str,
        interval_seconds: int = 60,
    ) -> Tuple[List[Dict], QualityReport]:
        """
        Validate and clean a list of OHLCV candles.

        Args:
            candles: List of dicts with keys: timestamp_ms, open, high, low, close, volume
            symbol: e.g. "BTCUSDT"
            interval_seconds: expected candle interval

        Returns:
            (cleaned_candles, QualityReport)
        """
        report = QualityReport(
            symbol=symbol,
            checked_at=datetime.now(timezone.utc).isoformat(),
            total_records=len(candles),
        )

        if not candles:
            report.issues.append("Empty candle list")
            return candles, report

        # Step 1: Sort by timestamp
        candles = sorted(candles, key=lambda x: x.get("timestamp_ms", 0))

        # Step 2: Remove candles with integrity violations
        clean = []
        for c in candles:
            issue = self._check_candle_integrity(c)
            if issue:
                report.bad_candles_removed += 1
                report.issues.append(f"Bad candle at {c.get('timestamp_ms')}: {issue}")
            else:
                clean.append(c)
        candles = clean

        if not candles:
            report.passed = False
            return candles, report

        # Step 3: Gap detection and fill
        candles, gaps, fills = self._fill_gaps(candles, interval_seconds)
        report.gaps_found = gaps
        report.gaps_filled = fills

        # Step 4: Volume outlier removal
        candles, outliers = self._remove_volume_outliers(candles)
        report.outliers_removed = outliers

        # Step 5: Price outlier removal (close price)
        candles, price_outliers = self._remove_price_outliers(candles)
        report.outliers_removed += price_outliers

        if report.gaps_found > 0:
            report.issues.append(f"Found {report.gaps_found} gaps ({report.gaps_filled} filled)")

        if report.outliers_removed > 0:
            report.issues.append(f"Removed {report.outliers_removed} outliers")

        report.total_records = len(candles)
        return candles, report

    def _check_candle_integrity(self, c: Dict) -> Optional[str]:
        """Returns error string or None if OK."""
        try:
            o, h, l, cl, v = (
                float(c.get("open", 0)),
                float(c.get("high", 0)),
                float(c.get("low", 0)),
                float(c.get("close", 0)),
                float(c.get("volume", 0)),
            )
        except (TypeError, ValueError):
            return "non-numeric OHLCV"

        if any(x <= 0 for x in [o, h, l, cl]):
            return f"non-positive price: O={o} H={h} L={l} C={cl}"
        if h < max(o, cl):
            return f"high {h} < max(open={o}, close={cl})"
        if l > min(o, cl):
            return f"low {l} > min(open={o}, close={cl})"
        if v < 0:
            return f"negative volume: {v}"
        return None

    def _fill_gaps(
        self, candles: List[Dict], interval_seconds: int
    ) -> Tuple[List[Dict], int, int]:
        """
        Fill small gaps in the candle series with carry-forward (close of previous).
        Returns (candles_with_fills, gaps_found, gaps_filled).
        """
        if len(candles) < 2:
            return candles, 0, 0

        interval_ms = interval_seconds * 1000
        result = [candles[0]]
        gaps_found = 0
        gaps_filled = 0

        for i in range(1, len(candles)):
            prev = candles[i - 1]
            curr = candles[i]
            prev_ts = prev["timestamp_ms"]
            curr_ts = curr["timestamp_ms"]
            expected_ts = prev_ts + interval_ms

            if curr_ts > expected_ts + interval_ms // 2:
                # Gap detected
                missing = (curr_ts - prev_ts) // interval_ms - 1
                gaps_found += 1

                if missing <= self.max_gap_fill_candles:
                    # Fill with carry-forward
                    prev_close = prev["close"]
                    for j in range(1, int(missing) + 1):
                        fill_ts = prev_ts + j * interval_ms
                        result.append({
                            "timestamp_ms": fill_ts,
                            "open": prev_close,
                            "high": prev_close,
                            "low": prev_close,
                            "close": prev_close,
                            "volume": 0.0,
                            "_filled": True,
                        })
                        gaps_filled += 1
                else:
                    logger.warning(
                        f"[DataQuality] Large gap of {missing} candles — not filled"
                    )

            result.append(curr)

        return result, gaps_found, gaps_filled

    def _remove_volume_outliers(
        self, candles: List[Dict]
    ) -> Tuple[List[Dict], int]:
        """Remove candles with volume > N sigma from mean."""
        volumes = [float(c.get("volume", 0)) for c in candles]
        if len(volumes) < 10:
            return candles, 0

        mean_v = np.mean(volumes)
        std_v = np.std(volumes)
        if std_v == 0:
            return candles, 0

        threshold = mean_v + self.outlier_sigma * std_v
        clean = [c for c in candles if float(c.get("volume", 0)) <= threshold]
        removed = len(candles) - len(clean)
        return clean, removed

    def _remove_price_outliers(
        self, candles: List[Dict]
    ) -> Tuple[List[Dict], int]:
        """Remove candles with close price > N sigma from mean (log-returns based)."""
        if len(candles) < 10:
            return candles, 0

        closes = np.array([float(c.get("close", 1)) for c in candles])
        log_returns = np.diff(np.log(closes + 1e-10))

        if len(log_returns) < 5:
            return candles, 0

        mean_r = np.mean(log_returns)
        std_r = np.std(log_returns)
        if std_r == 0:
            return candles, 0

        # Mark candles where the return FROM previous was an outlier
        outlier_mask = np.abs(log_returns - mean_r) > self.outlier_sigma * std_r
        # +1 because log_returns[i] is return of candles[i+1]
        bad_indices = set(np.where(outlier_mask)[0] + 1)

        clean = [c for i, c in enumerate(candles) if i not in bad_indices]
        return clean, len(bad_indices)

    # ------------------------------------------------------------------
    # Trade validation
    # ------------------------------------------------------------------

    def validate_trades(
        self,
        trades: List[Any],
        symbol: str,
    ) -> Tuple[List[Any], QualityReport]:
        """
        Validate a list of AggTrade objects.

        Checks:
        - Non-zero price and quantity
        - Monotonic timestamps (no negative time jumps)
        - Price outliers vs recent median
        """
        report = QualityReport(
            symbol=symbol,
            checked_at=datetime.now(timezone.utc).isoformat(),
            total_records=len(trades),
        )

        if not trades:
            return trades, report

        clean = []
        prev_ts = 0
        prices = []

        for t in trades:
            # Basic sanity
            if t.price <= 0 or t.quantity <= 0:
                report.outliers_removed += 1
                continue
            # Non-decreasing timestamps (within 1s tolerance for reordering)
            if t.timestamp_ms < prev_ts - 1000:
                report.stale_records += 1
                continue
            prev_ts = max(prev_ts, t.timestamp_ms)
            prices.append(t.price)
            clean.append(t)

        # Price outlier detection on the batch
        if len(prices) >= 20:
            median_p = np.median(prices)
            std_p = np.std(prices)
            if std_p > 0:
                filtered = []
                for t in clean:
                    if abs(t.price - median_p) <= self.outlier_sigma * std_p:
                        filtered.append(t)
                    else:
                        report.outliers_removed += 1
                clean = filtered

        # Stale detection
        now_ms = int(time.time() * 1000)
        if clean and (now_ms - clean[-1].timestamp_ms) > self.max_stale_seconds * 1000:
            report.stale_records += 1
            report.issues.append(
                f"Last trade {(now_ms - clean[-1].timestamp_ms) / 1000:.1f}s ago — stale"
            )

        report.total_records = len(clean)
        return clean, report

    # ------------------------------------------------------------------
    # Timestamp utilities
    # ------------------------------------------------------------------

    def normalize_timestamp_ms(self, ts: int) -> int:
        """Ensure timestamp is in milliseconds (handles seconds or microseconds)."""
        if ts < 1e10:
            return int(ts * 1000)     # seconds → ms
        if ts > 1e16:
            return int(ts / 1000)     # microseconds → ms
        return int(ts)

    def check_timestamp_skew(self, exchange_ts_ms: int) -> float:
        """
        Compare exchange timestamp vs local clock.
        Returns skew in ms (positive = exchange ahead).
        """
        local_ms = int(time.time() * 1000)
        skew = exchange_ts_ms - local_ms
        if abs(skew) > self.max_timestamp_skew_ms:
            logger.warning(
                f"[DataQuality] Timestamp skew: {skew:.0f}ms "
                f"(threshold: {self.max_timestamp_skew_ms:.0f}ms)"
            )
        return float(skew)

    # ------------------------------------------------------------------
    # Candle builder from aggTrade stream
    # ------------------------------------------------------------------

    def build_candles_from_trades(
        self,
        trades: List[Any],
        interval_seconds: int = 60,
    ) -> List[Dict]:
        """
        Aggregate aggTrade ticks into OHLCV candles.

        Args:
            trades: List of AggTrade (must have .price, .quantity, .timestamp_ms)
            interval_seconds: candle interval

        Returns:
            List of OHLCV dicts sorted by timestamp
        """
        if not trades:
            return []

        interval_ms = interval_seconds * 1000
        buckets: Dict[int, Dict] = {}

        for t in trades:
            bucket_ts = (t.timestamp_ms // interval_ms) * interval_ms
            if bucket_ts not in buckets:
                buckets[bucket_ts] = {
                    "timestamp_ms": bucket_ts,
                    "open": t.price,
                    "high": t.price,
                    "low": t.price,
                    "close": t.price,
                    "volume": 0.0,
                    "buy_volume": 0.0,
                    "sell_volume": 0.0,
                    "trade_count": 0,
                }
            b = buckets[bucket_ts]
            b["high"] = max(b["high"], t.price)
            b["low"] = min(b["low"], t.price)
            b["close"] = t.price
            b["volume"] += t.quantity
            b["buy_volume"] += t.buy_volume
            b["sell_volume"] += t.sell_volume
            b["trade_count"] += 1

        return sorted(buckets.values(), key=lambda x: x["timestamp_ms"])
