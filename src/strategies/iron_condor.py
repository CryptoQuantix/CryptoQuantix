from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import logging
import time
from dataclasses import dataclass

from src.strategies.base_strategy import BaseStrategy
from src.utils.volatility import VolatilityAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class OptionLeg:
    """Represents a single option leg in the condor"""
    instrument_name: str
    strike: float
    option_type: str  # "call" or "put"
    direction: str  # "buy" or "sell"
    delta: float
    mark_price: float
    mark_iv: float


@dataclass
class IronCondor:
    """Represents a complete Iron Condor structure"""
    id: str
    currency: str
    expiration_date: str
    spot_price: float
    entry_time: datetime

    # Put spread (lower)
    long_put: OptionLeg
    short_put: OptionLeg

    # Call spread (upper)
    short_call: OptionLeg
    long_call: OptionLeg

    # Financial details
    credit_received: float
    max_loss: float
    max_profit: float
    size: float  # Position size multiplier

    # Risk parameters
    take_profit_target: float
    stop_loss_target: float

    # Status
    status: str = "open"  # open, closed, expired
    close_time: Optional[datetime] = None
    close_reason: Optional[str] = None
    realized_pnl: Optional[float] = None


class IronCondorBuilder:
    """Build Iron Condor structures from options chain"""

    def __init__(self, short_delta_target: float = 0.12, wing_width_percent: float = 0.05):
        self.short_delta_target = short_delta_target
        self.wing_width_percent = wing_width_percent

    def find_strike_by_delta(self, options: List[Dict], target_delta: float,
                            option_type: str, tolerance: float = 0.05) -> Optional[Dict]:
        target_delta = abs(target_delta)
        candidates = []

        for opt in options:
            if opt.get("option_type") != option_type:
                continue

            delta = opt.get("greeks", {}).get("delta")
            if delta is None:
                continue

            delta = abs(delta)
            delta_diff = abs(delta - target_delta)

            if delta_diff <= tolerance:
                candidates.append({
                    "option": opt,
                    "delta": delta,
                    "delta_diff": delta_diff
                })

        if not candidates:
            # logger.warning(f"No {option_type} found with delta ~{target_delta}")
            return None

        candidates.sort(key=lambda x: x["delta_diff"])
        return candidates[0]["option"]

    def find_protective_strike(self, options: List[Dict], short_strike: float,
                              option_type: str, spot_price: float,
                              direction: str = "farther") -> Optional[Dict]:
        wing_distance = spot_price * self.wing_width_percent

        if option_type == "put":
            target_strike = short_strike - wing_distance
            candidates = [
                opt for opt in options
                if opt.get("option_type") == "put"
                and opt.get("strike", 0) < short_strike
                and opt.get("strike", 0) <= target_strike
            ]
        else:  # call
            target_strike = short_strike + wing_distance
            candidates = [
                opt for opt in options
                if opt.get("option_type") == "call"
                and opt.get("strike", 0) > short_strike
                and opt.get("strike", 0) >= target_strike
            ]

        if not candidates:
            # logger.warning(f"No protective {option_type} found for strike {short_strike}")
            return None

        candidates.sort(key=lambda x: abs(x["strike"] - target_strike))
        return candidates[0]

    def build_condor(self, currency: str, options_chain: List[Dict],
                    spot_price: float, expiration_date: str,
                    risk_per_condor: float, tp_ratio: float = 0.55,
                    sl_mult: float = 1.2) -> Optional[IronCondor]:
        try:
            short_put_opt = self.find_strike_by_delta(
                options_chain, -self.short_delta_target, "put"
            )
            if not short_put_opt: return None

            short_call_opt = self.find_strike_by_delta(
                options_chain, self.short_delta_target, "call"
            )
            if not short_call_opt: return None

            long_put_opt = self.find_protective_strike(
                options_chain, short_put_opt["strike"], "put", spot_price
            )
            if not long_put_opt: return None

            long_call_opt = self.find_protective_strike(
                options_chain, short_call_opt["strike"], "call", spot_price
            )
            if not long_call_opt: return None

            short_put = OptionLeg(
                instrument_name=short_put_opt["instrument_name"],
                strike=short_put_opt["strike"],
                option_type="put",
                direction="sell",
                delta=short_put_opt["greeks"]["delta"],
                mark_price=short_put_opt["mark_price"],
                mark_iv=short_put_opt.get("mark_iv", 0)
            )

            long_put = OptionLeg(
                instrument_name=long_put_opt["instrument_name"],
                strike=long_put_opt["strike"],
                option_type="put",
                direction="buy",
                delta=long_put_opt["greeks"]["delta"],
                mark_price=long_put_opt["mark_price"],
                mark_iv=long_put_opt.get("mark_iv", 0)
            )

            short_call = OptionLeg(
                instrument_name=short_call_opt["instrument_name"],
                strike=short_call_opt["strike"],
                option_type="call",
                direction="sell",
                delta=short_call_opt["greeks"]["delta"],
                mark_price=short_call_opt["mark_price"],
                mark_iv=short_call_opt.get("mark_iv", 0)
            )

            long_call = OptionLeg(
                instrument_name=long_call_opt["instrument_name"],
                strike=long_call_opt["strike"],
                option_type="call",
                direction="buy",
                delta=long_call_opt["greeks"]["delta"],
                mark_price=long_call_opt["mark_price"],
                mark_iv=long_call_opt.get("mark_iv", 0)
            )

            credit_per_unit = (
                short_put.mark_price + short_call.mark_price
                - long_put.mark_price - long_call.mark_price
            ) * spot_price

            if credit_per_unit <= 0: return None

            put_spread_width = (short_put.strike - long_put.strike)
            call_spread_width = (long_call.strike - short_call.strike)
            max_loss_per_unit = max(put_spread_width, call_spread_width) - credit_per_unit

            if max_loss_per_unit <= 0: return None

            size = risk_per_condor / max_loss_per_unit
            size = max(0.01, min(size, 10.0))

            condor_id = f"{currency}_{expiration_date}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            condor = IronCondor(
                id=condor_id,
                currency=currency,
                expiration_date=expiration_date,
                spot_price=spot_price,
                entry_time=datetime.now(),
                long_put=long_put,
                short_put=short_put,
                short_call=short_call,
                long_call=long_call,
                credit_received=credit_per_unit * size,
                max_loss=max_loss_per_unit * size,
                max_profit=credit_per_unit * size,
                size=size,
                take_profit_target=credit_per_unit * size * tp_ratio,
                stop_loss_target=-(credit_per_unit * size * sl_mult),
                status="open"
            )

            return condor

        except Exception as e:
            logger.error(f"Error building Iron Condor: {e}")
            return None


