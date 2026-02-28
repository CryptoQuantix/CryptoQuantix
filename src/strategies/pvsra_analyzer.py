"""
PVSRA (Price Volume Support Resistance Analysis) Analyzer

Detects vector candles based on volume analysis following PVSRA methodology.
Vector candles indicate market maker activity and potential reversals.
"""

import logging
import ccxt
import pandas as pd
from typing import List, Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class VectorType(Enum):
    """Vector candle types based on volume analysis"""
    GREEN_200 = "GREEN_200"  # Bullish, 200% volume
    BLUE_150 = "BLUE_150"    # Bullish, 150% volume
    RED_200 = "RED_200"      # Bearish, 200% volume
    PURPLE_150 = "PURPLE_150"  # Bearish, 150% volume
    NORMAL_BULL = "NORMAL_BULL"  # Normal bullish candle
    NORMAL_BEAR = "NORMAL_BEAR"  # Normal bearish candle


class PVSRAAnalyzer:
    """
    Analyzes candles using PVSRA methodology to identify vector candles.
    
    Vector candles are high-volume candles that indicate market maker activity:
    - 200% candles: Volume >= 200% of 10-period average OR volume*spread >= highest of last 10
    - 150% candles: Volume >= 150% of 10-period average
    """
    
    def __init__(self, binance_symbol: str):
        """
        Initialize PVSRA analyzer.
        
        Args:
            binance_symbol: Binance symbol for volume data (e.g., 'BTC/USDT')
        """
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.symbol = binance_symbol
        logger.info(f"PVSRA Analyzer initialized for {binance_symbol}")
    
    def fetch_ohlcv(self, timeframe: str = '15m', limit: int = 100) -> List[List]:
        """
        Fetch OHLCV data from Binance.
        
        Args:
            timeframe: Candle timeframe (e.g., '15m', '5m', '1m')
            limit: Number of candles to fetch
            
        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                self.symbol,
                timeframe=timeframe,
                limit=limit
            )
            logger.debug(f"Fetched {len(ohlcv)} candles from Binance ({timeframe})")
            return ohlcv
        except Exception as e:
            logger.error(f"Error fetching OHLCV from Binance: {e}", exc_info=True)
            return []
    
    def analyze_candles(self, ohlcv: List[List]) -> List[VectorType]:
        """
        Analyze candles and classify each as a vector type.
        
        Args:
            ohlcv: List of [timestamp, open, high, low, close, volume]
            
        Returns:
            List of VectorType for each candle
        """
        if len(ohlcv) < 11:  # Need at least 11 candles (10 for average + 1 to analyze)
            logger.warning(f"Insufficient candles for PVSRA analysis: {len(ohlcv)}")
            return []
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        vector_types = []
        
        for i in range(10, len(df)):  # Start from index 10 (need 10 previous candles)
            vector_type = self._classify_candle(df, i)
            vector_types.append(vector_type)
        
        return vector_types
    
    def _classify_candle(self, df: pd.DataFrame, index: int) -> VectorType:
        """
        Classify a single candle as a vector type.
        
        Args:
            df: DataFrame with OHLCV data
            index: Index of candle to classify
            
        Returns:
            VectorType classification
        """
        # Get current candle data
        current_volume = df.loc[index, 'volume']
        current_open = df.loc[index, 'open']
        current_close = df.loc[index, 'close']
        current_high = df.loc[index, 'high']
        current_low = df.loc[index, 'low']
        
        # Calculate 10-period average volume (using previous 10 candles)
        avg_volume = df.loc[index-10:index-1, 'volume'].mean()
        
        # Calculate volume * spread for current candle
        current_spread = current_high - current_low
        volume_spread = current_volume * current_spread
        
        # Calculate highest volume * spread of previous 10 candles
        prev_spreads = (df.loc[index-10:index-1, 'high'] - df.loc[index-10:index-1, 'low'])
        prev_volume_spreads = df.loc[index-10:index-1, 'volume'] * prev_spreads
        highest_volume_spread = prev_volume_spreads.max()
        
        # Determine if bullish or bearish
        is_bullish = current_close > current_open
        
        # Classify based on volume thresholds
        # 200% condition: volume >= 200% of average OR volume*spread >= highest of last 10
        is_200_percent = (current_volume >= avg_volume * 2.0) or (volume_spread >= highest_volume_spread)
        
        # 150% condition: volume >= 150% of average
        is_150_percent = current_volume >= avg_volume * 1.5
        
        # Determine vector type
        if is_bullish:
            if is_200_percent:
                return VectorType.GREEN_200
            elif is_150_percent:
                return VectorType.BLUE_150
            else:
                return VectorType.NORMAL_BULL
        else:
            if is_200_percent:
                return VectorType.RED_200
            elif is_150_percent:
                return VectorType.PURPLE_150
            else:
                return VectorType.NORMAL_BEAR
    
    def get_latest_vectors(self, timeframe: str = '15m', limit: int = 50) -> Dict[str, Any]:
        """
        Get latest candles with vector classification.
        
        Args:
            timeframe: Candle timeframe
            limit: Number of candles to fetch
            
        Returns:
            Dict with 'ohlcv' and 'vectors' keys
        """
        ohlcv = self.fetch_ohlcv(timeframe, limit)
        if not ohlcv:
            return {'ohlcv': [], 'vectors': []}
        
        vectors = self.analyze_candles(ohlcv)
        
        # Return only the candles that have vector classifications
        # (skip first 10 used for average calculation)
        return {
            'ohlcv': ohlcv[10:],
            'vectors': vectors
        }
    
    def is_vector_candle(self, vector_type: VectorType) -> bool:
        """Check if a candle is a vector candle (not normal)"""
        return vector_type not in [VectorType.NORMAL_BULL, VectorType.NORMAL_BEAR]
    
    def is_bullish_vector(self, vector_type: VectorType) -> bool:
        """Check if a vector candle is bullish"""
        return vector_type in [VectorType.GREEN_200, VectorType.BLUE_150]
    
    def is_bearish_vector(self, vector_type: VectorType) -> bool:
        """Check if a vector candle is bearish"""
        return vector_type in [VectorType.RED_200, VectorType.PURPLE_150]
