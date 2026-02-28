"""
Smart Money Position Logger

Logs all Smart Money trades, analysis, and management events to a dedicated file.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class SmartMoneyPositionLogger:
    """Dedicated logger for Smart Money trades"""
    
    def __init__(self, log_file: str = "logs/smart_money_positions.txt"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize file with header if new
        if not self.log_file.exists():
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("SMART MONEY TRADING SIGNALS HISTORY\n")
                f.write("=" * 80 + "\n\n")
    
    def log_sweep_detected(self, timestamp: datetime, direction: str, 
                          high: float, low: float, prev_high: float, prev_low: float):
        """Log when a liquidity sweep is detected"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'─' * 80}\n")
            f.write(f"🔍 LIQUIDITY SWEEP DETECTED\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Direction: {direction}\n")
            if direction == "LONG":
                f.write(f"  • Current Low: ${low:,.2f}\n")
                f.write(f"  • Previous Low: ${prev_low:,.2f}\n")
                f.write(f"  • Sweep Amount: ${prev_low - low:,.2f}\n")
            else:
                f.write(f"  • Current High: ${high:,.2f}\n")
                f.write(f"  • Previous High: ${prev_high:,.2f}\n")
                f.write(f"  • Sweep Amount: ${high - prev_high:,.2f}\n")
            f.write("\n")
    
    def log_flow_analysis(self, timestamp: datetime, flow_data: Dict[str, Any]):
        """Log order flow analysis results"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"📊 ORDER FLOW ANALYSIS\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Price Movement:\n")
            f.write(f"  • Start: ${flow_data['price_start']:,.2f}\n")
            f.write(f"  • End: ${flow_data['price_end']:,.2f}\n")
            f.write(f"  • Change: {flow_data['price_change_pct']:+.4f}%\n")
            f.write(f"\nVolume Analysis:\n")
            f.write(f"  • Total Volume: {flow_data['total_volume']:,.2f} BTC\n")
            f.write(f"  • Delta: {flow_data['delta']:+,.2f} BTC\n")
            f.write(f"\nSignal: {flow_data['signal']}\n")
            if flow_data['reason']:
                f.write(f"Reason: {flow_data['reason']}\n")
            f.write("\n")
    
    def log_signal_generated(self, timestamp: datetime, signal: Dict[str, Any]):
        """Log when a trading signal is generated"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"✅ SIGNAL GENERATED - CONFLUENCE CONFIRMED\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Type: {signal['type'].upper()}\n")
            f.write(f"Direction: {signal['direction'].upper()}\n")
            f.write(f"Instrument: {signal['instrument']}\n")
            f.write(f"Reason: {signal['reason']}\n")
            if 'stop_loss_price' in signal:
                f.write(f"Stop Loss: ${signal['stop_loss_price']:,.2f}\n")
            f.write(f"{'═' * 80}\n\n")
    
    def log_signal_rejected(self, timestamp: datetime, sweep_direction: str, 
                           flow_signal: str, reason: str):
        """Log when a signal is rejected (no confluence)"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"❌ SIGNAL REJECTED - NO CONFLUENCE\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Sweep Direction: {sweep_direction}\n")
            f.write(f"Flow Signal: {flow_signal}\n")
            f.write(f"Reason: {reason}\n")
            f.write(f"{'─' * 80}\n\n")
    
    def log_execution_result(self, timestamp: datetime, success: bool, 
                            instrument: str, details: Optional[str] = None):
        """Log trade execution result"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            if success:
                f.write(f"🎯 TRADE EXECUTED SUCCESSFULLY\n")
            else:
                f.write(f"⚠️ TRADE EXECUTION FAILED\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Instrument: {instrument}\n")
            if details:
                f.write(f"Details: {details}\n")
            f.write(f"{'─' * 80}\n\n")

    def log_sl_update(self, timestamp: datetime, new_sl: float, reason: str = "trailing"):
        """Log Stop Loss update (Trailing)"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"🛡️ STOP LOSS UPDATED ({reason.upper()})\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"New SL Price: ${new_sl:,.2f}\n\n")

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
    
    def log_session_start(self):
        """Log when a new trading session starts"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            now = datetime.now()
            f.write(f"\n\n{'═' * 80}\n")
            f.write(f"🚀 NEW SMART MONEY SESSION STARTED\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'═' * 80}\n\n")
