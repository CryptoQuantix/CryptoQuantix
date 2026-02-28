import time
import logging
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.strategies.base_strategy import BaseStrategy
from src.core.deribit_client import DeribitClient
from src.core.state_manager import StateManager
from config import SmartMoneyConfig
from src.utils.metrics import StrategyMetrics
from src.utils.smart_money_position_logger import SmartMoneyPositionLogger

logger = logging.getLogger(__name__)

class AdvancedFlowAnalyzer:
    """
    Advanced Order Flow Analyzer using CCXT.
    Calculates CVD (Cumulative Volume Delta) and detects Absorption (Whale Walls).
    """
    
    def __init__(self, symbol: str = "BTC/USDT"):
        self.symbol = symbol
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'} # We analyze Spot flow for "Whale" activity
        })

    def analyze_market_structure(self, limit: int = 1000, 
                               min_vol_threshold: float = 10.0,
                               delta_ratio_threshold: float = 0.15,
                               price_change_threshold: float = 0.01) -> Optional[Dict[str, Any]]:
        """
        Downloads recent trades and checks for Price/Delta divergence (Absorption).
        """
        try:
            logger.debug(f"Fetching {limit} trades from Binance for {self.symbol}...")
            
            # 1. Download trades (Tick Data)
            trades = self.exchange.fetch_trades(self.symbol, limit=limit)
            if not trades:
                logger.warning(f"No trades returned from Binance for {self.symbol}")
                return None
            
            logger.debug(f"Received {len(trades)} trades from Binance")
            df = pd.DataFrame(trades)
            
            # 2. Price Data
            first_price = df['price'].iloc[0]
            last_price = df['price'].iloc[-1]
            
            # Calculate price change percentage
            price_change_pct = ((last_price - first_price) / first_price) * 100
            
            logger.debug(f"Price movement: ${first_price:,.2f} -> ${last_price:,.2f} ({price_change_pct:+.4f}%)")
            
            # 3. Delta Data (Aggressors)
            # CCXT normalizes taker side: 'buy' = Taker Buy (Green), 'sell' = Taker Sell (Red)
            buy_vol = df[df['side'] == 'buy']['amount'].sum()
            sell_vol = df[df['side'] == 'sell']['amount'].sum()
            
            delta = buy_vol - sell_vol
            total_vol = buy_vol + sell_vol
            
            logger.debug(f"Volume analysis: Buy={buy_vol:.2f}, Sell={sell_vol:.2f}, Delta={delta:+.2f}, Total={total_vol:.2f}")

            # --- CORE LOGIC: ABSORPTION DETECTION ---
            signal = "NEUTRAL"
            reason = ""
            
            # Check if volume is sufficient
            if total_vol <= min_vol_threshold:
                logger.debug(f"Volume too low: {total_vol:.2f} <= {min_vol_threshold} threshold")
            else:
                logger.debug(f"Volume sufficient: {total_vol:.2f} > {min_vol_threshold}")
                
                # SCENARIO 1: BULLISH ABSORPTION (Whale Wall)
                # Sellers are aggressive (Delta Very Negative) BUT price holds or rises
                delta_threshold_neg = -(total_vol * delta_ratio_threshold)
                delta_threshold_pos = (total_vol * delta_ratio_threshold)
                
                logger.debug(f"Delta thresholds: Negative < {delta_threshold_neg:.2f}, Positive > {delta_threshold_pos:.2f}")
                
                if delta < delta_threshold_neg:
                    logger.debug(f"Strong selling pressure detected: Delta {delta:.2f} < {delta_threshold_neg:.2f}")
                    if price_change_pct >= -price_change_threshold:
                        signal = "ABSORPTION_BUY"
                        reason = f"Whale Wall: Strong selling (Delta {delta:.2f}) absorbed. Price change: {price_change_pct:.4f}%"
                        logger.debug(f"✓ BULLISH ABSORPTION: Price held despite selling ({price_change_pct:+.4f}% >= -{price_change_threshold}%)")
                    else:
                        logger.debug(f"✗ No absorption: Price fell too much ({price_change_pct:.4f}% < -{price_change_threshold}%)")

                # SCENARIO 2: BEARISH ABSORPTION (Iceberg)
                # Buyers are aggressive (Delta Very Positive) BUT price holds or falls
                elif delta > delta_threshold_pos:
                    logger.debug(f"Strong buying pressure detected: Delta {delta:.2f} > {delta_threshold_pos:.2f}")
                    if price_change_pct <= price_change_threshold:
                        signal = "ABSORPTION_SELL"
                        reason = f"Iceberg Order: Strong buying (Delta {delta:.2f}) absorbed. Price change: {price_change_pct:.4f}%"
                        logger.debug(f"✓ BEARISH ABSORPTION: Price held despite buying ({price_change_pct:+.4f}% <= {price_change_threshold}%)")
                    else:
                        logger.debug(f"✗ No absorption: Price rose too much ({price_change_pct:.4f}% > {price_change_threshold}%)")
                else:
                    logger.debug(f"Delta neutral: {delta:.2f} within [{delta_threshold_neg:.2f}, {delta_threshold_pos:.2f}]")
            
            result = {
                "price_start": first_price,
                "price_end": last_price,
                "price_change_pct": price_change_pct,
                "delta": delta,
                "total_volume": total_vol,
                "signal": signal,
                "reason": reason
            }
            
            logger.debug(f"Flow analysis complete: Signal={signal}")
            return result

        except Exception as e:
            logger.error(f"Error in AdvancedFlowAnalyzer: {e}", exc_info=True)
            return None


