import sys
import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.backtesting.backtester import Backtester
from src.strategies.pvsra_analyzer import PVSRAAnalyzer, VectorType
from src.strategies.wm_formation import WMFormationStrategy
from config import WMFormationConfig

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WMBacktest")
# logging.getLogger("src.strategies.wm_formation").setLevel(logging.DEBUG)

def calculate_indicators(df, config):
    """Pre-calculate indicators for the entire dataframe"""
    # EMAs
    emas = {}
    # Map config names to periods
    periods = {
        'ema_50': config.ema_fast,
        'ema_60': config.ema_medium,
        'ema_200': config.ema_slow,
        'ema_223': config.ema_very_slow,
        'ema_800': 800 # Proxy for 4h 200 EMA
    }
    
    for name, period in periods.items():
        emas[name] = df['close'].ewm(span=period, adjust=False).mean().values
        
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/config.rsi_period, min_periods=config.rsi_period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/config.rsi_period, min_periods=config.rsi_period, adjust=False).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50).values
    
    return {
        'emas': emas,
        'rsi': rsi
    }

class WMBacktestLogic:
    def __init__(self, df_1h, df_15m, vectors_15m, config):
        self.df_1h = df_1h # Keep reference for indexing
        self.df_15m = df_15m
        self.vectors_15m = vectors_15m
        self.config = config
        
        # Index 15m data by timestamp for fast lookup
        self.df_15m['timestamp'] = pd.to_datetime(self.df_15m['timestamp'])
        self.df_15m.set_index('timestamp', inplace=True)
        self.df_15m['vector'] = vectors_15m
        
        # Pre-calculate 1h indicators
        print("Pre-calculating indicators...")
        self.indicators_primary = calculate_indicators(df_1h, config)
        
        # Initialize Strategy with Mocks
        client_mock = MagicMock()
        dependencies = {'equity': 10000}
        self.strategy = WMFormationStrategy(client_mock, config, dependencies)
        
        # Mock PVSRA to return 5m data when requested
        self.strategy.pvsra.get_latest_vectors = self._mock_get_latest_vectors
        
    def _mock_get_latest_vectors(self, timeframe, limit):
        current_time = getattr(self.strategy, 'current_backtest_time', None)
        if not current_time:
            return {'ohlcv': [], 'vectors': []}
            
        if timeframe == self.config.confirmation_timeframe_1: # 15m
            try:
                subset = self.df_15m.loc[:current_time].tail(limit)
                
                if subset.empty:
                    return {'ohlcv': [], 'vectors': []}
                
                # timestamp is in index, so we select other columns and reset_index to get timestamp back
                ohlcv = subset[['open', 'high', 'low', 'close', 'volume']].reset_index().values.tolist()
                vectors = subset['vector'].tolist()
                
                return {
                    'ohlcv': ohlcv,
                    'vectors': vectors
                }
            except Exception as e:
                logger.error(f"Error fetching 5m data: {e}")
                return {'ohlcv': [], 'vectors': []}
                
        return {'ohlcv': [], 'vectors': []}

    def logic(self, row, lookback):
        """
        Faithful logic using WMFormationStrategy.scan() with pre-calculated indicators.
        """
        # Need sufficient lookback (Backtester provides 300)
        if len(lookback) < 50:
            return None
            
        current_time = row['timestamp']
        self.strategy.current_backtest_time = current_time
        
        # Prepare 15m data
        # We need to include the current row in the data passed to scan
        # lookback is [i-300 : i], row is [i]
        # So we concatenate
        
        # Convert lookback to list
        ohlcv = lookback[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
        vectors = lookback['vector'].tolist()
        
        # Append current row
        current_ohlcv = [row['timestamp'], row['open'], row['high'], row['low'], row['close'], row['volume']]
        current_vector = row['vector']
        
        ohlcv.append(current_ohlcv)
        vectors.append(current_vector)
        
        # Slice Indicators
        # row.name is the index 'i' in df_15m (assuming default index)
        current_idx = row.name
        # We need indicators corresponding to the ohlcv window
        # ohlcv length is len(lookback) + 1
        window_len = len(ohlcv)
        start_idx = current_idx - window_len + 1
        
        # Safety check
        if start_idx < 0:
            return None
            
        sliced_indicators = {
            'emas': {k: v[start_idx:current_idx+1] for k, v in self.indicators_primary['emas'].items()},
            'rsi': self.indicators_primary['rsi'][start_idx:current_idx+1]
        }
        
        # Calculate Trend Status (Price vs EMA 800)
        current_price = row['close']
        trend_ema = self.indicators_primary['emas']['ema_800'][current_idx]
        
        sliced_indicators['trend_bullish'] = current_price > trend_ema
        sliced_indicators['trend_bearish'] = current_price < trend_ema
        
        # Call Strategy Scan
        signals = self.strategy.scan(
            backtest_ohlcv=ohlcv, 
            backtest_vectors=vectors,
            backtest_indicators=sliced_indicators
        )
        
        if signals:
            signal = signals[0]
            return {
                "direction": "long" if signal['direction'] == 'buy' else "short",
                "sl": signal['stop_loss'],
                "tp": signal['take_profit'],
                "timestamp": current_time
            }

        return None

def calculate_vectors(df):
    """Calculate PVSRA vectors for a dataframe"""
    ohlcv = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].values.tolist()
    analyzer = PVSRAAnalyzer("BTC/USDT")
    vectors = analyzer.analyze_candles(ohlcv)
    padding = [VectorType.NORMAL_BULL] * 10 
    return padding + vectors

