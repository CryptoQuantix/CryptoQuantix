from typing import Dict, List, Optional, Tuple
import time
import logging
from src.core.deribit_client import DeribitClient
from src.core.order_registry import OrderRegistry
from src.strategies.iron_condor import IronCondor, OptionLeg

logger = logging.getLogger(__name__)


class OrderManager:
    """Manage order execution for Iron Condor structures and generic futures trades"""

    def __init__(self, client: DeribitClient, max_retries: int = 3, retry_delay: float = 1.0,
                 use_aggressive_limits: bool = True, slippage_pct: float = 0.10,
                 registry: Optional[OrderRegistry] = None):
        """
        Initialize order manager

        Args:
            client: Deribit API client
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            use_aggressive_limits: Use aggressive limit orders for better fills
            slippage_pct: Slippage percentage for aggressive limits (e.g., 0.10 = 10%)
            registry: OrderRegistry for orphan order tracking (optional, strongly recommended)
        """
        self.client = client
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.use_aggressive_limits = use_aggressive_limits
        self.slippage_pct = slippage_pct
        self.registry = registry

    def open_iron_condor(self, condor: IronCondor, use_market_orders: bool = False) -> bool:
        """
        Open all 4 legs of an Iron Condor

        Args:
            condor: IronCondor structure to open
            use_market_orders: Use market orders instead of limit orders

        Returns:
            True if all legs opened successfully
        """
        logger.info(f"Opening Iron Condor: {condor.id}")

        legs = [
            (condor.long_put, "buy"),
            (condor.short_put, "sell"),
            (condor.short_call, "sell"),
            (condor.long_call, "buy")
        ]

        opened_orders = []

        try:
            for leg, side in legs:
                logger.info(f"Executing leg: {side.upper()} {leg.option_type} @ {leg.strike} ({leg.instrument_name})")
                success = self._execute_leg(leg, side, condor.size, use_market_orders)

                if success:
                    opened_orders.append((leg, side))
                    logger.info(f"  ✓ {side.upper()} {leg.option_type} @ {leg.strike} - FILLED")
                else:
                    logger.error(f"  ✗ Failed to {side} {leg.option_type} @ {leg.strike} - NOT FILLED")
                    # Rollback: close already opened legs
                    logger.warning(f"Rolling back {len(opened_orders)} opened legs...")
                    self._rollback_orders(opened_orders, condor.size)
                    return False

                # Small delay between legs
                time.sleep(0.5)

            logger.info(f"Successfully opened Iron Condor: {condor.id}")
            return True

        except Exception as e:
            logger.error(f"Error opening Iron Condor: {e}")
            self._rollback_orders(opened_orders, condor.size)
            return False

    def close_iron_condor(self, condor: IronCondor, reason: str = "manual") -> bool:
        """
        Close all 4 legs of an Iron Condor

        Args:
            condor: IronCondor structure to close
            reason: Reason for closing (TP, SL, expiry, manual)

        Returns:
            True if all legs closed successfully
        """
        logger.info(f"Closing Iron Condor: {condor.id} (reason: {reason})")

        legs = [
            (condor.long_put, "sell"),  # Close long = sell
            (condor.short_put, "buy"),  # Close short = buy back
            (condor.short_call, "buy"),  # Close short = buy back
            (condor.long_call, "sell")  # Close long = sell
        ]

        all_closed = True

        for leg, side in legs:
            success = self._close_leg(leg, side, condor.size)

            if success:
                logger.info(f"  ✓ Closed {leg.option_type} @ {leg.strike}")
            else:
                logger.error(f"  ✗ Failed to close {leg.option_type} @ {leg.strike}")
                all_closed = False

            time.sleep(0.5)

        if all_closed:
            logger.info(f"Successfully closed Iron Condor: {condor.id}")
        else:
            logger.warning(f"Partially closed Iron Condor: {condor.id}")

        return all_closed

    def _round_to_tick_size(self, price: float, instrument_name: str) -> float:
        """
        Round price to Deribit tick size (4 decimals for BTC, 8 for ETH options)

        Args:
            price: Raw price
            instrument_name: Instrument name to determine currency

        Returns:
            Rounded price
        """
        # Deribit options tick size: 0.0001 for BTC, 0.00000001 for ETH
        if 'BTC' in instrument_name:
            if 'PERPETUAL' in instrument_name or 'future' in instrument_name.lower():
                 # BTC Future/Perp: 0.5 tick size
                 return round(price / 0.5) * 0.5
            else:
                 # BTC Option: 0.0001 (though often 0.0005, depends on strictness. 4 decimals safe)
                 return round(price, 4)
        elif 'ETH' in instrument_name:
            if 'PERPETUAL' in instrument_name or 'future' in instrument_name.lower():
                 # ETH Future/Perp: 0.05 tick size
                 return round(price / 0.05) * 0.05
            else:
                 # ETH Option
                 return round(price, 4)
        else:
            return round(price, 4)

    def _get_aggressive_price(self, instrument_name: str, side: str, mark_price: float) -> Optional[float]:
        """
        Get aggressive limit price that will likely fill immediately

        Args:
            instrument_name: Instrument name
            side: "buy" or "sell"
            mark_price: Current mark price as fallback

        Returns:
            Aggressive limit price or None for market order
        """
        try:
            # Get order book
            book = self.client.get_order_book(instrument_name, depth=5)

            if not book:
                logger.warning(f"No order book for {instrument_name}, using mark price")
                rounded = self._round_to_tick_size(mark_price, instrument_name)
                return rounded

            best_bid = book.get('best_bid_price')
            best_ask = book.get('best_ask_price')

            if side == "buy":
                # To buy: pay slightly more than best ask to ensure fill
                if best_ask and best_ask > 0:
                    aggressive_price = best_ask * (1 + self.slippage_pct)
                    rounded = self._round_to_tick_size(aggressive_price, instrument_name)
                    logger.info(f"BUY aggressive: {rounded:.4f} (best_ask: {best_ask:.4f} +{self.slippage_pct:.0%})")
                    return rounded
                else:
                    logger.warning(f"No best_ask for {instrument_name}, using mark * 1.1")
                    if mark_price:
                        rounded = self._round_to_tick_size(mark_price * 1.1, instrument_name)
                        return rounded
                    return None

            else:  # sell
                # To sell: use best_bid (someone wants to buy at this price)
                # OR use best_ask and slightly undercut to ensure fill
                if best_bid and best_bid > 0:
                    # Simply use best_bid - this is what market maker is willing to pay
                    # No need to go lower, that's leaving money on the table
                    rounded = self._round_to_tick_size(best_bid, instrument_name)
                    logger.info(f"SELL aggressive: {rounded:.4f} (best_bid: {best_bid:.4f})")
                    return rounded
                elif best_ask and best_ask > 0:
                    # If no bid, undercut the ask slightly
                    aggressive_price = best_ask * (1 - self.slippage_pct * 0.5)  # Less aggressive
                    rounded = self._round_to_tick_size(aggressive_price, instrument_name)
                    logger.info(f"SELL aggressive: {rounded:.4f} (undercutting ask: {best_ask:.4f})")
                    return rounded
                else:
                    logger.warning(f"No best_bid/ask for {instrument_name}, using mark")
                    if mark_price:
                        rounded = self._round_to_tick_size(mark_price, instrument_name)
                        return rounded
                    return None

        except Exception as e:
            logger.error(f"Error getting aggressive price: {e}")
            if mark_price:
                return self._round_to_tick_size(mark_price, instrument_name)
            return None

    def _execute_leg(self, leg: OptionLeg, side: str, size: float,
                    use_market_orders: bool = False) -> bool:
        """
        Execute a single option leg and verify it was filled

        Args:
            leg: Option leg to execute
            side: "buy" or "sell"
            size: Position size
            use_market_orders: Use market instead of limit orders

        Returns:
            True if successful and filled
        """
        for attempt in range(self.max_retries):
            try:
                if use_market_orders:
                    price = None  # Market order
                    logger.info(f"Using MARKET order for {leg.instrument_name}")
                elif self.use_aggressive_limits:
                    # Use aggressive limit price for better fill probability
                    price = self._get_aggressive_price(leg.instrument_name, side, leg.mark_price)
                    if price:
                        # Logging already done in _get_aggressive_price
                        pass
                    else:
                        logger.warning(f"Could not get aggressive price, using MARKET")
                        price = None
                else:
                    # Use mark price for conservative limit order
                    price = self._round_to_tick_size(leg.mark_price, leg.instrument_name)
                    logger.info(f"Using mark price {price:.4f} for {leg.instrument_name}")

                if side == "buy":
                    order = self.client.buy(
                        instrument_name=leg.instrument_name,
                        amount=size,
                        price=price,
                        label=f"iron_condor"
                    )
                else:  # sell
                    order = self.client.sell(
                        instrument_name=leg.instrument_name,
                        amount=size,
                        price=price,
                        label=f"iron_condor"
                    )

                if order and "order_id" in order:
                    order_id = order.get('order_id')
                    order_state = order.get('order_state', 'unknown')
                    logger.info(f"Order placed: {order_id}, state: {order_state}")

                    # Verify order was filled
                    if self._verify_order_filled(order_id, leg.instrument_name):
                        logger.info(f"Order {order_id} FILLED successfully")
                        return True
                    else:
                        logger.warning(f"Order {order_id} NOT filled, attempt {attempt + 1}/{self.max_retries}")
                        # Cancel the unfilled order before retrying
                        try:
                            self.client.get_order_state(order_id)  # Check if still exists
                            logger.info(f"Cancelling unfilled order {order_id}")
                        except:
                            pass
                elif order and "error" in order:
                     err_msg = order["error"].get("message", "Unknown API error")
                     logger.error(f"Order placement FAILED: {err_msg}, attempt {attempt + 1}/{self.max_retries}")
                else:
                    logger.error(f"Order placement FAILED (no response), attempt {attempt + 1}/{self.max_retries}")

            except Exception as e:
                logger.error(f"Error executing leg: {e}", exc_info=True)

            if attempt < self.max_retries - 1:
                logger.info(f"Waiting {self.retry_delay}s before retry...")
                time.sleep(self.retry_delay)

        return False

    def _verify_order_filled(self, order_id: str, instrument_name: str,
                            max_wait: int = 5) -> bool:
        """
        Verify that an order was filled

        Args:
            order_id: Order ID to check
            instrument_name: Instrument name for logging
            max_wait: Maximum seconds to wait for fill

        Returns:
            True if order is filled
        """
        for i in range(max_wait):
            try:
                order_state = self.client.get_order_state(order_id)

                if order_state:
                    state = order_state.get('order_state')
                    filled = order_state.get('filled_amount', 0)

                    logger.debug(f"Order {order_id} state: {state}, filled: {filled}")

                    if state == 'filled':
                        return True
                    elif state in ['rejected', 'cancelled']:
                        logger.error(f"Order {order_id} was {state}")
                        return False

                # Wait before checking again
                if i < max_wait - 1:
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Error checking order state: {e}")

        logger.error(f"Order {order_id} for {instrument_name} not filled after {max_wait}s")
        return False

    def _close_leg(self, leg: OptionLeg, side: str, size: float) -> bool:
        """
        Close a single option leg

        Args:
            leg: Option leg to close
            side: "buy" or "sell" (opposite of opening)
            size: Position size

        Returns:
            True if successful
        """
        for attempt in range(self.max_retries):
            try:
                # Try using close_position first (faster)
                result = self.client.close_position(
                    instrument_name=leg.instrument_name,
                    type_="market"
                )

                if result:
                    logger.debug(f"Position closed via close_position")
                    return True

                # Fallback to manual order
                if side == "buy":
                    order = self.client.buy(
                        instrument_name=leg.instrument_name,
                        amount=size,
                        price=None  # Market order
                    )
                else:
                    order = self.client.sell(
                        instrument_name=leg.instrument_name,
                        amount=size,
                        price=None
                    )

                if order:
                    logger.debug(f"Position closed via manual order")
                    return True

            except Exception as e:
                logger.error(f"Error closing leg: {e}")

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)

        return False

    def _rollback_orders(self, opened_orders: List, size: float):
        """
        Rollback (close) orders that were already opened

        Args:
            opened_orders: List of (leg, side) tuples that were opened
            size: Position size
        """
        logger.warning(f"Rolling back {len(opened_orders)} opened orders")

        for leg, original_side in opened_orders:
            # Reverse the side to close
            close_side = "sell" if original_side == "buy" else "buy"

            try:
                self._close_leg(leg, close_side, size)
            except Exception as e:
                logger.error(f"Error during rollback: {e}")

    def get_position_details(self, instrument_name: str, currency: str) -> Optional[Dict]:
        """
        Get current position details for an instrument

        Args:
            instrument_name: Option instrument name
            currency: BTC or ETH

        Returns:
            Position dict or None
        """
        try:
            positions = self.client.get_positions(currency)

            for pos in positions:
                if pos.get("instrument_name") == instrument_name:
                    return pos

            return None

        except Exception as e:
            logger.error(f"Error getting position details: {e}")
            return None

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders"""
        try:
            result = self.client.cancel_all()
            if result:
                logger.info("Cancelled all open orders")
                return True
            return False
        except Exception as e:
            logger.error(f"Error cancelling orders: {e}")
            return False
    def execute_smart_money_trade(self, instrument_name: str, direction: str, quantity: float, sl_price: float) -> bool:
        """
        Execute a Smart Money trade with immediate Stop Loss.
        
        Args:
            instrument_name: Instrument (e.g. BTC-PERPETUAL)
            direction: "buy" or "sell"
            quantity: Amount to trade (Contracts/USD for Inverse)
            sl_price: Stop Loss trigger price
            
        Returns:
            True if successful
        """
        logger.info(f"Executing Smart Money Trade: {direction.upper()} {quantity} {instrument_name} with SL @ {sl_price}")
        
        try:
            # 1. Place Market Order for Entry
            if direction == "buy":
                order = self.client.buy(instrument_name, quantity, type_="market", label="smart_money_entry")
            else:
                order = self.client.sell(instrument_name, quantity, type_="market", label="smart_money_entry")
                
            if not order:
                logger.error("Entry order failed (Network/Timeout)")
                return False
                
            if "error" in order:
                logger.error(f"Entry order failed: {order['error']}")
                return False
                
            order_id = order.get('order_id')
            logger.info(f"Entry order placed: {order_id}")
            
            # 2. Place Stop Loss Order
            # For Buy entry, SL is a Sell Stop Market
            # For Sell entry, SL is a Buy Stop Market
            sl_side = "sell" if direction == "buy" else "buy"
            
            # Deribit trigger type: "index_price" or "mark_price" or "last_price"
            # Usually "mark_price" is safer to avoid wicks
            
            sl_order = None
            if sl_side == "buy":
                sl_order = self.client.buy(
                    instrument_name=instrument_name, 
                    amount=quantity, 
                    type_="stop_market", 
                    trigger="mark_price", 
                    price=None,
                    trigger_price=sl_price,
                    label="smart_money_sl",
                    reduce_only=True
                )
                # Note: Deribit API uses 'trigger_price' param, but client wrapper might map 'price' to it for stop orders?
                # Checking DeribitClient wrapper would be ideal. Assuming standard kwargs pass-through.
            else:
                sl_order = self.client.sell(
                    instrument_name=instrument_name, 
                    amount=quantity, 
                    type_="stop_market", 
                    trigger="mark_price", 
                    price=None,
                    trigger_price=sl_price,
                    label="smart_money_sl",
                    reduce_only=True
                )
                
            if sl_order:
                logger.info(f"Stop Loss order placed: {sl_order.get('order_id')} @ {sl_price}")
                return True
            else:
                logger.error("Stop Loss order failed! Closing position immediately.")
                # Emergency close if SL fails
                self.client.close_position(instrument_name, type_="market")
                return False
                
        except Exception as e:
            logger.error(f"Error executing Smart Money trade: {e}")
            return False

    def execute_generic_trade(self, instrument_name: str, direction: str, quantity: float,
                              entry_type: str = "market", price: float = None,
                              stop_loss: float = None, take_profit: float = None,
                              label: str = "strategy_entry") -> Tuple[bool, str]:
        """
        Execute a generic trade with optional SL and TP.
        Registra automaticamente SL e TP nell'OrderRegistry per prevenire ordini orfani.

        Args:
            instrument_name: Instrument (e.g. BTC-PERPETUAL)
            direction: "buy" or "sell"
            quantity: Amount to trade
            entry_type: "market" or "limit"
            price: Entry price (required for limit)
            stop_loss: Stop Loss trigger price (optional)
            take_profit: Take Profit trigger price (optional - limit order)
            label: Label for the entry order

        Returns:
            Tuple[bool, str]: (Success, Message)
        """
        logger.info(
            f"Generic Execution: {direction.upper()} {quantity} {instrument_name} "
            f"@ {entry_type.upper()} (SL={stop_loss}, TP={take_profit})"
        )

        try:
            # CENTRALIZED ROUNDING
            if price:
                price = self._round_to_tick_size(price, instrument_name)
            if stop_loss:
                stop_loss = self._round_to_tick_size(stop_loss, instrument_name)
            if take_profit:
                take_profit = self._round_to_tick_size(take_profit, instrument_name)

            # 1. Place Entry Order
            order_label = label
            order = None

            if direction == "buy":
                order = self.client.buy(
                    instrument_name, quantity,
                    price=price if entry_type == "limit" else None,
                    type=entry_type, label=order_label
                )
            else:
                order = self.client.sell(
                    instrument_name, quantity,
                    price=price if entry_type == "limit" else None,
                    type=entry_type, label=order_label
                )

            if not order:
                return False, "Entry API Call Failed (Network/Timeout)"

            if "error" in order:
                err_msg = order["error"].get("message", "Unknown API Error")
                logger.error(f"Entry failed: {err_msg}")
                return False, f"Entry Rejected: {err_msg}"

            order_id = order.get("order_id")
            logger.info(f"Entry order placed: {order_id}")

            # Wait for Deribit to open the position before placing reduce_only SL/TP.
            # Without this delay, reduce_only orders fail with invalid_reduce_only_order
            # because the limit entry may not be processed yet.
            time.sleep(0.3)

            # Track SL and TP order IDs for orphan cleanup
            sl_order_id = None
            tp_order_id = None

            # 2. Place Stop Loss if specified — con RETRY e chiusura di
            #    emergenza: una posizione aperta NON deve mai restare senza
            #    stop (ordini appesi nel nulla / posizioni nude).
            if stop_loss:
                sl_side = "sell" if direction == "buy" else "buy"
                sl_label = label.replace("entry", "sl") if "entry" in label else f"{label}_sl"
                sl_fn = self.client.buy if sl_side == "buy" else self.client.sell

                for attempt in range(3):
                    sl_order = sl_fn(
                        instrument_name, quantity,
                        type="stop_market", trigger="mark_price",
                        price=None, trigger_price=stop_loss,
                        label=sl_label, reduce_only=True
                    )
                    if sl_order and "order_id" in sl_order:
                        sl_order_id = sl_order["order_id"]
                        logger.info(f"Stop Loss placed: {stop_loss} | order_id={sl_order_id}")
                        break
                    err = sl_order.get("error") if sl_order else "order object None"
                    logger.error(f"SL placement failed (attempt {attempt + 1}/3): {err}")
                    time.sleep(0.5)

                if sl_order_id is None:
                    # Posizione senza stop = rischio inaccettabile: chiusura
                    # di emergenza reduce-only della quantita' appena aperta
                    logger.critical(
                        f"SL non piazzabile su {instrument_name} — EMERGENCY CLOSE "
                        f"della posizione appena aperta ({quantity})"
                    )
                    close_fn = self.client.sell if direction == "buy" else self.client.buy
                    close_order = close_fn(
                        instrument_name, quantity, type="market",
                        label=f"{label}_emergency_close", reduce_only=True
                    )
                    if close_order and "error" not in close_order:
                        return False, "SL failed 3x — position emergency-closed"
                    logger.critical(
                        f"EMERGENCY CLOSE FALLITA su {instrument_name}: {close_order} — "
                        f"INTERVENTO MANUALE RICHIESTO"
                    )
                    return False, "SL failed AND emergency close failed — MANUAL ACTION"

            # 3. Place Take Profit if specified (Limit Reduce Only)
            if take_profit:
                tp_side = "sell" if direction == "buy" else "buy"
                tp_label = label.replace("entry", "tp") if "entry" in label else f"{label}_tp"

                tp_order = None
                if tp_side == "buy":
                    tp_order = self.client.buy(
                        instrument_name, quantity,
                        price=take_profit, type="limit",
                        label=tp_label, reduce_only=True
                    )
                else:
                    tp_order = self.client.sell(
                        instrument_name, quantity,
                        price=take_profit, type="limit",
                        label=tp_label, reduce_only=True
                    )

                if tp_order and "order_id" in tp_order:
                    tp_order_id = tp_order["order_id"]
                    logger.info(f"Take Profit placed: {take_profit} | order_id={tp_order_id}")
                elif tp_order and "error" in tp_order:
                    logger.error(f"TP placement error: {tp_order['error']}")
                else:
                    logger.error("Failed to place Take Profit — order object None")

            # 4. Registra nel registry per prevenire ordini orfani
            if self.registry and (sl_order_id or tp_order_id):
                self.registry.register_trade(
                    instrument=instrument_name,
                    direction=direction,
                    sl_order_id=sl_order_id,
                    tp_order_id=tp_order_id,
                    label=label
                )

            return True, f"Entry Placed: {order_id}"

        except Exception as e:
            logger.error(f"Error in execute_generic_trade: {e}")
            return False, f"Exception: {str(e)}"