class IronCondorStrategy(BaseStrategy):
    """Iron Condor Strategy Implementation"""

    def __init__(self, client, config, dependencies):
        super().__init__(client, config, dependencies)
        
        self.condor_builder = IronCondorBuilder(
            short_delta_target=config.short_delta_target,
            wing_width_percent=config.wing_width_percent
        )
        self.volatility_analyzer = VolatilityAnalyzer(lookback_days=30)

    def find_suitable_expiration(self, currency: str) -> Optional[str]:
        try:
            instruments = self.client.get_instruments(currency, kind="option")
            expirations = {}
            for inst in instruments:
                exp_date = inst.get("expiration_timestamp")
                if exp_date:
                    exp_dt = datetime.fromtimestamp(exp_date / 1000)
                    days = (exp_dt - datetime.now()).days

                    if self.config.min_dte <= days <= self.config.max_dte:
                        exp_str = exp_dt.strftime("%d%b%y").upper()
                        if exp_str not in expirations:
                            expirations[exp_str] = days

            if not expirations:
                return None

            best_exp = min(expirations.items(), key=lambda x: abs(x[1] - self.config.min_dte))
            return best_exp[0]
        except Exception as e:
            self.logger.error(f"Error finding expiration: {e}")
            return None

    def get_options_chain_with_greeks(self, currency: str, expiration: str) -> List[Dict]:
        try:
            instruments = self.client.get_instruments(currency, kind="option")
            options = []
            for inst in instruments:
                exp_timestamp = inst.get("expiration_timestamp")
                if exp_timestamp:
                    exp_dt = datetime.fromtimestamp(exp_timestamp / 1000)
                    exp_str = exp_dt.strftime("%d%b%y").upper()

                    if exp_str == expiration:
                        book = self.client.get_order_book(inst["instrument_name"])
                        if book:
                            inst["mark_price"] = book.get("mark_price", 0)
                            inst["mark_iv"] = book.get("mark_iv", 0)
                            inst["greeks"] = book.get("greeks", {})
                            options.append(inst)
                        time.sleep(0.05)
            return options
        except Exception as e:
            self.logger.error(f"Error getting options chain: {e}")
            return []

    def scan(self) -> List[Dict[str, Any]]:
        signals = []
        
        # Check global risk first
        can_open, reason = self.risk_manager.can_open_new_position()
        if not can_open:
            self.logger.info(f"Cannot open new position: {reason}")
            return signals

        for currency in self.config.currencies:
            self.logger.info(f"Scanning {currency}...")
            
            spot_price = self.client.get_index_price(currency)
            if not spot_price: continue

            expiration = self.find_suitable_expiration(currency)
            if not expiration: continue

            options = self.get_options_chain_with_greeks(currency, expiration)
            if not options: continue

            atm_iv = self.volatility_analyzer.get_atm_iv(options, spot_price)
            if not atm_iv: continue

            self.volatility_analyzer.update_iv_history(currency, atm_iv)
            
            should_enter, iv_reason = self.volatility_analyzer.should_enter_position(
                currency, atm_iv, min_iv_percentile=self.config.min_iv_percentile
            )

            if should_enter:
                self.logger.info(f"Opportunity found for {currency}: {iv_reason}")
                
                # Calculate size
                risk_amount = self.risk_manager.calculate_position_size()
                
                condor = self.condor_builder.build_condor(
                    currency=currency,
                    options_chain=options,
                    spot_price=spot_price,
                    expiration_date=expiration,
                    risk_per_condor=risk_amount,
                    tp_ratio=self.config.tp_ratio,
                    sl_mult=self.config.sl_mult
                )
                
                if condor:
                    signals.append({
                        "type": "iron_condor",
                        "condor": condor,
                        "currency": currency
                    })
        
        return signals

    def execute_entry(self, signal: Dict[str, Any]) -> bool:
        condor = signal.get("condor")
        if not condor: return False

        # Validate trade
        is_valid, validation_reason = self.risk_manager.validate_trade(condor.max_loss)
        if not is_valid:
            self.logger.warning(f"Trade validation failed: {validation_reason}")
            return False

        # Open condor
        use_market = (self.config.enabled) # Assuming if enabled we trade? No, check env.
        # Actually env is in client or global config.
        # Let's assume we use LIMIT orders by default unless forced.
        # In the original code: use_market = (self.env == "test")
        # We don't have direct access to env here easily unless we pass it or check client.
        # Let's default to False (Limit) for safety, or True if test.
        # For now, let's assume Limit orders.
        
        self.logger.info(f"Opening Iron Condor {condor.id}...")
        success = self.order_manager.open_iron_condor(condor, use_market_orders=False)

        if success:
            self.position_monitor.add_condor(condor)
            self.logger.info(f"✓ Successfully opened condor {condor.id}")
            return True
        else:
            self.logger.error(f"✗ Failed to open condor")
            return False

    def manage_positions(self) -> Dict[str, Any]:
        # Delegate to position monitor, but we might want to filter by strategy if we had multiple IC strategies.
        # For now, PositionMonitor manages all "condors".
        # If we have other strategies, PositionMonitor needs to know which positions belong to which strategy?
        # Or we just let PositionMonitor manage all "condors" regardless of who created them.
        # Since this is the only strategy creating condors, it's fine.
        
        stats = self.position_monitor.monitor_positions(self.config.close_before_expiry_hours)
        return stats
