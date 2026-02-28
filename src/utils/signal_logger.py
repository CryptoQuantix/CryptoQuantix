"""
Signal History Logger

Logs all trading signals (executed and rejected) to a dedicated file
for easy review and analysis.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

class SignalLogger:
    """Dedicated logger for trading signals"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create signal log file with date
        self.log_file = self.log_dir / "signals_history.txt"
        
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
    
    def log_session_start(self):
        """Log when a new trading session starts"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            now = datetime.now()
            f.write(f"\n\n{'═' * 80}\n")
            f.write(f"🚀 NEW TRADING SESSION STARTED\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'═' * 80}\n\n")
    
    def log_daily_summary(self, date: datetime, stats: Dict[str, int]):
        """Log daily summary statistics"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'═' * 80}\n")
            f.write(f"📈 DAILY SUMMARY - {date.strftime('%Y-%m-%d')}\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Sweeps Detected: {stats.get('sweeps', 0)}\n")
            f.write(f"Signals Generated: {stats.get('signals', 0)}\n")
            f.write(f"Signals Rejected: {stats.get('rejected', 0)}\n")
            f.write(f"Trades Executed: {stats.get('executed', 0)}\n")
            f.write(f"Trades Failed: {stats.get('failed', 0)}\n")
            if stats.get('signals', 0) > 0:
                success_rate = (stats.get('executed', 0) / stats.get('signals', 0)) * 100
                f.write(f"Execution Success Rate: {success_rate:.1f}%\n")
            f.write(f"{'═' * 80}\n\n")