def main():
    # Load Config
    config = WMFormationConfig.from_env()
    
    # Paths
    file_1h = "data/backtest/BTC_USDT_1h.csv"
    file_15m = "data/backtest/BTC_USDT_15m.csv"
    
    if not os.path.exists(file_1h) or not os.path.exists(file_15m):
        print("Data files not found. Please run download_wm_data.py first.")
        return
        
    print("Loading data...")
    df_1h = pd.read_csv(file_1h)
    df_15m = pd.read_csv(file_15m)
    
    df_1h['timestamp'] = pd.to_datetime(df_1h['timestamp'])
    df_15m['timestamp'] = pd.to_datetime(df_15m['timestamp'])
    
    print(f"Loaded {len(df_1h)} 1h candles and {len(df_15m)} 15m candles.")
    
    # Calculate Vectors
    print("Calculating PVSRA vectors...")
    vectors_1h = calculate_vectors(df_1h)
    vectors_15m = calculate_vectors(df_15m)
    
    # Add to DF
    if len(vectors_1h) != len(df_1h):
        min_len = min(len(vectors_1h), len(df_1h))
        vectors_1h = vectors_1h[:min_len]
        df_1h = df_1h.iloc[:min_len]
        
    if len(vectors_15m) != len(df_15m):
        min_len = min(len(vectors_15m), len(df_15m))
        vectors_15m = vectors_15m[:min_len]
        df_15m = df_15m.iloc[:min_len]
        
    df_1h['vector'] = vectors_1h
    
    # Initialize Logic
    logic_handler = WMBacktestLogic(df_1h, df_15m, vectors_15m, config)
    
    # Run Backtest
    print("Running Backtest (Faithful Logic + Optimized)...")
    bt = Backtester(initial_capital=10000.0, commission=0.0006, slippage=0.0002, max_leverage=config.max_leverage)
    bt.run_strategy(df_1h, logic_handler.logic)
    
    # Save detailed results
    if bt.trades:
        trades_df = pd.DataFrame(bt.trades)
        trades_df.to_csv("data/backtest/wm_backtest_trades.csv", index=False)
        print(f"\nDetailed trades saved to data/backtest/wm_backtest_trades.csv")
        
        # Additional analysis
        print("\n" + "="*60)
        print("DETAILED ANALYSIS")
        print("="*60)
        print(f"Average Win: ${trades_df[trades_df['pnl'] > 0]['pnl'].mean():.2f}")
        print(f"Average Loss: ${trades_df[trades_df['pnl'] <= 0]['pnl'].mean():.2f}")
        print(f"Largest Win: ${trades_df['pnl'].max():.2f}")
        print(f"Largest Loss: ${trades_df['pnl'].min():.2f}")
        print(f"Total Fees Paid: ${trades_df['fees'].sum():.2f}")
        print("="*60)

if __name__ == "__main__":
    main()
