"""
NY Brings Strategy

Capitalizes on market manipulation during the London/New York session overlap (15:00 - 16:00 CET).
Identifies Vector Candles created during this window and trades the reversal.
"""

import logging
import pytz
from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
from src.strategies.base_strategy import BaseStrategy
from src.strategies.pvsra_analyzer import PVSRAAnalyzer, VectorType
from src.utils.brings_position_logger import BringsPositionLogger
from config import BringsStrategyConfig
from src.core.state_manager import StateManager # Added for virtual state

logger = logging.getLogger(__name__)

class BringsStrategy(BaseStrategy):
    """
    NY Brings Trading Strategy using PVSRA.
    """
    
    def __init__(self, client, config: BringsStrategyConfig, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)
        self.config = config
        self.pvsra = PVSRAAnalyzer(config.binance_symbol)
        self.timezone = pytz.timezone(config.timezone)
        self.position_logger = BringsPositionLogger()
        
        # Virtual State Manager
        self.state_file = "brings_state.json"
        self.state_manager = StateManager()
        self.active_position = self.state_manager.load_state(self.state_file)
        
        # State to track if we already traded the current session
        self.last_traded_date = None
        if self.active_position:
             # Assume we traded today if we have a position? 
             # Or just check date. For safety, let's keep last_traded_date independent for now.
             pass
        
        # Sync state with exchange to catch "ghost" positions
        self.sync_state()

        logger.info(f"NY Brings Strategy initialized for {config.deribit_symbol}")
        logger.info(f"Timezone: {config.timezone}, Timeframe: {config.timeframe}")

    def sync_state(self):
        """
        Sync local state with actual exchange state.
        Recovers from 'amnesia' if bot crashed or was restarted on new machine.
        """
        try:
            symbol = self.config.deribit_symbol
            currency = "BTC" if "BTC" in symbol else "ETH"
            
            # 1. Check if we really have a position on exchange
            # Brings strategy trades futures/perps, so we must specify kind='future'
            positions = self.client.get_positions(currency, kind="future")
            target_pos = next((p for p in positions if p['instrument_name'] == symbol), None)
            
            if not target_pos:
                if self.active_position:
                    logger.warning(f"Local state has position but Exchange does NOT. Clearing local state.")
                    self.active_position = None
                    self.state_manager.delete_state(self.state_file)
                return

            # 2. Position exists on Exchange. Check if it belongs to THIS strategy.
            # We check if there is an open SL order with label 'brings_sl'
            open_orders = self.client.get_open_orders_by_instrument(symbol, type="stop_market")
            sl_order = next((o for o in open_orders if o.get('label') == "brings_sl"), None)
            
            if sl_order:
                # 3. It's OUR position! Reconstruct state if missing.
                if not self.active_position:
                    logger.info("Found orphan Brings position on exchange! Adopting it.")
                    
                    self.active_position = {
                        'instrument': symbol,
                        'direction': target_pos['direction'],
                        'quantity': target_pos['size'], # Deribit size is quantity
                        'entry_price': target_pos['average_price'],
                        'sl_price': sl_order['trigger_price'] if 'trigger_price' in sl_order else sl_order.get('stop_price'),
                        'start_time': datetime.now().isoformat() # Approx
                    }
                    self.state_manager.save_state(self.state_file, self.active_position)
                    
                    self.position_logger.log_execution(
                        datetime.now(self.timezone), 
                        True, 
                        f"RECOVERY: Adopted existing position {target_pos['size']} {target_pos['direction']} @ {target_pos['average_price']}"
                    )
            else:
                # Position exists but NO 'brings_sl'. 
                # Could be manual trade, or other strategy.
                # If we have local state, but no SL on exchange, maybe SL was cancelled?
                if self.active_position:
                    logger.warning("Position exists locally and on exchange, but SL is missing/mismatched. Keeping local state but SL management might fail.")
                
        except Exception as e:
            logger.error(f"Error syncing state: {e}")

    def scan(self, backtest_data: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Scan for entry signals with Confirmation + Trailing Stop logic.
        """
        try:
            signals = []
            
            # Determine current time and date
            if backtest_data and 'timestamp' in backtest_data:
                now = backtest_data['timestamp']
                if isinstance(now, (int, float)):
                    now = datetime.fromtimestamp(now / 1000, tz=self.timezone)
                if now.tzinfo is None:
                    now = self.timezone.localize(now)
                
                ohlcv = backtest_data.get('ohlcv', [])
                vectors = backtest_data.get('vectors', [])
            else:
                now = datetime.now(self.timezone)
                # if self.last_traded_date == now.date():
                #     return [] # Allow multiple scans to check for confirmation trigger
                    
                ohlcv_data = self.pvsra.get_latest_vectors(
                    timeframe=self.config.timeframe,
                    limit=100
                )
                ohlcv = ohlcv_data['ohlcv']
                vectors = ohlcv_data['vectors']

            # 1. Trading Window: 16:00 - 20:00 CET
            if not (time(16, 0) <= now.time() < time(20, 0)):
                 return []
                 
            # 2. Analyze Today's Session
            session_start = now.replace(hour=15, minute=0, second=0, microsecond=0)
            session_end = now.replace(hour=16, minute=0, second=0, microsecond=0)
            
            start_ts = session_start.timestamp() * 1000
            end_ts = session_end.timestamp() * 1000
            
            session_vectors = []
            session_candles = []
            
            for i, candle in enumerate(ohlcv):
                ts = candle[0]
                if start_ts <= ts < end_ts:
                    session_candles.append(candle)
                    if i < len(vectors):
                        session_vectors.append(vectors[i])
            
            if not session_candles:
                return []

            # 3. Determine Bias
            bullish_vectors = 0
            bearish_vectors = 0
            for v in session_vectors:
                if self.pvsra.is_bullish_vector(v): bullish_vectors += 1
                elif self.pvsra.is_bearish_vector(v): bearish_vectors += 1
            
            bias = "NEUTRAL"
            if bearish_vectors >= 2 and bearish_vectors > bullish_vectors: bias = "LONG"
            elif bullish_vectors >= 2 and bullish_vectors > bearish_vectors: bias = "SHORT"
                
            if bias == "NEUTRAL":
                return []
                
            # Log session analysis once per day (checking if we haven't traded yet helps verify readiness)
            # Using a simple cache to avoid spamming log
            today_str = now.strftime('%Y-%m-%d')
            if not hasattr(self, '_last_log_date') or self._last_log_date != today_str:
                session_high = max([c[2] for c in session_candles])
                session_low = min([c[3] for c in session_candles])
                self.position_logger.log_session_analysis(now, {
                    'bias': bias,
                    'bullish_vectors': bullish_vectors,
                    'bearish_vectors': bearish_vectors,
                    'session_high': session_high,
                    'session_low': session_low
                })
                self._last_log_date = today_str
                
            # 4. Check for Confirmation Trigger (Breakout of Vector Candle)
            current_candle = ohlcv[-1]
            current_vector = vectors[-1] if vectors else None
            
            signal = None
            session_high = max([c[2] for c in session_candles])
            session_low = min([c[3] for c in session_candles])
            
            # We need to find if we have a valid setup candle RECENTLY (e.g. current or last few)
            # For simplicity in live trading, we check if the CURRENT candle is the vector that triggers the setup
            # OR if we just broke the structure.
            
            # Robust Logic:
            # If Bias LONG: Look for Bullish Vector. If found, High of that vector is Trigger Price.
            # If Bias SHORT: Look for Bearish Vector. If found, Low of that vector is Trigger Price.
            
            # In live scan, we might miss the exact moment.
            # So we check: Did we JUST close above a Bullish Vector High?
            
            # Determine tick size
            tick_size = 0.5 if "BTC" in self.config.deribit_symbol else 0.05

            if bias == "LONG":
                if current_vector and self.pvsra.is_bullish_vector(current_vector):
                     # We have a candidate vector. Check if price is breaking out? 
                     # Or do we simply enter on the Vector Close if it absorbed?
                     # Backtest optimization used "Breakout" of the vector high.
                     
                     # Simplification for Live Bot:
                     # If we have a Bullish Vector, AND price is > Open (Green), ENTER.
                     # Stop Loss: Session Low OR Recent Low.
                     
                     entry_price = current_candle[4]
                     raw_sl = session_low * (1 - self.config.stop_loss_buffer)
                     stop_loss = round(raw_sl / tick_size) * tick_size
                     
                     if entry_price > stop_loss:
                         signal = {
                            'type': 'brings_reversal',
                            'direction': 'buy',
                            'entry_price': entry_price,
                            'stop_loss': stop_loss,
                            'take_profit': 0, # Trailing
                            'session_high': session_high
                         }
                         
            elif bias == "SHORT":
                if current_vector and self.pvsra.is_bearish_vector(current_vector):
                     entry_price = current_candle[4]
                     raw_sl = session_high * (1 + self.config.stop_loss_buffer)
                     stop_loss = round(raw_sl / tick_size) * tick_size
                     
                     if entry_price < stop_loss:
                         signal = {
                            'type': 'brings_reversal',
                            'direction': 'sell',
                            'entry_price': entry_price,
                            'stop_loss': stop_loss,
                            'take_profit': 0, # Trailing
                            'session_low': session_low
                         }

            if signal:
                signal['position_size'] = self._calculate_position_size(signal['entry_price'], signal['stop_loss'])
                signal['instrument'] = self.config.deribit_symbol
                signals.append(signal)
                
                # Log the signal
                self.position_logger.log_trade_signal(now, signal)

            return signals
            
        except Exception as e:
            logger.error(f"Error in Brings Strategy Scan: {e}")
            self.position_logger.log_error(datetime.now(self.timezone), f"Scan Error: {str(e)}")
            return []

    def _calculate_position_size(self, entry_price: float, stop_loss: float) -> float:
        """Calculate position size using RiskManager"""
        if not self.risk_manager:
            logger.warning("RiskManager not available, using default small size")
            return 100.0 # Safety fallback
            
        risk_pct = self.config.risk_per_trade_pct
        
        # 1. Use RiskManager for robust calculation (Equity, Max Risk, Leverage Cap)
        # Returns size in BTC (Quantity = Risk / Distance) which effectively models Linear risk
        # For Inverse, we convert this to contracts below.
        sizing = self.risk_manager.calculate_futures_quantity(
            entry_price=entry_price,
            sl_price=stop_loss,
            risk_pct=risk_pct,
            leverage_max=5 # Or self.config.leverage_max if available
        )
        
        if "error" in sizing:
            logger.error(f"Sizing Error: {sizing['error']}")
            return 0.0
            
        qty_btc = sizing['quantity_btc']
        
        # 2. Convert to Inverse Contracts (USD) if needed
        # Formula: Contracts = (Risk / Diff) * Entry / ContractVal
        # Since qty_btc = (Risk / Diff), then Contracts = qty_btc * Entry / ContractVal
        
        symbol = self.config.deribit_symbol
        is_inverse = "PERPETUAL" in symbol and "USDC" not in symbol
        
        size = 0.0
        if is_inverse:
             if "BTC" in symbol: contract_val = 10.0 
             else: contract_val = 1.0
             
             qty_usd_raw = qty_btc * entry_price
             # Deribit 'amount' for Inverse is in USD, but must be multiple of contract_val.
             # We must send USD amount (e.g. 18620), NOT number of contracts.
             steps = int(qty_usd_raw / contract_val)
             size = steps * int(contract_val)
        else:
             # Linear
             size = round(qty_btc, 4)

        logger.info(f"Sizing {symbol}: Eq=${sizing['equity']:,.2f} Risk%={risk_pct} Risk=${sizing['max_loss_usd']:.2f} Size={size} (Lev: {sizing['effective_leverage']:.2f}x)")
        
        return size

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        """Execute the trade"""
        if self.last_traded_date == datetime.now(self.timezone).date():
            logger.info("Already traded Brings today. Skipping.")
            return False
            
        logger.info(f"Executing Brings Strategy {signal['direction']} on {signal['instrument']}")
        
        amount = signal['position_size']
        if not amount or amount <= 0:
            logger.error(f"Invalid position size: {amount}")
            return False

        # Place Entry Order directly via Client (Bypass OrderManager to avoid missing methods)
        try:
            # ... (Entry Logic) ...
            order = None
            if signal['direction'] == 'buy':
                order = self.client.buy(
                    instrument_name=signal['instrument'],
                    amount=amount,
                    type="market",
                    label="brings_entry"
                )
            else:
                order = self.client.sell(
                    instrument_name=signal['instrument'],
                    amount=amount,
                    type="market",
                    label="brings_entry"
                )
            
            if not order:
                # Try to get last error from client if possible, or just log generic
                logger.error("Brings Entry Failed: client.buy/sell returned None")
                self.position_logger.log_error(datetime.now(self.timezone), "Entry Failed: API execution returned None")
                return False
                
            if "error" in order:
                error_msg = order["error"].get("message", "Unknown API error")
                error_code = order["error"].get("code", "Unknown")
                logger.error(f"Brings Entry Failed: {error_code} - {error_msg}")
                self.position_logger.log_error(datetime.now(self.timezone), f"API Error {error_code}: {error_msg}")
                return False

            # Entry Successful - Capture Average Price
            # Note: For Market Order, price might be in 'average_price' or we assume close to 'price' if limit
            exec_price = float(signal['entry_price']) # Estimating from signal for now, ideally get from fill
            if 'average_price' in order:
                 exec_price = float(order['average_price'])
                 
            self.position_logger.log_execution(
                datetime.now(self.timezone), 
                True, 
                f"Executed {signal['direction']} {amount} on {signal['instrument']} @ {exec_price}"
            )
            
            # Save Virtual State
            self.active_position = {
                'instrument': signal['instrument'],
                'direction': signal['direction'],
                'quantity': amount,
                'entry_price': exec_price,
                'sl_price': signal.get('stop_loss'),
                'start_time': datetime.now().isoformat()
            }
            self.state_manager.save_state(self.state_file, self.active_position)
            
            # Place Stop Loss Order
            if 'stop_loss' in signal:
                sl_side = 'sell' if signal['direction'] == 'buy' else 'buy'
                sl_price = signal['stop_loss']
                
                sl_order = None
                if sl_side == 'buy':
                    sl_order = self.client.buy(
                        instrument_name=signal['instrument'],
                        amount=amount,
                        type="stop_market",
                        trigger="mark_price",
                        price=None,
                        trigger_price=sl_price,
                        label="brings_sl",
                        reduce_only=True
                    )
                else:
                    sl_order = self.client.sell(
                        instrument_name=signal['instrument'],
                        amount=amount,
                        type="stop_market",
                        trigger="mark_price",
                        price=None,
                        trigger_price=sl_price,
                        label="brings_sl",
                        reduce_only=True
                    )
                    
                if sl_order:
                    self.position_logger.log_execution(datetime.now(self.timezone), True, f"Placed SL at {sl_price}")
                    # Update SL in state
                    self.active_position['sl_price'] = sl_price
                    self.state_manager.save_state(self.state_file, self.active_position)
                else:
                     self.position_logger.log_execution(datetime.now(self.timezone), False, f"Failed to place SL")

            self.last_traded_date = datetime.now(self.timezone).date()
            return True
                
        except Exception as e:
            logger.error(f"Exception during Brings execution: {e}")
            self.position_logger.log_error(datetime.now(self.timezone), f"Exception: {str(e)}")
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """Manage active positions with Trailing Stop using Virtual State"""
        if not hasattr(self, 'active_position') or not self.active_position:
            return {}
            
        stats = {'closed_tp': 0, 'closed_sl': 0, 'trailing_updated': 0}
        
        pos = self.active_position
        # Virtual State Data
        entry_price = float(pos['entry_price'])
        current_sl = float(pos.get('sl_price', 0))
        direction = pos['direction']
        size = float(pos['quantity'])
        instrument = pos['instrument']
        
        # Get Current Price from Ticker
        ticker = self.client.get_ticker(instrument)
        current_price = ticker.get('last_price') if ticker else None
        
        if not current_price:
            return stats

        activation_pct = 0.005 # 0.5% profit to activate
        trail_pct = 0.005 # Trail by 0.5%
        
        updated = False
        new_sl = None
        current_profit_pct = 0
        
        if direction == 'buy':
            current_profit_pct = (current_price - entry_price) / entry_price
            if current_profit_pct > activation_pct:
                # Calculate new SL
                potential_sl = current_price * (1 - trail_pct)
                if potential_sl > current_sl:
                    new_sl = potential_sl
        elif direction == 'sell':
            current_profit_pct = (entry_price - current_price) / entry_price
            if current_profit_pct > activation_pct:
                potential_sl = current_price * (1 + trail_pct)
                # For Short, SL moves DOWN
                if current_sl == 0 or potential_sl < current_sl:
                    new_sl = potential_sl
                
        if new_sl:
            # Update the order via Deribit Client
            try:
                # 1. Find existing SL order
                open_orders = self.client.get_open_orders_by_instrument(instrument, type="stop_market")
                sl_order = next((o for o in open_orders if o['label'] == "brings_sl"), None)
                
                if sl_order:
                    # 2. Edit the order
                    result = self.client.edit(
                        order_id=sl_order['order_id'],
                        amount=size, # Keep same size from virtual state
                        price=None,
                        trigger_price=new_sl
                    )
                    
                    if result:
                        self.position_logger.log_trailing_update(datetime.now(self.timezone), {
                            'current_price': current_price,
                            'new_sl': new_sl,
                            'profit_pct': current_profit_pct
                        })
                        stats['trailing_updated'] = 1
                        logger.info(f"Updated SL to {new_sl}")
                        
                        # Update Virtual State
                        self.active_position['sl_price'] = new_sl
                        self.state_manager.save_state(self.state_file, self.active_position)
                    else:
                        logger.error(f"Failed to edit SL order: {result}")
                        self.position_logger.log_error(datetime.now(self.timezone), "Failed to update SL order")
                else:
                    logger.warning("No active SL order found to update")
                    
            except Exception as e:
                logger.error(f"Error updating trailing stop: {e}")
                self.position_logger.log_error(datetime.now(self.timezone), f"Trailing Update Error: {str(e)}")
        
        return stats
