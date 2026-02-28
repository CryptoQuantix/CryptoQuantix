"""
W/M Formation Trading Strategy

Detects psychological price formations (W and M patterns) using PVSRA methodology.
Trades based on multi-timeframe confirmation, trend filtering, and smart stop-loss placement.

W Formation (Bullish):
  Phase 1: Aggressive dump (3+ red vector candles)
  Phase 2: Retracement (20-70%)
  Phase 3: Liquidity sweep below Phase 1 low
  Phase 4: Confirmation (Reclaim of Phase 1 Low OR Breakout above 50 EMA)

M Formation (Bearish):
  Phase 1: Aggressive pump (3+ green vector candles)
  Phase 2: Pullback (20-70%)
  Phase 3: Liquidity sweep above Phase 1 high
  Phase 4: Confirmation (Reclaim of Phase 1 High OR Breakdown below 50 EMA)
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from src.strategies.base_strategy import BaseStrategy
from src.strategies.pvsra_analyzer import PVSRAAnalyzer, VectorType
from src.utils.wm_position_logger import WMPositionLogger
from src.core.deribit_client import DeribitClient
from config import WMFormationConfig

logger = logging.getLogger(__name__)


class WMFormationStrategy(BaseStrategy):
    """
    W/M Formation trading strategy based on PVSRA methodology.
    
    Detects psychological price formations and enters trades with
    smart stop-loss placement to avoid liquidity sweeps.
    """
    
    def __init__(self, client: DeribitClient, config: WMFormationConfig, dependencies: Dict[str, Any]):
        super().__init__(client, config, dependencies)
        self.dependencies = dependencies
        self.pvsra = PVSRAAnalyzer(config.binance_symbol)
        self.position_logger = WMPositionLogger(config.position_log_file)
        self.position_logger.log_session_start()
        
        self.active_position = None
        
        logger.info(f"W/M Formation Strategy initialized for {config.deribit_symbol}")
        logger.info(f"Primary TF: {config.primary_timeframe}, Mode: {config.entry_mode}")
    
    def scan(self, backtest_data: Dict[str, Any] = None, backtest_indicators: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Scan for W and M formations with vector candle confirmation.
        """
        try:
            signals = []
            
            # Use backtest data if provided, otherwise fetch live data
            if backtest_data:
                primary_data = backtest_data
                now = primary_data.get('timestamp')
            else:
                primary_data = self.pvsra.get_latest_vectors(
                    timeframe=self.config.timeframe,
                    limit=self.config.ema_slow + 100
                )
            
            if not primary_data['ohlcv'] or not primary_data['vectors']:
                logger.warning("No data available for W/M formation analysis")
                return signals
            
            # Calculate EMAs
            if backtest_indicators and 'emas' in backtest_indicators:
                emas = backtest_indicators['emas']
            else:
                emas = self._calculate_emas(primary_data['ohlcv'])
            
            # Calculate RSI
            if backtest_indicators and 'rsi' in backtest_indicators:
                rsi = backtest_indicators['rsi']
            else:
                rsi = self._calculate_rsi(primary_data['ohlcv'], self.config.rsi_period)
                
            # --- Trend Filter ---
            is_bullish_trend = True
            is_bearish_trend = True
            
            if self.config.trend_filter_enabled:
                # If backtest passed a specific trend indicator, use it.
                if backtest_indicators and 'trend_bullish' in backtest_indicators:
                    is_bullish_trend = backtest_indicators['trend_bullish']
                    is_bearish_trend = not is_bullish_trend
                    if 'trend_bearish' in backtest_indicators:
                         is_bearish_trend = backtest_indicators['trend_bearish']
                else:
                     # Fallback for Live Trading: Match Backtest Logic (1h Trend Proxy on 15m)
                     # Backtest used 800 EMA on 15m (approx 200 EMA on 1h)
                     current_price = primary_data['ohlcv'][-1][4]
                     # Ensure we have enough data for 800 EMA
                     if 'ema_800' in emas:
                        trend_ema = emas['ema_800'][-1]
                        is_bullish_trend = current_price > trend_ema
                        is_bearish_trend = current_price < trend_ema
                     else:
                        # Fallback to 200 if 800 not available (e.g. insufficient history)
                        logger.warning("EMA 800 not available for trend filter, falling back to EMA 200")
                        trend_ema = emas['ema_200'][-1]
                        is_bullish_trend = current_price > trend_ema
                        is_bearish_trend = current_price < trend_ema
            
            # Check for W Formation (Bullish)
            if is_bullish_trend:
                w_formation = self._detect_w_formation(
                    primary_data['ohlcv'],
                    primary_data['vectors'],
                    emas,
                    rsi
                )
                
                if w_formation:
                    logger.debug("W Formation detected! Checking confirmation...")
                    signal = self._confirm_formation(w_formation, primary_data['ohlcv'], 'W')
                    if signal:
                        signals.append(signal)
            
            # Check for M Formation (Bearish)
            if is_bearish_trend:
                m_formation = self._detect_m_formation(
                    primary_data['ohlcv'],
                    primary_data['vectors'],
                    emas,
                    rsi
                )
                
                if m_formation:
                    logger.debug("M Formation detected! Checking confirmation...")
                    signal = self._confirm_formation(m_formation, primary_data['ohlcv'], 'M')
                    if signal:
                        signals.append(signal)
            
            return signals

        except Exception as e:
            logger.error(f"Error in W/M Strategy Scan: {e}")
            self.position_logger.log_error(datetime.now(), f"Scan Error: {str(e)}")
            return []
    
    def _calculate_emas(self, ohlcv: List[List]) -> Dict[str, np.ndarray]:
        """Calculate EMAs for the given OHLCV data"""
        closes = np.array([candle[4] for candle in ohlcv])
        
        return {
            'ema_50': self._ema(closes, self.config.ema_fast),
            'ema_60': self._ema(closes, self.config.ema_medium),
            'ema_200': self._ema(closes, self.config.ema_slow),
            'ema_223': self._ema(closes, self.config.ema_very_slow),
            'ema_800': self._ema(closes, 800), # Added for Trend Filter
        }
    
    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate Exponential Moving Average"""
        ema = np.zeros_like(data)
        ema[0] = data[0]
        multiplier = 2 / (period + 1)
        
        for i in range(1, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        
        return ema
    
    def _calculate_rsi(self, ohlcv: List[List], period: int = 14) -> np.ndarray:
        """Calculate RSI"""
        if not ohlcv:
            return np.array([])
            
        closes = pd.Series([c[4] for c in ohlcv])
        delta = closes.diff()
        
        # Make two series: gains (delta > 0) and losses (delta < 0)
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        
        # Calculate EWMA (Wilder's Smoothing)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.fillna(50).values  # Fill NaN with 50 (neutral)
    
    def _detect_w_formation(self, ohlcv: List[List], vectors: List[VectorType],
                           emas: Dict[str, np.ndarray], rsi: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Detect W Formation pattern.
        """
        if len(ohlcv) < 20 or len(vectors) < 20:
            return None
        
        # Look for Phase 1: 3+ consecutive red vector candles
        phase1_data = self._find_phase1_dump(ohlcv, vectors)
        if not phase1_data:
            return None
        
        # Look for Phase 2: Retracement
        phase2_data = self._find_phase2_retracement(
            ohlcv, phase1_data, 'W', emas
        )
        if not phase2_data:
            return None
        
        # Look for Phase 3: Sweep below Phase 1 low
        phase3_data = self._find_phase3_sweep(
            ohlcv, vectors, phase1_data, phase2_data, 'W', rsi
        )
        if not phase3_data:
            return None
        
        # Look for Phase 4: Confirmation (Breakout or Reclaim)
        phase4_data = self._find_phase4_confirmation(
            ohlcv, vectors, emas, 'W', phase1_data
        )
        if not phase4_data:
            return None
        
        return {
            'type': 'W',
            'phase1': phase1_data,
            'phase2': phase2_data,
            'phase3': phase3_data,
            'phase4': phase4_data,
            'emas': {k: v[-1] for k, v in emas.items()},
            'current_price': ohlcv[-1][4]
        }
    
    def _detect_m_formation(self, ohlcv: List[List], vectors: List[VectorType],
                           emas: Dict[str, np.ndarray], rsi: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Detect M Formation pattern.
        """
        if len(ohlcv) < 20 or len(vectors) < 20:
            return None
        
        # Look for Phase 1: 3+ consecutive green vector candles
        phase1_data = self._find_phase1_pump(ohlcv, vectors)
        if not phase1_data:
            return None
        
        # Look for Phase 2: Pullback
        phase2_data = self._find_phase2_retracement(
            ohlcv, phase1_data, 'M', emas
        )
        if not phase2_data:
            return None
        
        # Look for Phase 3: Sweep above Phase 1 high
        phase3_data = self._find_phase3_sweep(
            ohlcv, vectors, phase1_data, phase2_data, 'M', rsi
        )
        if not phase3_data:
            return None
        
        # Look for Phase 4: Confirmation (Breakdown or Reclaim)
        phase4_data = self._find_phase4_confirmation(
            ohlcv, vectors, emas, 'M', phase1_data
        )
        if not phase4_data:
            return None
        
        return {
            'type': 'M',
            'phase1': phase1_data,
            'phase2': phase2_data,
            'phase3': phase3_data,
            'phase4': phase4_data,
            'emas': {k: v[-1] for k, v in emas.items()},
            'current_price': ohlcv[-1][4]
        }
    
    def _find_phase1_dump(self, ohlcv: List[List], vectors: List[VectorType]) -> Optional[Dict[str, Any]]:
        """Find Phase 1: Aggressive dump with 3+ red vector candles"""
        for i in range(len(vectors) - 1, self.config.phase1_min_vector_candles - 1, -1):
            bearish_count = 0
            start_idx = i
            
            for j in range(i, max(0, i - 15), -1): # Look a bit further back
                if self.pvsra.is_bearish_vector(vectors[j]):
                    bearish_count += 1
                    start_idx = j
                else:
                    break
            
            if bearish_count >= self.config.phase1_min_vector_candles:
                low_idx = start_idx
                # Calculate High/Low of the sequence
                phase1_low = min([ohlcv[k][3] for k in range(start_idx, i + 1)])
                phase1_high = max([ohlcv[k][2] for k in range(start_idx, i + 1)])
                
                return {
                    'start_index': start_idx,
                    'end_index': i,
                    'low': phase1_low,
                    'high': phase1_high,
                    'low_index': low_idx,
                    'vector_count': bearish_count,
                    'vectors': [vectors[k].value for k in range(start_idx, i + 1)]
                }
        
        return None
    
    def _find_phase1_pump(self, ohlcv: List[List], vectors: List[VectorType]) -> Optional[Dict[str, Any]]:
        """Find Phase 1: Aggressive pump with 3+ green vector candles"""
        for i in range(len(vectors) - 1, self.config.phase1_min_vector_candles - 1, -1):
            bullish_count = 0
            start_idx = i
            
            for j in range(i, max(0, i - 15), -1):
                if self.pvsra.is_bullish_vector(vectors[j]):
                    bullish_count += 1
                    start_idx = j
                else:
                    break
            
            if bullish_count >= self.config.phase1_min_vector_candles:
                high_idx = start_idx
                phase1_high = max([ohlcv[k][2] for k in range(start_idx, i + 1)])
                phase1_low = min([ohlcv[k][3] for k in range(start_idx, i + 1)])
                
                return {
                    'start_index': start_idx,
                    'end_index': i,
                    'high': phase1_high,
                    'low': phase1_low,
                    'high_index': high_idx,
                    'vector_count': bullish_count,
                    'vectors': [vectors[k].value for k in range(start_idx, i + 1)]
                }
        
        return None
    
    def _find_phase2_retracement(self, ohlcv: List[List], phase1: Dict[str, Any],
                                formation_type: str, emas: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
        """Find Phase 2: Retracement"""
        start_idx = phase1['end_index'] + 1
        
        if start_idx >= len(ohlcv):
            return None
        
        if formation_type == 'W':
            phase1_low = phase1['low']
            phase1_high = phase1['high']
            impulse_height = phase1_high - phase1_low
            
            if impulse_height == 0: return None
            
            for i in range(start_idx, min(start_idx + 12, len(ohlcv))):
                high = ohlcv[i][2]
                retracement_height = high - phase1_low
                retracement_ratio = retracement_height / impulse_height
                
                if self.config.phase2_retracement_min <= retracement_ratio <= self.config.phase2_retracement_max:
                    return {
                        'index': i,
                        'high': high,
                        'retracement_pct': retracement_ratio * 100
                    }
        else:  # M Formation
            phase1_high = phase1['high']
            phase1_low = phase1['low']
            impulse_height = phase1_high - phase1_low
            
            if impulse_height == 0: return None
            
            for i in range(start_idx, min(start_idx + 12, len(ohlcv))):
                low = ohlcv[i][3]
                pullback_height = phase1_high - low
                pullback_ratio = pullback_height / impulse_height
                
                if self.config.phase2_retracement_min <= pullback_ratio <= self.config.phase2_retracement_max:
                    return {
                        'index': i,
                        'low': low,
                        'retracement_pct': pullback_ratio * 100
                    }
        
        return None
    
    def _find_phase3_sweep(self, ohlcv: List[List], vectors: List[VectorType],
                          phase1: Dict[str, Any], phase2: Dict[str, Any],
                          formation_type: str, rsi: np.ndarray) -> Optional[Dict[str, Any]]:
        """Find Phase 3: Liquidity sweep"""
        start_idx = phase2['index'] + 1
        
        if start_idx >= len(ohlcv):
            return None
        
        if formation_type == 'W':
            phase1_low = phase1['low']
            sweep_threshold = phase1_low * (1 - self.config.phase3_sweep_buffer)
            
            for i in range(start_idx, min(start_idx + 8, len(ohlcv))):
                candle_low = ohlcv[i][3]
                candle_close = ohlcv[i][4]
                
                # Check for sweep
                if candle_low < sweep_threshold:
                    # In Reclaim mode, we don't care about the close HERE, we check it in Phase 4
                    # But we do want to avoid massive crashes, so RSI check helps
                    
                    if rsi[i] < 65: # Loose check, just not extremely overbought
                        return {
                            'index': i,
                            'sweep_low': candle_low,
                            'body_close': candle_close,
                            'sweep_amount': phase1_low - candle_low,
                            'rsi': rsi[i]
                        }
        
        else:  # M Formation
            phase1_high = phase1['high']
            sweep_threshold = phase1_high * (1 + self.config.phase3_sweep_buffer)
            
            for i in range(start_idx, min(start_idx + 8, len(ohlcv))):
                candle_high = ohlcv[i][2]
                candle_close = ohlcv[i][4]
                
                if candle_high > sweep_threshold:
                    if rsi[i] > 35: # Loose check
                        return {
                            'index': i,
                            'sweep_high': candle_high,
                            'body_close': candle_close,
                            'sweep_amount': candle_high - phase1_high,
                            'rsi': rsi[i]
                        }
        
        return None
    
    def _find_phase4_confirmation(self, ohlcv: List[List], vectors: List[VectorType],
                              emas: Dict[str, np.ndarray], formation_type: str, phase1: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find Phase 4: Breakout or Reclaim confirmation"""
        
        # Check from the latest candle back a few bars
        # We need the confirmation to be recent (e.g., current bar or last bar)
        
        # In scanning live, usually we care about the LAST COMPLETED candle
        # So we look at index -1
        i = len(ohlcv) - 1
        
        if self.config.entry_mode == 'reclaim':
            if formation_type == 'W':
                # Reclaim Phase 1 Low
                if ohlcv[i][4] > phase1['low']:
                    # REQUIREMENT: Must be a Bullish Vector Candle to confirm strength
                    # Or at least have decent volume? Let's strictly check for Bullish Vector.
                    if i < len(vectors) and self.pvsra.is_bullish_vector(vectors[i]):
                        return {
                            'index': i,
                            'price': ohlcv[i][4],
                            'type': 'reclaim',
                            'vector': vectors[i].value
                        }
            else:
                # Reclaim Phase 1 High
                if ohlcv[i][4] < phase1['high']:
                    # REQUIREMENT: Must be a Bearish Vector Candle
                    if i < len(vectors) and self.pvsra.is_bearish_vector(vectors[i]):
                        return {
                            'index': i,
                            'price': ohlcv[i][4],
                            'type': 'reclaim',
                            'vector': vectors[i].value
                        }
                    
        else: # Breakout Mode
            if formation_type == 'W':
                if i < len(vectors) and self.pvsra.is_bullish_vector(vectors[i]):
                     if ohlcv[i][4] > emas['ema_50'][i]:
                        return {
                            'index': i,
                            'price': ohlcv[i][4],
                            'type': 'breakout',
                            'vector': vectors[i].value
                        }
            else:
                 if i < len(vectors) and self.pvsra.is_bearish_vector(vectors[i]):
                    if ohlcv[i][4] < emas['ema_50'][i]:
                        return {
                            'index': i,
                            'price': ohlcv[i][4],
                            'type': 'breakout',
                            'vector': vectors[i].value
                        }
        
        return None
    
    def _confirm_formation(self, formation: Dict[str, Any], ohlcv: List[List], formation_type: str) -> Optional[Dict[str, Any]]:
        """
        Confirm formation and create signal.
        """
        # For Reclaim mode, the primary signal IS the confirmation.
        # We can add extra checks here if needed (volume, lower TF).
        
        return self._create_signal(formation, formation_type)

    def _create_signal(self, formation: Dict[str, Any], formation_type: str) -> Optional[Dict[str, Any]]:
        """
        Create trading signal from formation data.
        """
        current_price = formation['current_price']
        
        if formation_type == 'W':
            direction = 'buy'
            
            # SL: Below sweep low
            sweep_low = formation['phase3']['sweep_low']
            stop_loss = sweep_low * (1 - self.config.stop_loss_buffer_pct)
            
            # Target Logic
            # Target 1: Phase 2 High (Retracement High) - highly probable
            # Target 2: Previous structure / Phase 1 High
            target_conservative = formation['phase2']['high']
            target_aggressive = formation['phase1']['high']
            
            risk = current_price - stop_loss
            
            # If Risk is 0 or negative (error), abort
            if risk <= 0: return None

            # Calculate potential reward to conservative target
            reward_conservative = target_conservative - current_price
            
            if (reward_conservative / risk) > 1.5:
                take_profit = target_conservative
            else:
                # If conservative target is too close, aim higher
                take_profit = target_aggressive

            # Ensure Stop Loss isn't too tight (Min Dist)
            min_dist = current_price * self.config.min_stop_loss_dist_pct
            if (current_price - stop_loss) < min_dist:
                stop_loss = current_price - min_dist
                
        else:  # M Formation
            direction = 'sell'
            
            # SL: Above sweep high
            sweep_high = formation['phase3']['sweep_high']
            stop_loss = sweep_high * (1 + self.config.stop_loss_buffer_pct)
            
            target_conservative = formation['phase2']['low']
            target_aggressive = formation['phase1']['low']
            
            risk = stop_loss - current_price
            if risk <= 0: return None
            
            reward_conservative = current_price - target_conservative
            
            if (reward_conservative / risk) > 1.5:
                take_profit = target_conservative
            else:
                take_profit = target_aggressive

            min_dist = current_price * self.config.min_stop_loss_dist_pct
            if (stop_loss - current_price) < min_dist:
                stop_loss = current_price + min_dist
        
        # Log formation
        phase_data = {
            'phase1_vectors': formation['phase1']['vectors'],
            'phase1_extreme': formation['phase1'].get('low' if formation_type == 'W' else 'high'),
            'phase3_sweep': formation['phase3'].get('sweep_low' if formation_type == 'W' else 'sweep_high'),
            'type': formation['phase4']['type']
        }
        
        self.position_logger.log_formation_detected(
            timestamp=datetime.now(),
            formation_type=formation_type,
            phase_data=phase_data,
            instrument=self.config.deribit_symbol
        )
        
        # Calculate Position Size
        # Calculate Position Size via Risk Manager
        # Try to get risk manager
        if hasattr(self, 'risk_manager') and self.risk_manager:
            risk_pct = self.config.risk_per_trade_pct
            
            sizing = self.risk_manager.calculate_futures_quantity(
                entry_price=current_price,
                sl_price=stop_loss,
                risk_pct=risk_pct,
                leverage_max=getattr(self.config, 'max_leverage', 5)
            )
            
            if "error" in sizing:
                logger.error(f"Sizing error: {sizing['error']}")
                return None
                
            qty_btc = sizing['quantity_btc']
            
            # Convert to Contracts (Inverse) or keep as coins (Linear)
            symbol = self.config.deribit_symbol
            is_inverse = "PERPETUAL" in symbol and "USDC" not in symbol
            
            if is_inverse:
                if "BTC" in symbol: contract_val = 10.0 
                else: contract_val = 1.0
                qty_usd_raw = qty_btc * current_price
                steps = int(qty_usd_raw / contract_val)
                position_size = steps * int(contract_val)
            else:
                position_size = round(qty_btc, 4)
                
            # Determine tick size
            tick_size = 0.5 if "BTC" in self.config.deribit_symbol else 0.05
            
            # Round SL to tick size
            stop_loss = round(stop_loss / tick_size) * tick_size
            
            logger.info(f"Sizing {symbol}: Eq=${sizing['equity']:,.2f} Size={position_size}")
            
        else:
            # Fallback (Should not happen in correct setup)
            logger.warning("RiskManager missing in WMFormation, using default safe size")
            position_size = 100.0
        
        return {
            'type': 'wm_formation',
            'formation_type': formation_type,
            'direction': direction,
            'instrument': self.config.deribit_symbol,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'position_size': position_size,
            'reason': f"{formation_type} Formation ({self.config.entry_mode})"
        }
    
    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        """Execute entry based on signal"""
        try:
            logger.info(f"Executing {signal['formation_type']} Formation {signal['direction']} on {signal['instrument']}")
            
            order_manager = self.dependencies.get('order_manager')
            if not order_manager:
                logger.error("OrderManager not found in dependencies")
                self.position_logger.log_error(datetime.now(), "Execution Error: OrderManager missing")
                return False
                
            success, message = order_manager.execute_generic_trade(
                instrument_name=signal['instrument'],
                direction=signal['direction'],
                quantity=signal['position_size'],
                entry_type="market",
                stop_loss=signal.get('stop_loss'),
                take_profit=signal.get('take_profit'),
                label="wm_entry"  # Unique label for identification
            )
            
            self.position_logger.log_execution_result(
                timestamp=datetime.now(),
                success=success, 
                instrument=signal['instrument'],
                details=f"Direction: {signal['direction']}, Size: {signal['position_size']}, Entry: market, Result: {message}"
            )
            
            return success
        except Exception as e:
            logger.error(f"Error executing W/M Strategy entry: {e}")
            self.position_logger.log_error(datetime.now(), f"Execution Error: {str(e)}")
            return False

    def manage_positions(self) -> Dict[str, Any]:
        """Manage active positions"""
        return {}
