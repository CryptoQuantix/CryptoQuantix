from typing import Any, Dict, Optional, Tuple
from datetime import date
import logging
from src.core.deribit_client import DeribitClient
from src.core.position_monitor import PositionMonitor

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Manage risk and position sizing.

    Funzionalità:
      - Sizing Iron Condor (metodi originali invariati)
      - Sizing futures direzionale con 3-factor dinamico:
          Factor 1: Volatilità (ATR percentile → scalar 0.5–1.0)
          Factor 2: Regime di mercato (EXPANSION/COMPRESSION → scalar ridotto)
          Factor 3: Winrate storico del modello (Kelly fraction capped)
      - Kill switch giornaliero (max daily loss)
      - Tracking PnL giornaliero
    """

    def __init__(
        self,
        client: DeribitClient,
        position_monitor: PositionMonitor,
        initial_equity: float,
        risk_per_condor: float = 0.01,
        max_portfolio_risk: float = 0.03,
        base_risk_pct: float = 0.01,
        max_daily_loss_pct: float = 0.03,
        max_open_trades: int = 3,
        max_gross_exposure: float = 1.5,
    ):
        """
        Args:
            client:               Deribit API client
            position_monitor:     Position monitor instance
            initial_equity:       Initial account equity in USD
            risk_per_condor:      Risk per condor (Iron Condor legacy)
            max_portfolio_risk:   Max total risk (Iron Condor legacy)
            base_risk_pct:        Rischio base per trade futures (es. 0.01 = 1%)
            max_daily_loss_pct:   Kill switch giornaliero (es. 0.03 = -3%)
            max_open_trades:      Max trade aperti contemporaneamente
            max_gross_exposure:   Cap nozionale LORDO aggregato (x equity).
                                  Anti-oversizing quando piu' strategie aprono
                                  insieme (MacroCore core + tattiche multi-symbol)
        """
        self.client = client
        self.position_monitor = position_monitor
        self.initial_equity = initial_equity
        self.risk_per_condor = risk_per_condor
        self.max_portfolio_risk = max_portfolio_risk
        self.base_risk_pct = base_risk_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_open_trades = max_open_trades
        self.max_gross_exposure = max_gross_exposure

        # Daily tracking
        self._daily_pnl: float = 0.0
        self._daily_trade_count: int = 0
        self._kill_switch_triggered: bool = False
        self._last_reset_date: date = date.today()

    # ==================================================================
    # DAILY TRACKING & KILL SWITCH
    # ==================================================================

    def _check_daily_reset(self):
        """Reset contatori giornalieri se è un nuovo giorno."""
        today = date.today()
        if today != self._last_reset_date:
            logger.info(
                f"[Risk] Nuovo giorno — reset contatori. "
                f"PnL ieri: ${self._daily_pnl:+.2f} | Trade: {self._daily_trade_count}"
            )
            self._daily_pnl = 0.0
            self._daily_trade_count = 0
            self._kill_switch_triggered = False
            self._last_reset_date = today

    def register_trade_pnl(self, pnl_usd: float):
        """
        Registra il PnL di un trade chiuso per il tracking giornaliero.
        Chiamare dal manage_positions() di ogni strategia dopo la chiusura.
        """
        self._check_daily_reset()
        self._daily_pnl += pnl_usd
        self._daily_trade_count += 1
        logger.info(f"[Risk] PnL giornaliero aggiornato: ${self._daily_pnl:+.2f} (trade #{self._daily_trade_count})")
        self._check_kill_switch_condition()

    def _check_kill_switch_condition(self):
        """Controlla se la perdita giornaliera supera la soglia."""
        if self._kill_switch_triggered:
            return
        equity = self.get_total_equity()
        max_loss = equity * self.max_daily_loss_pct
        if self._daily_pnl <= -max_loss:
            self._kill_switch_triggered = True
            logger.critical(
                f"[KILL SWITCH] Perdita giornaliera ${self._daily_pnl:.2f} "
                f"supera limite ${-max_loss:.2f} ({self.max_daily_loss_pct:.0%} equity). "
                f"TRADING SOSPESO per oggi."
            )

    def is_kill_switch_active(self) -> bool:
        """True se il kill switch giornaliero è attivo."""
        self._check_daily_reset()
        return self._kill_switch_triggered

    def get_daily_stats(self) -> Dict:
        """Statistiche del giorno corrente."""
        self._check_daily_reset()
        equity = self.get_total_equity()
        return {
            "daily_pnl_usd": self._daily_pnl,
            "daily_pnl_pct": self._daily_pnl / equity * 100 if equity > 0 else 0,
            "daily_trade_count": self._daily_trade_count,
            "kill_switch_active": self._kill_switch_triggered,
            "max_daily_loss_usd": equity * self.max_daily_loss_pct,
            "remaining_loss_budget": (equity * self.max_daily_loss_pct) + self._daily_pnl
        }

    # ==================================================================
    # 3-FACTOR DYNAMIC SIZING (futures direzionali)
    # ==================================================================

    def calculate_dynamic_size(
        self,
        instrument_name: str,
        entry_price: float,
        sl_price: float,
        atr_percentile: float = 50.0,
        regime: str = "UNKNOWN",
        model_winrate: float = 0.5
    ) -> Dict[str, Any]:
        """
        Calcola la size di una posizione futures con 3 fattori dinamici.

        Formula:
            base_risk = equity × base_risk_pct
            adj_risk  = base_risk × volatility_scalar × regime_scalar × kelly_scalar
            quantity  = adj_risk / |entry - sl|

        Factor 1 — Volatilità (ATR percentile):
            atr_percentile < 30  → scalar = 1.0  (bassa vol, size piena)
            30 ≤ percentile < 70 → scalar = 0.75 (vol media)
            percentile ≥ 70      → scalar = 0.50 (alta vol, size ridotta)

        Factor 2 — Regime di mercato:
            TREND_UP / TREND_DOWN  → scalar = 1.0
            RANGE                  → scalar = 0.80
            COMPRESSION            → scalar = 0.60
            EXPANSION              → scalar = 0.70 (volatile)
            UNKNOWN                → scalar = 0.70 (conservativo)

        Factor 3 — Kelly fraction (capped al 25%):
            kelly = (winrate - (1 - winrate)) capped a [0.05, 0.25]
            scalar = kelly / 0.25  (normalizzato a 1.0 per kelly massimo)

        Args:
            instrument_name: Es. BTC-PERPETUAL
            entry_price:     Prezzo di entrata
            sl_price:        Prezzo di stop loss
            atr_percentile:  Percentile ATR (0–100) del timeframe operativo
            regime:          Regime rilevato (TREND_UP, TREND_DOWN, RANGE, COMPRESSION, EXPANSION)
            model_winrate:   Winrate storico del modello (0.0–1.0)

        Returns:
            Dict con quantity_btc, quantity_usd, max_loss_usd, effective_leverage,
                  adj_risk, scalars usati, equity
        """
        if self.is_kill_switch_active():
            logger.warning("[Risk] Kill switch attivo — sizing restituisce 0")
            return {"error": "Kill switch attivo", "quantity_btc": 0, "quantity_usd": 0}

        equity = self.get_total_equity()

        if entry_price <= 0 or sl_price <= 0:
            return {"error": "Prezzi non validi"}

        price_diff = abs(entry_price - sl_price)
        if price_diff == 0:
            return {"error": "Entry uguale a SL"}

        # --- Factor 1: Volatility scalar ---
        if atr_percentile < 30:
            vol_scalar = 1.0
        elif atr_percentile < 70:
            vol_scalar = 0.75
        else:
            vol_scalar = 0.50

        # --- Factor 2: Regime scalar ---
        regime_scalars = {
            "TREND_UP":    1.0,
            "TREND_DOWN":  1.0,
            "RANGE":       0.80,
            "EXPANSION":   0.70,
            "COMPRESSION": 0.60,
            "UNKNOWN":     0.70,
        }
        regime_scalar = regime_scalars.get(regime.upper(), 0.70)

        # --- Factor 3: Kelly fraction (capped) ---
        raw_kelly = winrate = model_winrate
        kelly_frac = max(0.05, min(0.25, (winrate - (1.0 - winrate))))
        kelly_scalar = kelly_frac / 0.25  # normalizzato: 1.0 = kelly al massimo (25%)

        # --- Rischio aggiustato ---
        base_risk = equity * self.base_risk_pct
        adj_risk = base_risk * vol_scalar * regime_scalar * kelly_scalar

        # --- Size ---
        quantity_btc = adj_risk / price_diff
        quantity_usd = quantity_btc * entry_price
        effective_leverage = quantity_usd / equity

        # Leverage cap
        max_leverage = 10.0
        if effective_leverage > max_leverage:
            logger.warning(
                f"[Risk] Leverage {effective_leverage:.1f}x > {max_leverage}x — riduzione size"
            )
            quantity_usd = equity * max_leverage
            quantity_btc = quantity_usd / entry_price
            effective_leverage = max_leverage
            adj_risk = quantity_btc * price_diff

        # Gross exposure cap: il nozionale del nuovo trade non deve portare
        # l'esposizione lorda aggregata oltre max_gross_exposure x equity
        available = self.available_gross_usd()
        if quantity_usd > available:
            logger.warning(
                f"[Risk] Gross cap: size ${quantity_usd:,.0f} -> ${available:,.0f} "
                f"(esposizione aggregata al limite {self.max_gross_exposure:.1f}x)"
            )
            quantity_usd = available
            quantity_btc = quantity_usd / entry_price if entry_price > 0 else 0
            effective_leverage = quantity_usd / equity if equity > 0 else 0
            adj_risk = quantity_btc * price_diff

        logger.info(
            f"[Risk] Dynamic sizing {instrument_name}: "
            f"vol_scalar={vol_scalar:.2f} regime_scalar={regime_scalar:.2f} "
            f"kelly_scalar={kelly_scalar:.2f} → "
            f"adj_risk=${adj_risk:.2f} qty={quantity_btc:.6f} BTC lev={effective_leverage:.1f}x"
        )

        return {
            "quantity_btc": quantity_btc,
            "quantity_usd": quantity_usd,
            "max_loss_usd": adj_risk,
            "effective_leverage": effective_leverage,
            "adj_risk_usd": adj_risk,
            "base_risk_usd": base_risk,
            "vol_scalar": vol_scalar,
            "regime_scalar": regime_scalar,
            "kelly_scalar": kelly_scalar,
            "kelly_frac": kelly_frac,
            "equity": equity,
            "regime": regime,
            "atr_percentile": atr_percentile,
            "model_winrate": model_winrate
        }

    def get_current_equity(self, currency: str = "BTC") -> Optional[float]:
        """
        Get current account equity from Deribit

        Args:
            currency: Currency to check (BTC or ETH)

        Returns:
            Current equity in USD
        """
        try:
            account = self.client.get_account_summary(currency)

            if account:
                # Deribit returns equity in the currency (BTC/ETH)
                equity_in_currency = account.get("equity", 0)

                # Convert to USD
                spot_price = self.client.get_index_price(currency)
                if spot_price:
                    equity_usd = equity_in_currency * spot_price
                    logger.info(f"Current equity for {currency}: ${equity_usd:,.2f}")
                    return equity_usd

            logger.warning(f"Could not get equity for {currency}, using initial equity")
            return self.initial_equity

        except Exception as e:
            logger.error(f"Error getting equity: {e}")
            return self.initial_equity

    def get_total_equity(self) -> float:
        """
        Get total equity across all currencies (BTC + ETH)

        Returns:
            Total equity in USD
        """
        btc_equity = self.get_current_equity("BTC") or 0
        eth_equity = self.get_current_equity("ETH") or 0
        total = btc_equity + eth_equity
        
        # TESTNET SAFETY CAP
        # If running in Testnet and Equity is unrealistically high (e.g. Testnet Faucet Funds),
        # cap the *Calculation Equity* to a realistic amount (e.g. $50,000) so that 
        # position sizing produces tradeable order sizes that don't hit market limits.
        # This allows verifying functionality (Open/Stop/Trail) without "Max Size" errors.
        # This logic is safe for Prod because Prod equity won't exceed $50k usually, 
        # and if it does, scaling down for safety is still consistent.
        if self.client and hasattr(self.client, 'env') and self.client.env == 'test':
             if total > 50000.0:
                 logger.warning(f"Testnet Equity ${total:,.2f} exceeds cap. Using $50,000 for sizing calculations.")
                 total = 50000.0

        logger.info(f"Total equity: ${total:,.2f} (BTC: ${btc_equity:,.2f}, ETH: ${eth_equity:,.2f})")
        return total

    def calculate_position_size(self, equity: Optional[float] = None) -> float:
        """
        Calculate risk amount per condor based on current equity

        Args:
            equity: Current equity (if None, will fetch from account)

        Returns:
            Risk amount in USD per condor
        """
        if equity is None:
            equity = self.get_total_equity()

        risk_amount = equity * self.risk_per_condor

        logger.info(f"Risk per condor: ${risk_amount:.2f} ({self.risk_per_condor:.1%} of ${equity:,.2f})")
        return risk_amount

    # ==================================================================
    # GROSS EXPOSURE CAP (anti-oversizing multi-strategia)
    # ==================================================================

    def get_gross_exposure_usd(self) -> float:
        """Somma del nozionale ASSOLUTO di tutte le posizioni futures aperte.
        Su Deribit perpetual/futures lineari-inversi `size` e' in USD."""
        try:
            positions = self.position_monitor.get_open_futures_positions()
            return float(sum(abs(p.get("size", 0)) for p in positions))
        except Exception as e:
            logger.error(f"[Risk] get_gross_exposure_usd: {e}")
            return 0.0

    def available_gross_usd(self) -> float:
        """Nozionale ancora apribile prima del cap lordo aggregato."""
        equity = self.get_total_equity()
        cap = equity * self.max_gross_exposure
        return max(0.0, cap - self.get_gross_exposure_usd())

    def can_open_new_position(self) -> Tuple[bool, str]:
        """
        Gate di portafoglio per le strategie futures:
          1. kill switch giornaliero
          2. numero massimo di posizioni aperte (max_open_trades)
          3. cap di esposizione lorda aggregata (max_gross_exposure x equity)

        Returns:
            Tuple of (can_open, reason)
        """
        if self.is_kill_switch_active():
            return False, "Kill switch giornaliero attivo"

        try:
            positions = self.position_monitor.get_open_futures_positions()
        except Exception as e:
            return True, f"position check failed ({e}) — gate bypassed"

        n_open = len(positions)
        if n_open >= self.max_open_trades:
            return False, (f"Max posizioni aperte raggiunto: "
                           f"{n_open}/{self.max_open_trades}")

        equity = self.get_total_equity()
        gross = float(sum(abs(p.get("size", 0)) for p in positions))
        cap = equity * self.max_gross_exposure
        if gross >= cap:
            return False, (f"Cap esposizione lorda raggiunto: "
                           f"${gross:,.0f} >= ${cap:,.0f} "
                           f"({self.max_gross_exposure:.1f}x equity)")

        return True, (f"OK — posizioni {n_open}/{self.max_open_trades}, "
                      f"gross ${gross:,.0f}/${cap:,.0f}")

    def get_max_condors_allowed(self) -> int:
        """
        Calculate maximum number of condors allowed based on current equity

        Returns:
            Maximum number of condors
        """
        equity = self.get_total_equity()
        max_total_risk = equity * self.max_portfolio_risk
        risk_per_condor = equity * self.risk_per_condor

        if risk_per_condor <= 0:
            return 0

        max_condors = int(max_total_risk / risk_per_condor)
        return max_condors

    def get_risk_summary(self) -> Dict:
        """
        Get comprehensive risk summary

        Returns:
            Dict with risk metrics
        """
        equity = self.get_total_equity()
        current_risk = self.position_monitor.get_total_risk_exposure()
        max_risk = equity * self.max_portfolio_risk
        risk_per_condor = self.calculate_position_size(equity)

        portfolio = self.position_monitor.get_portfolio_summary()

        summary = {
            "equity": equity,
            "initial_equity": self.initial_equity,
            "equity_change": equity - self.initial_equity,
            "equity_change_pct": ((equity - self.initial_equity) / self.initial_equity * 100)
                                if self.initial_equity > 0 else 0,
            "current_risk": current_risk,
            "max_risk": max_risk,
            "risk_utilization_pct": (current_risk / max_risk * 100) if max_risk > 0 else 0,
            "available_risk": max_risk - current_risk,
            "risk_per_condor": risk_per_condor,
            "max_condors_allowed": self.get_max_condors_allowed(),
            "current_condors": self.position_monitor.get_open_condor_count(),
            "total_pnl": portfolio["total_pnl"],
            "config": {
                "risk_per_condor_pct": self.risk_per_condor * 100,
                "max_portfolio_risk_pct": self.max_portfolio_risk * 100
            }
        }

        return summary

    def validate_trade(self, expected_max_loss: float) -> Tuple[bool, str]:
        """
        Validate if a trade meets risk requirements

        Args:
            expected_max_loss: Expected max loss of the trade

        Returns:
            Tuple of (is_valid, reason)
        """
        equity = self.get_total_equity()
        risk_per_condor = self.calculate_position_size(equity)

        # Check if trade risk is reasonable
        # Accept trades between 20% and 150% of target risk
        if expected_max_loss > risk_per_condor * 1.5:
            return False, (
                f"Trade risk ${expected_max_loss:.2f} too high "
                f"(target: ${risk_per_condor:.2f})"
            )

        if expected_max_loss < risk_per_condor * 0.2:
            return False, (
                f"Trade risk ${expected_max_loss:.2f} too low "
                f"(target: ${risk_per_condor:.2f}, minimum 20%)"
            )

        # Check portfolio risk limit
        can_open, reason = self.can_open_new_position()
        if not can_open:
            return False, reason

        return True, "Trade validated"

    def update_risk_parameters(self, risk_per_condor: float = None,
                              max_portfolio_risk: float = None):
        """
        Update risk parameters

        Args:
            risk_per_condor: New risk per condor (fraction)
            max_portfolio_risk: New max portfolio risk (fraction)
        """
        if risk_per_condor is not None:
            self.risk_per_condor = risk_per_condor
            logger.info(f"Updated risk per condor: {risk_per_condor:.1%}")

        if max_portfolio_risk is not None:
            self.max_portfolio_risk = max_portfolio_risk
            logger.info(f"Updated max portfolio risk: {max_portfolio_risk:.1%}")

    def emergency_stop(self) -> bool:
        """
        Emergency stop: close all positions

        Returns:
            True if successful
        """
        logger.warning("EMERGENCY STOP TRIGGERED - Closing all positions")

        try:
            # Cancel all pending orders first
            self.client.cancel_all()

            # Close all open condors
            for condor in list(self.position_monitor.open_condors.values()):
                from src.core.order_manager import OrderManager
                order_manager = OrderManager(self.client)
                order_manager.close_iron_condor(condor, "emergency_stop")

            logger.info("Emergency stop completed")
            return True

        except Exception as e:
            logger.error(f"Error during emergency stop: {e}")
            return False
    def calculate_futures_quantity(self, entry_price: float, sl_price: float, risk_pct: float = 0.015, leverage_max: int = 5) -> Dict[str, Any]:
        """
        Calculate position size for futures/perpetuals based on risk percentage and stop loss.
        
        Formula: Quantity = (Equity * Risk_Pct) / |Entry - SL|
        Returns detailed risk metrics including leverage check.
        
        Args:
            entry_price: Entry price
            sl_price: Stop loss price
            risk_pct: Risk percentage (default 1.5%)
            leverage_max: Maximum allowed leverage
            
        Returns:
            Dict with quantity, leverage, margin, max_loss, error (if any)
        """
        equity = self.get_total_equity()
        
        if entry_price <= 0 or sl_price <= 0:
            return {"error": "Invalid prices"}
            
        price_diff = abs(entry_price - sl_price)
        if price_diff == 0:
             return {"error": "Entry equals SL"}
             
        # 1. Calculate Max Loss (Risk Amount)
        max_loss_usd = equity * risk_pct
        
        # 2. Calculate Position Size (BTC)
        # Size = Risk / Distance
        position_size_btc = max_loss_usd / price_diff
        
        # 3. Calculate Position Value (USD)
        position_value_usd = position_size_btc * entry_price
        
        # 4. Calculate Effective Leverage
        effective_leverage = position_value_usd / equity
        
        # 5. Check Leverage Limit
        if effective_leverage > leverage_max:
            logger.warning(f"Calculated leverage {effective_leverage:.2f}x exceeds max {leverage_max}x. Reducing size.")
            # Cap size to max leverage
            position_value_usd = equity * leverage_max
            position_size_btc = position_value_usd / entry_price
            effective_leverage = leverage_max
            # Recalculate max loss
            max_loss_usd = position_size_btc * price_diff

        # SAFETY CAP FOR TESTNET/PROD (Prevent massive erroneous orders)
        # Cap max position value to $100k USD per trade (configurable ideally)
        MAX_POS_VALUE = 100000.0
        if position_value_usd > MAX_POS_VALUE:
             logger.warning(f"Position value ${position_value_usd:,.2f} exceeds Safety Cap ${MAX_POS_VALUE:,.2f}. Scaling down.")
             ratio = MAX_POS_VALUE / position_value_usd
             position_value_usd = MAX_POS_VALUE
             position_size_btc = position_size_btc * ratio
             max_loss_usd = max_loss_usd * ratio
            
        return {
            "quantity_btc": position_size_btc,
            "quantity_usd": position_value_usd,
            "max_loss_usd": max_loss_usd,
            "effective_leverage": effective_leverage,
            "equity": equity
        }

    def calculate_exit_levels(self, entry_price: float, sl_price: float, rr_ratio: float = 2.5) -> Dict[str, Any]:
        """
        Calculate Take Profit price based on Risk:Reward ratio.
        """
        risk_distance = abs(entry_price - sl_price)
        tp_distance = risk_distance * rr_ratio
        
        is_long = entry_price > sl_price # SL below entry = Long
        
        if is_long:
            tp_price = entry_price + tp_distance
            trade_type = "LONG"
        else:
            tp_price = entry_price - tp_distance
            trade_type = "SHORT"
            
        return {
            "trade_type": trade_type,
            "tp_price": tp_price,
            "risk_distance": risk_distance,
            "rr_ratio": rr_ratio
        }
