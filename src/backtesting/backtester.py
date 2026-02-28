import pandas as pd
import numpy as np
from typing import List, Dict, Any
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Backtester:
    """
    Simple Event-Driven Backtester for Smart Money Strategy.
    """
    
    def __init__(self, initial_capital: float = 1000.0, commission: float = 0.0006, slippage: float = 0.0, max_leverage: float = 10.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.commission = commission # e.g. 0.0006 = 0.06% per trade
        self.slippage = slippage # e.g. 0.0001 = 0.01% price impact
        self.max_leverage = max_leverage
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []
        
    def load_data(self, csv_path: str) -> pd.DataFrame:
        """Load OHLCV data from CSV"""
        df = pd.read_csv(csv_path)
        # Ensure columns: timestamp, open, high, low, close, volume
        return df
        
    def run_strategy(self, data: pd.DataFrame, strategy_logic):
        """
        Run strategy logic over data.
        strategy_logic: function that takes (row, lookback_data) and returns signal
        """
        logger.info("Starting Backtest...")
        
        position = None # {entry_price, size, sl, tp, direction}
        
        for i in range(300, len(data)):
            row = data.iloc[i]
            lookback = data.iloc[i-300:i]
            
            # 1. Check Exit if in position
            if position:
                self._check_exit(position, row)
                if position['status'] == 'closed':
                    self.trades.append(position)
                    self.capital += position['pnl']
                    position = None
                continue
                
            # 2. Check Entry
            signal = strategy_logic(row, lookback)
            if signal:
                position = self._open_position(signal, row)
                
            self.equity_curve.append(self.capital)
            
        self._generate_report()

    def _open_position(self, signal: Dict, row) -> Dict:
        """Simulate opening a position"""
        entry_price = row['close']
        
        # Apply Slippage to Entry
        if signal['direction'] == 'long':
            entry_price *= (1 + self.slippage)
        else:
            entry_price *= (1 - self.slippage)
            
        sl = signal['sl']
        
        # Sizing (1.5% Risk)
        risk_pct = 0.015
        risk_amt = self.capital * risk_pct
        dist = abs(entry_price - sl)
        
        if dist == 0:
            size = 0
        else:
            size = risk_amt / dist
            
        # Cap Size based on Max Leverage
        max_position_value = self.capital * self.max_leverage
        max_size = max_position_value / entry_price
        
        if size > max_size:
            size = max_size
        
        tp = entry_price + (dist * 2.5) if signal['direction'] == 'long' else entry_price - (dist * 2.5)
        
        return {
            "entry_time": row['timestamp'],
            "entry_price": entry_price,
            "direction": signal['direction'],
            "size": size,
            "sl": sl,
            "tp": tp,
            "status": "open",
            "pnl": 0
        }

    def _check_exit(self, position: Dict, row):
        """Check TP/SL hit"""
        high = row['high']
        low = row['low']
        exit_price = 0
        
        if position['direction'] == 'long':
            if low <= position['sl']:
                exit_price = position['sl'] * (1 - self.slippage) # Slippage on SL
                position['reason'] = 'SL'
                position['status'] = 'closed'
            elif high >= position['tp']:
                exit_price = position['tp'] * (1 - self.slippage) # Slippage on TP? Usually limit, but let's be conservative
                position['reason'] = 'TP'
                position['status'] = 'closed'
                
            if position['status'] == 'closed':
                raw_pnl = (exit_price - position['entry_price']) * position['size']
                
        else: # Short
            if high >= position['sl']:
                exit_price = position['sl'] * (1 + self.slippage)
                position['reason'] = 'SL'
                position['status'] = 'closed'
            elif low <= position['tp']:
                exit_price = position['tp'] * (1 + self.slippage)
                position['reason'] = 'TP'
                position['status'] = 'closed'
                
            if position['status'] == 'closed':
                raw_pnl = (position['entry_price'] - exit_price) * position['size']

        if position['status'] == 'closed':
            position['exit_price'] = exit_price
            
            # Calculate Fees
            entry_fee = position['entry_price'] * position['size'] * self.commission
            exit_fee = exit_price * position['size'] * self.commission
            total_fees = entry_fee + exit_fee
            
            position['pnl'] = raw_pnl - total_fees
            position['fees'] = total_fees

    def _generate_report(self):
        """Generate performance report"""
        if not self.trades:
            logger.info("No trades generated.")
            return
            
        df = pd.DataFrame(self.trades)
        total_trades = len(df)
        wins = len(df[df['pnl'] > 0])
        losses = len(df[df['pnl'] <= 0])
        win_rate = (wins / total_trades) * 100
        total_pnl = df['pnl'].sum()
        
        print("\n" + "="*40)
        print("BACKTEST RESULTS")
        print("="*40)
        print(f"Initial Capital: ${self.initial_capital:.2f}")
        print(f"Final Capital:   ${self.capital:.2f}")
        print(f"Total Return:    {((self.capital - self.initial_capital)/self.initial_capital)*100:.2f}%")
        print(f"Total Trades:    {total_trades}")
        print(f"Win Rate:        {win_rate:.1f}%")
        print(f"Wins: {wins} | Losses: {losses}")
        print("="*40 + "\n")

if __name__ == "__main__":
    # Example usage
    bt = Backtester()
    # bt.run_strategy(data, my_strategy_logic)
