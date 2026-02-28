import sys
import os
import pandas as pd
import logging
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.backtesting.backtester import Backtester

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BacktestRunner")

def smart_money_logic(row, lookback):
    """
    Smart Money Logic for Backtesting (OHLCV only).
    Adapts the strategy logic to work with Pandas rows.
    """
    # 1. Time Window (London/NY) - e.g. 8 AM to 5 PM UTC
    # row['timestamp'] is a datetime object
    current_hour = row['timestamp'].hour
    if not (8 <= current_hour < 17):
        return None
        
    # 2. Liquidity Sweep
    # Need at least 10 candles
    if len(lookback) < 10:
        return None
        
    # Convert lookback to list of lists for compatibility if needed, 
    # or just use pandas vectorization.
    # Let's use simple pandas logic here.
    
    # Last completed candle (row is current, but backtester passes 'row' as current candle)
    # Actually, in event-driven, 'row' is the candle that just closed (or current).
    # Let's assume 'row' is the trigger candle.
    
    current_low = row['low']
    current_close = row['close']
    current_high = row['high']
    
    # Find lowest low of previous N candles (excluding current)
    prev_candles = lookback.iloc[-10:]
    lowest_low = prev_candles['low'].min()
    highest_high = prev_candles['high'].max()
    
    # Bullish Sweep: Price dipped below lowest low but closed above it
    # Note: This logic is slightly different than live because 'row' is the *current* candle.
    # If 'row' low < lowest_low AND 'row' close > lowest_low
    
    signal = None
    sl = None
    direction = None
    
    # Bullish Sweep
    if current_low < lowest_low and current_close > lowest_low:
        signal = "LONG"
        sl = current_low # SL at sweep low
        direction = "long"
        
    # Bearish Sweep
    elif current_high > highest_high and current_close < highest_high:
        signal = "SHORT"
        sl = current_high # SL at sweep high
        direction = "short"
        
    if signal:
        return {
            "direction": direction,
            "sl": sl,
            "timestamp": row['timestamp']
        }
        
    return None

def main():
    # 1. Check for data
    data_file = "data/backtest/BTC_USDT_15m.csv"
    if not os.path.exists(data_file):
        print(f"Data file {data_file} not found.")
        print("Please run: python scripts/download_data.py --symbol BTC/USDT --timeframe 15m --start 2024-01-01")
        return

    # 2. Load Data
    print(f"Loading data from {data_file}...")
    # Strict Fees: 0.06% Commission (Taker), 0.02% Slippage
    bt = Backtester(initial_capital=10000.0, commission=0.0006, slippage=0.0002)
    df = bt.load_data(data_file)
    
    # Convert timestamp to datetime if not already
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    print(f"Loaded {len(df)} candles.")
    
    # 3. Run Backtest
    print("Running Smart Money Backtest...")
    bt.run_strategy(df, smart_money_logic)
    
if __name__ == "__main__":
    main()
