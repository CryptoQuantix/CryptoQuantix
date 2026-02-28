import ccxt
import pandas as pd
import os
import argparse
from datetime import datetime, timedelta
import time
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def download_ohlcv(symbol, timeframe, start_date, output_dir):
    """Download OHLCV data from Binance"""
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    
    # Convert start date to timestamp
    since = exchange.parse8601(f"{start_date}T00:00:00Z")
    
    all_candles = []
    logger.info(f"Downloading {symbol} {timeframe} since {start_date}...")
    
    filename = f"{symbol.replace('/','_')}_{timeframe}.csv"
    filepath = os.path.join(output_dir, filename)
    
    # Check if file exists and load it to resume or skip
    if os.path.exists(filepath):
        logger.info(f"File {filepath} exists. Checking last timestamp...")
        try:
            existing_df = pd.read_csv(filepath)
            if not existing_df.empty:
                last_ts = pd.to_datetime(existing_df.iloc[-1]['timestamp']).timestamp() * 1000
                since = int(last_ts) + 1
                logger.info(f"Resuming from {datetime.fromtimestamp(since/1000)}")
                # We will append to this file later or just overwrite? 
                # For simplicity, let's just overwrite for now or handle appending carefully.
                # Actually, overwriting is safer to ensure continuity if we don't implement complex merging.
                # Let's just re-download to be safe and simple.
                logger.info("Overwriting existing file to ensure data integrity.")
                since = exchange.parse8601(f"{start_date}T00:00:00Z")
        except Exception as e:
            logger.warning(f"Could not read existing file: {e}")

    while since < exchange.milliseconds():
        try:
            candles = exchange.fetch_ohlcv(symbol, timeframe, since, limit=1000)
            if not candles:
                break
                
            all_candles.extend(candles)
            since = candles[-1][0] + 1
            
            # Progress
            current_date = datetime.fromtimestamp(since/1000).strftime('%Y-%m-%d')
            print(f"Fetched up to {current_date} ({len(all_candles)} candles)", end='\r')
            
            # Sleep to be nice to API
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(5) # Wait longer on error
            continue
            
    print() # Newline
    
    if not all_candles:
        logger.warning("No candles fetched.")
        return

    # Save to CSV
    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    df.to_csv(filepath, index=False)
    logger.info(f"Saved {len(df)} candles to {filepath}")

def main():
    parser = argparse.ArgumentParser(description="Download crypto data for W/M Strategy")
    parser.add_argument("--symbol", type=str, default="BTC/USDT", help="Symbol (e.g. BTC/USDT)")
    parser.add_argument("--start", type=str, default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="data/backtest", help="Output directory")
    
    args = parser.parse_args()
    
    # Download 15m data
    download_ohlcv(args.symbol, "15m", args.start, args.output)
    
    # Download 5m data
    download_ohlcv(args.symbol, "5m", args.start, args.output)

    # Download 1h data
    download_ohlcv(args.symbol, "1h", args.start, args.output)

if __name__ == "__main__":
    main()
