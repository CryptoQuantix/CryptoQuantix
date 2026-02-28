"""
Brings Strategy Position Logger

Logs all NY Brings strategy trades to a dedicated file with full session and setup details.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class BringsPositionLogger:
    """Dedicated logger for NY Brings Strategy trades"""
    
    def __init__(self, log_file: str = "logs/brings_positions.txt"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize file with header if new
        if not self.log_file.exists():
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("NY BRINGS STRATEGY TRADING HISTORY\n")
                f.write("=" * 80 + "\n\n")
    
    def log_session_analysis(self, timestamp: datetime, session_data: Dict[str, Any]):
        """Log the result of the 15:00-16:00 session analysis"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'─' * 80}\n")
            f.write(f"📊 SESSION ANALYSIS (15:00-16:00 CET)\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"Date: {timestamp.strftime('%Y-%m-%d')}\n")
            f.write(f"Bias: {session_data.get('bias', 'NEUTRAL')}\n")
            f.write(f"Vectors: \n")
            f.write(f"  • Bullish (Green/Blue): {session_data.get('bullish_vectors', 0)}\n")
            f.write(f"  • Bearish (Red/Purple): {session_data.get('bearish_vectors', 0)}\n")
            f.write(f"Levels: \n")
            f.write(f"  • Session High: ${session_data.get('session_high', 0):,.2f}\n")
            f.write(f"  • Session Low:  ${session_data.get('session_low', 0):,.2f}\n")
            f.write(f"{'─' * 80}\n\n")

    def log_trade_signal(self, timestamp: datetime, signal: Dict[str, Any]):
        """Log a generated trade signal"""
        direction = signal.get('direction', 'unknown').upper()
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'═' * 80}\n")
            f.write(f"⚡ TRADE SIGNAL TRIGGERED - {direction}\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Instrument: {signal.get('instrument')}\n")
            f.write(f"Type: {signal.get('type')}\n\n")
            
            f.write(f"Entry Details:\n")
            f.write(f"  • Entry Price: ${signal.get('entry_price', 0):,.2f}\n")
            f.write(f"  • Stop Loss:   ${signal.get('stop_loss', 0):,.2f}\n")
            f.write(f"  • Size:        {signal.get('position_size', 0)}\n")
            f.write(f"{'═' * 80}\n\n")

    def log_execution(self, timestamp: datetime, success: bool, message: str = ""):
        """Log execution result"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            status = "✅ SUCCESS" if success else "❌ FAILED"
            f.write(f"{status}: {message}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'─' * 80}\n\n")
            
    def log_trailing_update(self, timestamp: datetime, update_data: Dict[str, Any]):
        """Log trailing stop updates"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"🔄 TRAILING STOP UPDATE\n")
            f.write(f"Timestamp: {timestamp.strftime('%H:%M:%S')}\n")
            f.write(f"Current Price: ${update_data.get('current_price', 0):,.2f}\n")
            f.write(f"New SL:        ${update_data.get('new_sl', 0):,.2f}\n")
            f.write(f"Profit:        {update_data.get('profit_pct', 0)*100:.2f}%\n\n")

    def log_tp_hit(self, timestamp: datetime, price: float, pnl: float):
        """Log Take Profit hit"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"💰 TAKE PROFIT HIT\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Price: ${price:,.2f}\n")
            f.write(f"PnL: ${pnl:,.2f}\n")
            f.write(f"{'═' * 80}\n\n")

    def log_close_position(self, timestamp: datetime, reason: str, pnl: float):
        """Log Position Closed"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"🚪 POSITION CLOSED\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Reason: {reason}\n")
            f.write(f"PnL: ${pnl:,.2f}\n")
            f.write(f"{'═' * 80}\n\n")

    def log_error(self, timestamp: datetime, error_msg: str):
        """Log execution error"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"🚨 EXECUTION ERROR\n")
            f.write(f"{'!' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Error: {error_msg}\n")
            f.write(f"{'!' * 80}\n\n")
