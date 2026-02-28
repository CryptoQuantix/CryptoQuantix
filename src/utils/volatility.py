import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class VolatilityAnalyzer:
    """Analyze implied and historical volatility for trading decisions"""

    def __init__(self, lookback_days: int = 30):
        """
        Initialize volatility analyzer

        Args:
            lookback_days: Number of days to look back for IV rank calculation
        """
        self.lookback_days = lookback_days
        self.iv_history = {}  # Store IV history per currency

    def calculate_iv_rank(self, currency: str, current_iv: float, iv_history: List[float]) -> float:
        """
        Calculate IV Rank (percentile of current IV in historical range)

        IV Rank = (Current IV - Min IV) / (Max IV - Min IV) * 100

        Args:
            currency: BTC or ETH
            current_iv: Current implied volatility
            iv_history: Historical IV values

        Returns:
            IV rank as percentage (0-100)
        """
        if not iv_history or len(iv_history) < 2:
            logger.warning(f"Insufficient IV history for {currency}, returning 50%")
            return 50.0

        min_iv = min(iv_history)
        max_iv = max(iv_history)

        if max_iv == min_iv:
            return 50.0

        iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100
        return round(iv_rank, 2)

    def calculate_iv_percentile(self, current_iv: float, iv_history: List[float]) -> float:
        """
        Calculate IV Percentile (percentage of time IV was below current level)

        Args:
            current_iv: Current implied volatility
            iv_history: Historical IV values

        Returns:
            Percentile as percentage (0-100)
        """
        if not iv_history:
            return 50.0

        below_count = sum(1 for iv in iv_history if iv < current_iv)
        percentile = (below_count / len(iv_history)) * 100
        return round(percentile, 2)

    def get_atm_iv(self, options_chain: List[Dict], spot_price: float) -> Optional[float]:
        """
        Get ATM (At-The-Money) implied volatility

        Args:
            options_chain: List of option instruments with greeks
            spot_price: Current spot price

        Returns:
            ATM implied volatility
        """
        if not options_chain:
            return None

        # Find options closest to ATM
        atm_options = []
        for option in options_chain:
            strike = option.get("strike")
            iv = option.get("mark_iv")

            if strike and iv:
                distance = abs(strike - spot_price)
                atm_options.append({
                    "strike": strike,
                    "iv": iv,
                    "distance": distance
                })

        if not atm_options:
            return None

        # Sort by distance and get closest strikes
        atm_options.sort(key=lambda x: x["distance"])
        closest = atm_options[:3]  # Take 3 closest

        # Average their IVs
        avg_iv = sum(opt["iv"] for opt in closest) / len(closest)
        return round(avg_iv, 4)

    def update_iv_history(self, currency: str, iv: float, timestamp: datetime = None):
        """
        Update IV history for a currency

        Args:
            currency: BTC or ETH
            iv: Implied volatility value
            timestamp: Timestamp (default: now)
        """
        if currency not in self.iv_history:
            self.iv_history[currency] = []

        if timestamp is None:
            timestamp = datetime.now()

        self.iv_history[currency].append({
            "timestamp": timestamp,
            "iv": iv
        })

        # Keep only recent history
        cutoff = datetime.now() - timedelta(days=self.lookback_days)
        self.iv_history[currency] = [
            item for item in self.iv_history[currency]
            if item["timestamp"] > cutoff
        ]

    def get_iv_history(self, currency: str) -> List[float]:
        """Get historical IV values for a currency"""
        if currency not in self.iv_history:
            return []

        return [item["iv"] for item in self.iv_history[currency]]

    def should_enter_position(self, currency: str, current_iv: float,
                             min_iv_threshold: float = None,
                             min_iv_percentile: float = 30,
                             min_history_points: int = 5) -> Tuple[bool, str]:
        """
        Determine if conditions are good to enter a position based on IV

        Args:
            currency: BTC or ETH
            current_iv: Current implied volatility
            min_iv_threshold: Absolute minimum IV (e.g., 0.5 = 50%)
            min_iv_percentile: Minimum IV percentile required
            min_history_points: Minimum number of IV history points needed for percentile calculation

        Returns:
            Tuple of (should_enter, reason)
        """
        iv_history = self.get_iv_history(currency)

        # Check absolute IV threshold
        if min_iv_threshold and current_iv < min_iv_threshold:
            return False, f"IV {current_iv:.2%} below minimum threshold {min_iv_threshold:.2%}"

        # Check IV percentile only if we have enough history
        if iv_history and len(iv_history) >= min_history_points:
            iv_percentile = self.calculate_iv_percentile(current_iv, iv_history)
            if iv_percentile < min_iv_percentile:
                return False, f"IV percentile {iv_percentile:.1f}% below minimum {min_iv_percentile}%"

            iv_rank = self.calculate_iv_rank(currency, current_iv, iv_history)
            return True, f"IV rank {iv_rank:.1f}%, percentile {iv_percentile:.1f}%"
        else:
            # Not enough history - allow trading if IV is high enough
            # Use a reasonable default threshold if none provided
            if min_iv_threshold is None:
                min_iv_threshold = 0.50  # 50% IV minimum when no history

            if current_iv >= min_iv_threshold:
                history_msg = f"building history ({len(iv_history)}/{min_history_points})" if iv_history else "no history"
                return True, f"IV {current_iv:.2%} above threshold ({history_msg})"
            else:
                return False, f"IV {current_iv:.2%} below threshold {min_iv_threshold:.2%} (insufficient history)"

    def get_iv_statistics(self, currency: str) -> Dict:
        """
        Get statistical summary of IV for a currency

        Returns:
            Dict with mean, std, min, max, current
        """
        iv_history = self.get_iv_history(currency)

        if not iv_history:
            return {
                "mean": None,
                "std": None,
                "min": None,
                "max": None,
                "count": 0
            }

        return {
            "mean": round(np.mean(iv_history), 4),
            "std": round(np.std(iv_history), 4),
            "min": round(min(iv_history), 4),
            "max": round(max(iv_history), 4),
            "count": len(iv_history)
        }