class SmartMoneyStrategy(BaseStrategy):
    """
    Smart Money Strategy 2.0 🐋
    Combines:
    1. Time Window (London/NY Overlap)
    2. Liquidity Hunter (Sweep & Reclaim)
    3. Order Flow Confirmation (CVD & Absorption)
    """

    def __init__(self, client: DeribitClient, config: SmartMoneyConfig, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)
        self.flow_analyzer = AdvancedFlowAnalyzer(symbol=config.binance_symbol)
        
        # Persistence
        self.state_manager = StateManager()
        self.state_file = f"smart_money_{config.binance_symbol.replace('/','_')}_state.json"
        
        # Load persisted state
        saved_state = self.state_manager.load_state(self.state_file)
        if saved_state:
            self.active_position = saved_state
            logger.info(f"Restored active position from state: {self.active_position}")
        else:
            self.active_position = None
        
        # Initialize metrics
        self.metrics = StrategyMetrics("Smart Money")
        
        # Initialize position logger
        self.position_logger = SmartMoneyPositionLogger()
        self.position_logger.log_session_start()
        
        # Sync state with exchange
        self.sync_state()

    def sync_state(self):
        """
        Sync local state with actual exchange state.
        Recovers from 'amnesia' if bot crashed or was restarted on new machine.
        """
        try:
            # Smart Money usually trades one instrument (BTC-PERPETUAL)
            symbol = "BTC-PERPETUAL" # or self.config.deribit_symbol if available
            # Just in case config doesn't have it, assume BTC-PERPETUAL as per scan logic
            
            currency = "BTC"
            
            # 1. Check if we really have a position on exchange
            # Smart Money trades perps, so specify kind='future'
            positions = self.client.get_positions(currency, kind="future")
            target_pos = next((p for p in positions if p['instrument_name'] == symbol), None)
            
            if not target_pos:
                if self.active_position:
                    logger.warning(f"[Smart Money] Local state has position but Exchange does NOT. Clearing local state.")
                    self.active_position = None
                    self.state_manager.delete_state(self.state_file)
                return

            # 2. Position exists on Exchange. Check if it belongs to THIS strategy.
            # We check if there is an open SL order with label 'smart_money_sl'
            open_orders = self.client.get_open_orders_by_instrument(symbol, type="stop_market")
            sl_order = next((o for o in open_orders if o.get('label') == "smart_money_sl"), None)
            
            if sl_order:
                # 3. It's OUR position! Reconstruct state if missing.
                if not self.active_position:
                    logger.info("[Smart Money] Found orphan position on exchange! Adopting it.")
                    
                    # Try to find TP order too for complete state
                    open_limit_orders = self.client.get_open_orders_by_instrument(symbol, type="limit")
                    tp_order = next((o for o in open_limit_orders if o.get('label') == "sm_close_tp" or o.get('label') == "smart_money_tp"), None)
                    tp_price = tp_order['price'] if tp_order else 0
                    
                    self.active_position = {
                        "instrument": symbol,
                        "direction": target_pos['direction'],
                        "entry_price": target_pos['average_price'],
                        "sl_price": sl_order['trigger_price'] if 'trigger_price' in sl_order else sl_order.get('stop_price'),
                        "tp_price": tp_price,
                        "risk_distance": abs(target_pos['average_price'] - (sl_order['trigger_price'] if 'trigger_price' in sl_order else sl_order.get('stop_price'))), # Approximation
                        "quantity": target_pos['size'],
                        "entry_time": datetime.now() # Approx
                    }
                    self.state_manager.save_state(self.state_file, self.active_position)
                    
                    self.position_logger.log_execution_result(
                        datetime.now(), 
                        True, 
                        symbol,
                        f"RECOVERY: Adopted existing position {target_pos['size']} {target_pos['direction']} @ {target_pos['average_price']}"
                    )
            else:
                if self.active_position:
                    logger.warning("[Smart Money] Position exists locally and on exchange, but SL uses different label. Keeping local state.")
                
        except Exception as e:
            logger.error(f"Error syncing Smart Money state: {e}")

    def is_time_window_active(self) -> bool:
        """Check if we are in the active trading window"""
        now = datetime.now()
        current_hour = now.hour
        return self.config.time_window_start <= current_hour < self.config.time_window_end

    def check_liquidity_sweep(self, ohlcv: List[List[float]]) -> Optional[str]:
        """
        Check for Liquidity Sweep pattern.
        """
        if len(ohlcv) < self.config.liquidity_lookback_periods + 1:
            return None
            
        current = ohlcv[-1]
        curr_low, curr_close = current[3], current[4]
        curr_high = current[2]
        
        lookback = ohlcv[-(self.config.liquidity_lookback_periods + 1):-1]
        
        lowest_low = min(c[3] for c in lookback)
        highest_high = max(c[2] for c in lookback)
        
        # Bullish Sweep (Long)
        if curr_low < lowest_low and curr_close > lowest_low:
            logger.info(f"Bullish Sweep detected! Low {curr_low} < PrevLow {lowest_low}, Close {curr_close} > PrevLow")
            return "LONG"
            
        # Bearish Sweep (Short)
        if curr_high > highest_high and curr_close < highest_high:
            logger.info(f"Bearish Sweep detected! High {curr_high} > PrevHigh {highest_high}, Close {curr_close} < PrevHigh")
            return "SHORT"
            
        return None

    def scan(self) -> List[Dict[str, Any]]:
        self.metrics.increment('scans')
        signals = []
        
        # 1. Time Window Check
        current_hour = datetime.now().hour
        if not self.is_time_window_active():
            self.metrics.increment('time_window_inactive')
            logger.debug(f"Outside trading window. Current hour: {current_hour}, Active: {self.config.time_window_start}-{self.config.time_window_end}")
            return signals
            
        self.metrics.increment('time_window_active')
        logger.debug(f"✓ Inside Trading Window (Hour: {current_hour})")
        
        # 2. Liquidity Hunter (Price Action)
        # We use the instrument from config or default to BTC-PERPETUAL for Deribit
        instrument = "BTC-PERPETUAL" 
        
        ohlcv = self.client.get_ohlcv(instrument, timeframe=self.config.timeframe, limit=50)
        if not ohlcv:
            logger.warning(f"Could not fetch OHLCV data for {instrument}")
            return signals
        
        logger.debug(f"Fetched {len(ohlcv)} candles for {instrument} ({self.config.timeframe})")
        sweep_direction = self.check_liquidity_sweep(ohlcv)
        
        if not sweep_direction:
            logger.debug("No liquidity sweep detected in current market structure")
            return signals
        
        self.metrics.increment('sweeps_detected')
        logger.info(f"Liquidity Sweep detected ({sweep_direction}). Checking Order Flow...")
        
        # Log sweep to position history
        self.position_logger.log_sweep_detected(
            timestamp=datetime.now(),
            direction=sweep_direction,
            high=ohlcv[-1][2],
            low=ohlcv[-1][3],
            prev_high=ohlcv[-2][2],
            prev_low=ohlcv[-2][3]
        )
        
        # 3. Order Flow Confirmation (CVD & Absorption)
        flow_analysis = self.flow_analyzer.analyze_market_structure(
            min_vol_threshold=self.config.absorption_min_vol,
            delta_ratio_threshold=self.config.absorption_delta_ratio,
            price_change_threshold=self.config.absorption_price_threshold
        )
        
        if not flow_analysis:
            logger.warning("Could not fetch Order Flow data from Binance")
            self.position_logger.log_error(datetime.now(), "Could not fetch Order Flow data from Binance")
            return signals
        
        self.metrics.increment('flow_analyzed')
        logger.debug(f"Order Flow: Signal={flow_analysis['signal']}, Delta={flow_analysis['delta']:.2f}, Vol={flow_analysis['total_volume']:.2f}, Price Δ={flow_analysis['price_change_pct']:.4f}%")
        logger.info(f"Order Flow Analysis: {flow_analysis['signal']} | Delta: {flow_analysis['delta']:.2f} | Price Chg: {flow_analysis['price_change_pct']:.4f}%")
        
        # Log flow analysis to position history
        self.position_logger.log_flow_analysis(
            timestamp=datetime.now(),
            flow_data=flow_analysis
        )
        
        # Confluence Check
        if sweep_direction == "LONG":
            if flow_analysis['signal'] == "ABSORPTION_BUY":
                logger.info(">>> CONFLUENCE: Bullish Sweep + Bullish Absorption <<<")
                self.metrics.increment('signals_generated')
                
                signal_data = {
                    "type": "smart_money",
                    "direction": "buy",
                    "instrument": instrument,
                    "reason": f"Bullish Sweep + Absorption ({flow_analysis['reason']})",
                    "stop_loss_price": ohlcv[-1][3] # Low of the sweep candle
                }
                
                # Log signal generation
                self.position_logger.log_signal_generated(
                    timestamp=datetime.now(),
                    signal=signal_data
                )
                
                signals.append(signal_data)
            else:
                # Log rejection
                self.position_logger.log_signal_rejected(
                    timestamp=datetime.now(),
                    sweep_direction=sweep_direction,
                    flow_signal=flow_analysis['signal'],
                    reason=f"Bullish Sweep detected but flow shows {flow_analysis['signal']}, need ABSORPTION_BUY"
                )
                logger.debug(f"Bullish Sweep detected but no Absorption confirmation. Flow signal: {flow_analysis['signal']}")
                
        elif sweep_direction == "SHORT":
            if flow_analysis['signal'] == "ABSORPTION_SELL":
                logger.info(">>> CONFLUENCE: Bearish Sweep + Bearish Absorption <<<")
                self.metrics.increment('signals_generated')
                
                signal_data = {
                    "type": "smart_money",
                    "direction": "sell",
                    "instrument": instrument,
                    "reason": f"Bearish Sweep + Absorption ({flow_analysis['reason']})",
                    "stop_loss_price": ohlcv[-1][2] # High of the sweep candle
                }
                
                # Log signal generation
                self.position_logger.log_signal_generated(
                    timestamp=datetime.now(),
                    signal=signal_data
                )
                
                signals.append(signal_data)
            else:
                # Log rejection
                self.position_logger.log_signal_rejected(
                    timestamp=datetime.now(),
                    sweep_direction=sweep_direction,
                    flow_signal=flow_analysis['signal'],
                    reason=f"Bearish Sweep detected but flow shows {flow_analysis['signal']}, need ABSORPTION_SELL"
                )
                logger.debug(f"Bearish Sweep detected but no Absorption confirmation. Flow signal: {flow_analysis['signal']}")
            
        # Validate and Round Signals
        final_signals = []
        for s in signals:
            if "stop_loss_price" in s:
                tick_size = 0.5 if "BTC" in s['instrument'] else 0.05
                s['stop_loss_price'] = round(s['stop_loss_price'] / tick_size) * tick_size
            final_signals.append(s)
            
        return final_signals

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        direction = signal["direction"]
        instrument = signal["instrument"]
        reason = signal["reason"]
        sl_price = signal.get("stop_loss_price")
        
        logger.info(f"Executing Smart Money {direction} on {instrument}")
        logger.info(f"Reason: {reason}")
        
        if not sl_price:
            logger.error("No Stop Loss price provided, cannot execute.")
            self.position_logger.log_execution_result(datetime.now(), False, instrument, "No Stop Loss price provided")
            return False
            
        # 1. Get current price
        ticker = self.client.get_ticker(instrument)
        current_price = ticker.get('last_price') if ticker else None
        
        if not current_price:
            logger.error("Could not get current price for sizing")
            self.position_logger.log_execution_result(datetime.now(), False, instrument, "Could not get current price for sizing")
            return False
            
        # 2. Calculate Size & Exit Levels
        risk_manager = self.dependencies['risk_manager']
        
        # Sizing
        sizing = risk_manager.calculate_futures_quantity(
            current_price, 
            sl_price, 
            risk_pct=self.config.risk_per_trade_pct,
            leverage_max=self.config.leverage_max
        )
        
        if "error" in sizing:
            logger.error(f"Sizing error: {sizing['error']}")
            self.position_logger.log_execution_result(datetime.now(), False, instrument, f"Sizing error: {sizing['error']}")
            return False
            
        qty_btc = sizing['quantity_btc']
        logger.info(f"Sizing: {qty_btc:.4f} BTC | Lev: {sizing['effective_leverage']:.2f}x | Risk: ${sizing['max_loss_usd']:.2f}")

        # Exit Levels (TP)
        exits = risk_manager.calculate_exit_levels(
            current_price, 
            sl_price, 
            rr_ratio=self.config.risk_reward_ratio
        )
        tp_price = exits['tp_price']
        logger.info(f"Targets: Entry {current_price} | SL {sl_price} | TP {tp_price} (R:R {self.config.risk_reward_ratio})")

        # 3. Convert to Contracts (USD)
        contract_size_usd = 10.0
        qty_usd_raw = qty_btc * current_price
        qty_contracts = int(round(qty_usd_raw / contract_size_usd) * contract_size_usd)
        
        if qty_contracts < contract_size_usd:
            logger.warning("Quantity too small for min contract")
            self.position_logger.log_execution_result(datetime.now(), False, instrument, "Quantity too small for min contract")
            return False

        # 4. Execute Trade
        try:
            success = self.dependencies['order_manager'].execute_smart_money_trade(
                instrument, direction, qty_contracts, sl_price
            )
            
            if success:
                self.metrics.increment('entries_executed')
                
                # Log successful execution
                self.position_logger.log_execution_result(
                    timestamp=datetime.now(),
                    success=True,
                    instrument=instrument,
                    details=f"Direction: {direction}, contracts: {qty_contracts}, Entry: ${current_price:,.2f}, SL: {sl_price}, TP: {tp_price}"
                )
                
                # Store position details for management
                self.active_position = {
                    "instrument": instrument,
                    "direction": direction,
                    "entry_price": current_price,
                    "sl_price": sl_price,
                    "tp_price": tp_price,
                    "risk_distance": exits['risk_distance'],
                    "quantity": qty_contracts,
                    "entry_time": datetime.now()
                }
                # Save state
                self.state_manager.save_state(self.state_file, self.active_position)
                logger.info("Position stored and persisted for active management")
                return True
            else:
                self.metrics.increment('entries_failed')
                
                # Log failed execution
                self.position_logger.log_execution_result(
                    timestamp=datetime.now(),
                    success=False,
                    instrument=instrument,
                    details="Order placement failed in OrderManager"
                )
                return False
                
        except Exception as e:
            logger.error(f"Entry execution exception: {e}")
            self.position_logger.log_error(datetime.now(), f"Entry execution exception: {str(e)}")
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """
        Active Position Management:
        1. Check TP hit
        2. Break-Even Trigger (at 1R profit)
        3. Trailing Stop (Dynamic)
        """
        if not hasattr(self, 'active_position') or not self.active_position:
            return {}
            
        pos = self.active_position
        instrument = pos['instrument']
        
        # Get current price
        ticker = self.client.get_ticker(instrument)
        current_price = ticker.get('last_price') if ticker else None
        
        if not current_price:
            return {}
            
        is_long = pos['direction'] == 'buy'
        entry_price = pos['entry_price']
        current_sl = pos['sl_price']
        tp_price = pos['tp_price']
        risk_dist = pos['risk_distance']
        
        # 1. Check Take Profit
        if (is_long and current_price >= tp_price) or (not is_long and current_price <= tp_price):
            logger.info(f"Take Profit hit at {current_price}! Closing position.")
            pnl = (current_price - entry_price) * (1 if is_long else -1) # Simplified PnL
            
            # Targeted Close: Use reduce_only market order for specific size
            qty = pos.get('quantity', 0)
            if qty > 0:
                if is_long:
                     self.client.sell(instrument, qty, type="market", label="sm_close_tp", reduce_only=True)
                else:
                     self.client.buy(instrument, qty, type="market", label="sm_close_tp", reduce_only=True)
            else:
                # Fallback if quantity missing (shouldn't happen with correct state)
                self.client.close_position(instrument, type_="market")

            # Log TP Hit
            self.position_logger.log_tp_hit(datetime.now(), current_price, pnl)
            
            self.active_position = None
            self.state_manager.delete_state(self.state_file)
            return {"closed_tp": 1}
            
        # 2. Trailing Stop Logic
        new_sl = current_sl
        update_reason = ""
        
        if is_long:
            # Profit distance
            profit = current_price - entry_price
            
            # Break-Even Trigger: If profit > 1R, move SL to Entry
            if profit >= risk_dist and current_sl < entry_price:
                logger.info(f"Profit > 1R. Moving SL to Break-Even: {entry_price}")
                new_sl = entry_price
                update_reason = "Break-Even (Profit > 1R)"
                
            # Trailing: If price moves up, trail SL at 1R distance
            # Ideal SL = Current Price - 1R
            ideal_sl = current_price - risk_dist
            if ideal_sl > new_sl:
                # Only move SL up
                new_sl = ideal_sl
                logger.info(f"Trailing SL updated: {new_sl:.2f}")
                update_reason = f"Trailing (Price {current_price})"
                
        else: # Short
            profit = entry_price - current_price
            
            # Break-Even
            if profit >= risk_dist and current_sl > entry_price:
                logger.info(f"Profit > 1R. Moving SL to Break-Even: {entry_price}")
                new_sl = entry_price
                update_reason = "Break-Even (Profit > 1R)"
                
            # Trailing
            ideal_sl = current_price + risk_dist
            if ideal_sl < new_sl:
                # Only move SL down
                new_sl = ideal_sl
                logger.info(f"Trailing SL updated: {new_sl:.2f}")
                update_reason = f"Trailing (Price {current_price})"
                
        # 3. Update SL on Exchange if changed
        if new_sl != current_sl:
            logger.info(f"Updating SL order on exchange to {new_sl}")
            # Log SL update
            self.position_logger.log_sl_update(datetime.now(), new_sl, update_reason)
            
            # Find existing SL order
            open_orders = self.client.get_open_orders_by_instrument(instrument, type="stop_market")
            sl_order = next((o for o in open_orders if o['label'] == "smart_money_sl"), None)
            
            if sl_order:
                logger.info(f"Updating SL order {sl_order['order_id']} to {new_sl}")
                # Round to tick size
                tick_size = 0.5 if "BTC" in instrument else 0.05
                new_sl = round(new_sl / tick_size) * tick_size
                
                result = self.client.edit(
                    order_id=sl_order['order_id'],
                    amount=pos['quantity'],
                    trigger_price=new_sl
                )
                if result:
                    logger.info("SL order updated successfully")
                    self.active_position['sl_price'] = new_sl
                    self.state_manager.save_state(self.state_file, self.active_position)
                else:
                    logger.error("Failed to update SL order")
            else:
                 logger.warning("No active SL order found to update")
            
        return {"status": "managing", "current_pnl": current_price - entry_price}
