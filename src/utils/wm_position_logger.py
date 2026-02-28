"""
W/M Formation Position Logger

Logs all W/M formation trades to a dedicated file with full formation details.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class WMPositionLogger:
    """Dedicated logger for W/M Formation trades"""
    
    def __init__(self, log_file: str = "logs/wm_positions.txt"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize file with header if new
        if not self.log_file.exists():
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("W/M FORMATION TRADING SIGNALS HISTORY\n")
                f.write("=" * 80 + "\n\n")
    
    def log_formation_detected(self, timestamp: datetime, formation_type: str,
                              phase_data: Dict[str, Any], instrument: str):
        """Log when a W or M formation is detected"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'═' * 80}\n")
            f.write(f"{formation_type.upper()} FORMATION - {'LONG' if formation_type == 'W' else 'SHORT'} SIGNAL\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Instrument: {instrument}\n")
            f.write(f"Formation Type: {formation_type} Formation\n\n")
            
            # Phase 1
            f.write(f"Phase 1 ({'Dump' if formation_type == 'W' else 'Pump'}):\n")
            f.write(f"  • Vector Candles: {', '.join(phase_data.get('phase1_vectors', []))}\n")
            f.write(f"  • {'Low' if formation_type == 'W' else 'High'}: ${phase_data.get('phase1_extreme', 0):,.2f}\n")
            f.write(f"  • EMA 50: ${phase_data.get('ema_50', 0):,.2f}\n\n")
            
            # Phase 2
            f.write(f"Phase 2 (Retracement):\n")
            f.write(f"  • Retracement: {phase_data.get('phase2_retracement_pct', 0):.1f}%\n")
            f.write(f"  • {'High' if formation_type == 'W' else 'Low'}: ${phase_data.get('phase2_extreme', 0):,.2f}\n\n")
            
            # Phase 3
            f.write(f"Phase 3 (Sweep):\n")
            f.write(f"  • Sweep {'Low' if formation_type == 'W' else 'High'}: ${phase_data.get('phase3_sweep', 0):,.2f}")
            f.write(f" (swept ${abs(phase_data.get('phase3_sweep_amount', 0)):,.2f} {'below' if formation_type == 'W' else 'above'} Phase 1)\n")
            f.write(f"  • Body Close: ${phase_data.get('phase3_body_close', 0):,.2f}")
            f.write(f" ({'above' if formation_type == 'W' else 'below'} Phase 1 {'low' if formation_type == 'W' else 'high'} ✓)\n\n")
            
            # Phase 4
            f.write(f"Phase 4 ({'Breakout' if formation_type == 'W' else 'Breakdown'}):\n")
            f.write(f"  • Breakout Candle: {phase_data.get('phase4_vector', 'N/A')}\n")
            f.write(f"  • Price: ${phase_data.get('phase4_price', 0):,.2f}\n")
            f.write(f"  • {'Above' if formation_type == 'W' else 'Below'} 50 EMA: ✓\n\n")
    
    def log_entry_details(self, timestamp: datetime, entry_data: Dict[str, Any]):
        """Log trade entry details"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"Entry Details:\n")
            f.write(f"  • Entry Price: ${entry_data.get('entry_price', 0):,.2f}\n")
            f.write(f"  • Stop Loss: ${entry_data.get('stop_loss', 0):,.2f}")
            f.write(f" ({entry_data.get('stop_loss_buffer_pct', 0):.2f}% beyond sweep)\n")
            f.write(f"  • Take Profit: ${entry_data.get('take_profit', 0):,.2f}")
            f.write(f" ({entry_data.get('risk_reward_ratio', 0):.1f}:1 RR)\n")
            f.write(f"  • Position Size: {entry_data.get('position_size', 0)} contracts\n")
            f.write(f"  • Risk: ${entry_data.get('risk_amount', 0):,.2f}")
            f.write(f" ({entry_data.get('risk_pct', 0):.1f}% of equity)\n\n")
            f.write(f"{'═' * 80}\n\n")
    
    def log_formation_rejected(self, timestamp: datetime, formation_type: str,
                              reason: str, phase_data: Dict[str, Any]):
        """Log when a formation is rejected (doesn't meet all criteria)"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'─' * 80}\n")
            f.write(f"❌ {formation_type.upper()} FORMATION REJECTED\n")
            f.write(f"{'─' * 80}\n")
            f.write(f"Timestamp: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Reason: {reason}\n")
            f.write(f"Phase Data: {phase_data}\n")
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
            f.write(f"🚀 NEW W/M FORMATION TRADING SESSION STARTED\n")
            f.write(f"{'═' * 80}\n")
            f.write(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'═' * 80}\n\n")
