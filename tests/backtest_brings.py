import sys
import os
import pytz
import logging
import pandas as pd
from datetime import datetime, timedelta, time
import ccxt

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import BringsStrategyConfig
from src.strategies.brings_strategy import BringsStrategy
from src.strategies.pvsra_analyzer import PVSRAAnalyzer

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def fetch_historical_data(symbol, days=90, timeframe='5m'):
    """Fetch historical data from Binance with pagination"""
    exchange = ccxt.binance()
    limit = 1000
    since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
    all_ohlcv = []
    
    logger.info(f"Fetching {days} days of {timeframe} data for {symbol}...")
    
    while since < exchange.milliseconds():
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            if not ohlcv:
                break
            
            all_ohlcv.extend(ohlcv)
            since = ohlcv[-1][0] + 1
            # logger.info(f"Fetched {len(ohlcv)} candles, last date: {datetime.fromtimestamp(ohlcv[-1][0]/1000)}")
            
            if len(ohlcv) < limit:
                break
                
        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            break
            
    logger.info(f"Total candles fetched: {len(all_ohlcv)}")
    return all_ohlcv

def run_backtest():
    # Configuration
    config = BringsStrategyConfig(
        name="Backtest",
        enabled=True,
        deribit_symbol="BTC-PERPETUAL",
        binance_symbol="BTC/USDT",
        timeframe="5m",
        timezone="Europe/Rome",
        risk_per_trade_pct=0.01
    )
    
    # Initialize Strategy
    # Mocking client/dependencies as we don't execute real trades
    strategy = BringsStrategy(None, config, {})
    
    # Fetch Data
    # 90 days to get some stats
    ohlcv = fetch_historical_data(config.binance_symbol, days=90, timeframe=config.timeframe)
    if not ohlcv:
        logger.error("No data fetched.")
        return

    # Pre-analyze Vectors for efficiency
    # The strategy calculates vectors on the fly usually, but for backtest we can pass them
    # Actually PVSRAAnalyzer needs to calculate them. 
    # Let's use the analyzer to generate vectors for the whole dataset first.
    logger.info("Analyzing vectors...")
    
    # Chunking analysis to avoid memory issues if any (though 26k is fine)
    # PVSRAAnalyzer expects list of lists
    vectors = strategy.pvsra.analyze_candles(ohlcv)
    
    logger.info(f"Generated {len(vectors)} vector classifications.")
    
    # Simulation Loop
    trades = []
    equity = 10000.0
    initial_equity = equity
    
    # Mapping timestamp to index for easy lookup
    # We need to simulate the "scan" call at each candle step? 
    # Scanning every candle is slow. We can iterate day by day, 
    # pick the 15:00-16:00 window, determine bias, then look at 16:00+ candles.
    
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['dt'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert(config.timezone)
    df['vector'] = pd.Series(vectors) # align? vectors might be shorter by 10
    # Vectors[i] corresponds to OHLCV[i+10] usually in PVSRAAnalyzer default?
    # No, analyze_candles returns list corresponding to df[10:]
    # Let's align carefully.
    
    # PVSRAAnalyzer.analyze_candles returns vectors starting from index 10 of input
    aligned_ohlcv = ohlcv[10:]
    aligned_dt = df['dt'].iloc[10:].reset_index(drop=True)
    
    # Iterating through days
    unique_dates = aligned_dt.dt.date.unique()
    
    for date in unique_dates:
        # Get candles for this date
        day_indices = aligned_dt[aligned_dt.dt.date == date].index
        
        # We need the original OHLCV chunk for this block + some history for context if strategy needed it
        # But our strategy logic is "Look at 15-16, then scan after 16".
        
        # 1. Identify 15:00 - 16:00 Window
        # This corresponds to "Session Analysis"
        
        # Filter for 15:00-16:00
        # Indices in our aligned arrays
        session_indices = []
        post_session_indices = []
        
        for idx in day_indices:
            t = aligned_dt[idx].time()
            if time(15, 0) <= t < time(16, 0):
                session_indices.append(idx)
            elif time(16, 0) <= t < time(23, 0): # Scan until late night
                post_session_indices.append(idx)
        
        if not session_indices:
            continue
            
        # Analyze Session Bias
        bullish_vecs = 0
        bearish_vecs = 0
        
        session_high = -1.0
        session_low = 99999999.0
        
        for idx in session_indices:
            # Reconstruct candle format [ts, o, h, l, c, v]
            # aligned_ohlcv[idx]
            c = aligned_ohlcv[idx]
            v = vectors[idx] # vectors is 0-indexed aligned with aligned_ohlcv
            
            if c[2] > session_high: session_high = c[2]
            if c[3] < session_low: session_low = c[3]
            
            if strategy.pvsra.is_bullish_vector(v):
                bullish_vecs += 1
            elif strategy.pvsra.is_bearish_vector(v):
                bearish_vecs += 1
                
        bias = "NEUTRAL"
        if bearish_vecs >= 2 and bearish_vecs > bullish_vecs:
            bias = "LONG"
        elif bullish_vecs >= 2 and bullish_vecs > bearish_vecs:
            bias = "SHORT"
            
        # logger.info(f"{date}: Bias {bias} (Bull: {bullish_vecs}, Bear: {bearish_vecs})")
        
        if bias == "NEUTRAL":
            continue
            
        # Scan post-session for entry
        entered = False
        trade = None
        
        # Optimization: Track potential setup
        pending_setup = None # { 'type': LONG, 'vector_high': ... }
        
        for idx in post_session_indices:
            if entered: break
            
            current_candle = aligned_ohlcv[idx] # [ts, o, h, l, c, v]
            current_vector = vectors[idx]
            close_price = current_candle[4]
            high_price = current_candle[2]
            low_price = current_candle[3]
            
            # 1. Look for Setup (Reversal Vector)
            if not pending_setup:
                if bias == "LONG" and strategy.pvsra.is_bullish_vector(current_vector):
                     pending_setup = {
                         'type': 'LONG',
                         'trigger_price': high_price, # Enter if we break above this high
                         'sl_price': low_price * (1 - config.stop_loss_buffer)
                     }
                elif bias == "SHORT" and strategy.pvsra.is_bearish_vector(current_vector):
                     pending_setup = {
                         'type': 'SHORT',
                         'trigger_price': low_price, # Enter if we break below this low
                         'sl_price': high_price * (1 + config.stop_loss_buffer)
                     }
            
            # 2. Check for Trigger (Confirmation)
            elif pending_setup:
                # Expire setup if too much time passed? Let's keep it simple for now.
                # Or if SL hit before entry?
                
                if pending_setup['type'] == 'LONG':
                    # Check if invalid (price went below potential SL before triggering)
                    if low_price < pending_setup['sl_price']:
                        pending_setup = None # Invalidated
                        continue
                        
                    # Check Trigger (Breakout)
                    if high_price > pending_setup['trigger_price']:
                        # Entered!
                        entry_price = max(current_candle[1], pending_setup['trigger_price']) # Assumed slippage/market open
                        entered = True
                        trade = {
                            'date': aligned_dt[idx],
                            'type': 'LONG',
                            'entry': entry_price,
                            'sl': pending_setup['sl_price'],
                            'tp': 999999, # Trailing
                            'highest_price': entry_price, # For trailing
                            'result': 0
                        }
                        
                elif pending_setup['type'] == 'SHORT':
                    if high_price > pending_setup['sl_price']:
                        pending_setup = None
                        continue
                        
                    if low_price < pending_setup['trigger_price']:
                        entry_price = min(current_candle[1], pending_setup['trigger_price'])
                        entered = True
                        trade = {
                            'date': aligned_dt[idx],
                            'type': 'SHORT',
                            'entry': entry_price,
                            'sl': pending_setup['sl_price'],
                            'tp': 0,
                            'lowest_price': entry_price,
                            'result': 0
                        }

        # Check outcome of the trade (Trailing Stop Logic)
        if trade:
            start_search = -1
            for i, c in enumerate(aligned_ohlcv):
                if c[0] == current_candle[0]:
                    start_search = i + 1
                    break
            
            if start_search != -1:
                for i in range(start_search, len(aligned_ohlcv)):
                    c = aligned_ohlcv[i]
                    ts = c[0]
                    high = c[2]
                    low = c[3]
                    close = c[4]
                    
                    # Force close end of day? (23:00)
                    tz_obj = pytz.timezone(config.timezone) if isinstance(config.timezone, str) else config.timezone
                    if not tz_obj: tz_obj = pytz.UTC
                    
                    candle_time = datetime.fromtimestamp(ts/1000, tz=tz_obj)
                    if candle_time.hour >= 23:
                         # Close at market
                         if trade['type'] == 'LONG':
                             pnl_pct = (close - trade['entry']) / trade['entry']
                         else:
                             pnl_pct = (trade['entry'] - close) / trade['entry']
                         trade['pnl_pct'] = pnl_pct
                         trade['exit_reason'] = 'EOD'
                         break
                    
                    if trade['type'] == 'LONG':
                        # 1. Check SL
                        if low <= trade['sl']:
                            trade['pnl_pct'] = (trade['sl'] - trade['entry']) / trade['entry']
                            trade['exit_reason'] = 'SL'
                            break
                        
                        # 2. Update Trailing
                        if high > trade['highest_price']:
                            trade['highest_price'] = high
                            
                            # Trailing Logic
                            # If profit > 0.5%, move SL to Entry + 0.1%
                            profit_pct = (high - trade['entry']) / trade['entry']
                            if profit_pct > 0.005:
                                new_sl = trade['entry'] * 1.001
                                if new_sl > trade['sl']: trade['sl'] = new_sl
                            
                            # If profit > 1%, Trail by 0.5%
                            if profit_pct > 0.01:
                                new_sl = high * 0.995
                                if new_sl > trade['sl']: trade['sl'] = new_sl
                                
                    else: # SHORT
                        if high >= trade['sl']:
                            trade['pnl_pct'] = (trade['entry'] - trade['sl']) / trade['entry']
                            trade['exit_reason'] = 'SL'
                            break
                            
                        if low < trade['lowest_price']:
                            trade['lowest_price'] = low
                            
                            profit_pct = (trade['entry'] - low) / trade['entry']
                            if profit_pct > 0.005:
                                new_sl = trade['entry'] * 0.999
                                if new_sl < trade['sl']: trade['sl'] = new_sl
                                
                            if profit_pct > 0.01:
                                new_sl = low * 1.005
                                if new_sl < trade['sl']: trade['sl'] = new_sl
            
            if 'pnl_pct' in trade:
                trades.append(trade)
                equity *= (1 + trade['pnl_pct'])

    report = []
    report.append("\n" + "="*60)
    report.append(f"BACKTEST RESULTS ({len(aligned_dt.dt.date.unique())} Days processed)")
    report.append("="*60)
    report.append(f"Total Trades: {len(trades)}")
    
    if trades:
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]
        
        report.append(f"Wins: {len(wins)}")
        report.append(f"Losses: {len(losses)}")
        report.append(f"Win Rate: {len(wins)/len(trades):.1%}")
        
        avg_win = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
        report.append(f"Avg Win: {avg_win:.2%}")
        report.append(f"Avg Loss: {avg_loss:.2%}")
        
        total_pnl = sum(t['pnl_pct'] for t in trades)
        report.append(f"Total Simple PnL: {total_pnl:.2%}")
        report.append(f"Final Equity (Hypothetical): ${equity:,.2f}")
    
    report.append("="*60)
    
    report_text = "\n".join(report)
    print(report_text)
    
    with open("backtest_summary.txt", "w", encoding="utf-8") as f:
        f.write(report_text)

if __name__ == "__main__":
    run_backtest()
