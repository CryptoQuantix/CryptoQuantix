import ccxt
import pandas as pd
import os
import argparse
from datetime import datetime, timedelta
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def download_ohlcv(symbol, timeframe, start_date, output_dir):
    """Download OHLCV data from Binance"""
    exchange = ccxt.binance({'enableRateLimit': True})
    
    # Convert start date to timestamp
    since = exchange.parse8601(f"{start_date}T00:00:00Z")
    
    all_candles = []
    logger.info(f"Downloading {symbol} {timeframe} since {start_date}...")
    
    while since < exchange.milliseconds():
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            if not candles:
                break
                
            all_candles.extend(candles)
            since = candles[-1][0] + 1
            
            # Progress
            current_date = datetime.fromtimestamp(since/1000).strftime('%Y-%m-%d')
            print(f"Fetched up to {current_date}", end='\r')
            
        except Exception as e:
            logger.error(f"Error: {e}")
            break
            
    # Save to CSV
    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    filename = f"{symbol.replace('/','_')}_{timeframe}.csv"
    filepath = os.path.join(output_dir, filename)
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    df.to_csv(filepath, index=False)
    logger.info(f"\nSaved {len(df)} candles to {filepath}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download crypto data")
    parser.add_argument("--symbol", type=str, default="BTC/USDT", help="Symbol (e.g. BTC/USDT)")
    parser.add_argument("--timeframe", type=str, default="15m", help="Timeframe (e.g. 15m, 1h)")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="data/backtest", help="Output directory")
    
    args = parser.parse_args()
    
    download_ohlcv(args.symbol, args.timeframe, args.start, args.output)
