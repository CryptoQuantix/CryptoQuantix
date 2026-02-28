"""
PositionMonitor — monitora posizioni aperte e gestisce cleanup ordini orfani.

Responsabilità:
  1. Traccia le posizioni Iron Condor (comportamento originale invariato)
  2. Monitora le posizioni futures/perpetual generiche su Deribit
  3. Ogni N secondi rileva e cancella ordini SL/TP orfani tramite OrderRegistry
     (quando una posizione è chiusa da SL o TP, l'ordine compagno rimane aperto
      su Deribit — questo modulo lo rimuove automaticamente)
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

from src.core.deribit_client import DeribitClient
from src.core.order_manager import OrderManager
from src.core.order_registry import OrderRegistry
from src.strategies.iron_condor import IronCondor

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Monitor posizioni aperte — Iron Condor e futures generici."""

    def __init__(
        self,
        client: DeribitClient,
        order_manager: OrderManager,
        registry: Optional[OrderRegistry] = None
    ):
        """
        Args:
            client:        Deribit API client
            order_manager: OrderManager per chiudere posizioni
            registry:      OrderRegistry per cleanup ordini orfani (opzionale ma consigliato)
        """
        self.client = client
        self.order_manager = order_manager
        self.registry = registry

        # --- Iron Condor tracking (codice originale invariato) ---
        self.open_condors: Dict[str, IronCondor] = {}

    # ==================================================================
    # IRON CONDOR — codice originale intatto
    # ==================================================================

    def add_condor(self, condor: IronCondor):
        """Add a new Iron Condor to monitor"""
        self.open_condors[condor.id] = condor
        logger.info(f"Added condor {condor.id} to monitoring")

    def remove_condor(self, condor_id: str):
        """Remove an Iron Condor from monitoring"""
        if condor_id in self.open_condors:
            del self.open_condors[condor_id]
            logger.info(f"Removed condor {condor_id} from monitoring")

    def get_condor_pnl(self, condor: IronCondor) -> Optional[float]:
        """Calculate current P&L for an Iron Condor"""
        try:
            total_current_value = 0.0

            legs = [
                (condor.long_put, "buy"),
                (condor.short_put, "sell"),
                (condor.short_call, "sell"),
                (condor.long_call, "buy")
            ]

            spot_price = self.client.get_index_price(condor.currency)
            if not spot_price:
                logger.error(f"Could not get spot price for {condor.currency}")
                return None

            for leg, direction in legs:
                book = self.client.get_order_book(leg.instrument_name, depth=1)

                if not book:
                    logger.warning(f"Could not get order book for {leg.instrument_name}")
                    continue

                current_mark = book.get("mark_price", leg.mark_price)

                if direction == "buy":
                    value = current_mark * condor.size * spot_price
                else:
                    value = -current_mark * condor.size * spot_price

                total_current_value += value

            pnl = condor.credit_received + total_current_value
            return round(pnl, 2)

        except Exception as e:
            logger.error(f"Error calculating P&L for {condor.id}: {e}")
            return None

    def check_exit_conditions(self, condor: IronCondor, hours_before_expiry: int = 24) -> Tuple[bool, str]:
        """Check if any exit conditions are met for a condor"""
        try:
            exp_dt = datetime.strptime(condor.expiration_date, "%d%b%y")
            time_to_expiry = exp_dt - datetime.now()

            if time_to_expiry.total_seconds() < (hours_before_expiry * 3600):
                return True, "expiry"
        except Exception as e:
            logger.error(f"Error parsing expiration date: {e}")

        pnl = self.get_condor_pnl(condor)

        if pnl is None:
            logger.warning(f"Could not calculate P&L for {condor.id}")
            return False, ""

        if pnl >= condor.take_profit_target:
            return True, f"take_profit (P&L: ${pnl:.2f})"

        if pnl <= condor.stop_loss_target:
            return True, f"stop_loss (P&L: ${pnl:.2f})"

        return False, ""

    def monitor_positions(self, close_before_expiry_hours: int = 24) -> Dict[str, any]:
        """Monitor all open Iron Condor positions and execute TP/SL"""
        stats = {
            "total_monitored": len(self.open_condors),
            "closed_tp": 0,
            "closed_sl": 0,
            "closed_expiry": 0,
            "total_pnl": 0.0,
            "errors": 0
        }

        condors_to_close = []

        for condor_id, condor in self.open_condors.items():
            try:
                should_exit, reason = self.check_exit_conditions(
                    condor, close_before_expiry_hours
                )

                if should_exit:
                    pnl = self.get_condor_pnl(condor)
                    logger.info(f"Exit condition met for {condor_id}: {reason}, P&L: ${pnl:.2f}")
                    condors_to_close.append((condor, reason))

            except Exception as e:
                logger.error(f"Error monitoring condor {condor_id}: {e}")
                stats["errors"] += 1

        for condor, reason in condors_to_close:
            try:
                success = self.order_manager.close_iron_condor(condor, reason)

                if success:
                    pnl = self.get_condor_pnl(condor)
                    condor.realized_pnl = pnl
                    condor.close_time = datetime.now()
                    condor.close_reason = reason
                    condor.status = "closed"

                    if "take_profit" in reason:
                        stats["closed_tp"] += 1
                    elif "stop_loss" in reason:
                        stats["closed_sl"] += 1
                    elif "expiry" in reason:
                        stats["closed_expiry"] += 1

                    stats["total_pnl"] += pnl if pnl else 0
                    self.remove_condor(condor.id)

                    logger.info(f"Closed condor {condor.id}: {reason}, P&L: ${pnl:.2f}")
                else:
                    logger.error(f"Failed to close condor {condor.id}")
                    stats["errors"] += 1

            except Exception as e:
                logger.error(f"Error closing condor {condor.id}: {e}")
                stats["errors"] += 1

        return stats

    def get_portfolio_summary(self) -> Dict:
        """Get summary of all open Iron Condor positions"""
        summary = {
            "total_condors": len(self.open_condors),
            "total_pnl": 0.0,
            "total_risk": 0.0,
            "by_currency": {},
            "condors": []
        }

        for condor in self.open_condors.values():
            pnl = self.get_condor_pnl(condor)

            if pnl:
                summary["total_pnl"] += pnl

            summary["total_risk"] += condor.max_loss

            if condor.currency not in summary["by_currency"]:
                summary["by_currency"][condor.currency] = {
                    "count": 0, "pnl": 0.0, "risk": 0.0
                }

            summary["by_currency"][condor.currency]["count"] += 1
            summary["by_currency"][condor.currency]["pnl"] += pnl if pnl else 0
            summary["by_currency"][condor.currency]["risk"] += condor.max_loss

            summary["condors"].append({
                "id": condor.id,
                "currency": condor.currency,
                "expiration": condor.expiration_date,
                "entry_time": condor.entry_time.isoformat(),
                "pnl": pnl,
                "max_loss": condor.max_loss,
                "credit": condor.credit_received,
                "tp_target": condor.take_profit_target,
                "sl_target": condor.stop_loss_target
            })

        return summary

    def get_open_condor_count(self) -> int:
        """Get number of open condors"""
        return len(self.open_condors)

    def get_total_risk_exposure(self) -> float:
        """Get total risk across all open condors"""
        return sum(condor.max_loss for condor in self.open_condors.values())

    # ==================================================================
    # ORPHAN ORDER CLEANUP — logica per futures/perpetual generici
    # ==================================================================

    def check_orphan_orders(self, currencies: List[str] = None) -> Dict:
        """
        Rileva e cancella gli ordini SL/TP orfani su Deribit.

        Un ordine orfano è un SL o TP che rimane aperto dopo che la posizione
        associata è già stata chiusa (dall'ordine compagno o manualmente).

        Viene chiamato nel loop di management (ogni 5–30 secondi).

        Args:
            currencies: Lista di valute da controllare (es. ["BTC", "ETH"]).
                        Se None usa ["BTC", "ETH"] come default.

        Returns:
            Dict con statistiche del cleanup:
              orphans_found, orphans_cancelled, instruments_checked, errors
        """
        if not self.registry:
            return {"orphans_found": 0, "orphans_cancelled": 0, "instruments_checked": 0, "errors": 0}

        if not self.registry.has_trades():
            return {"orphans_found": 0, "orphans_cancelled": 0, "instruments_checked": 0, "errors": 0}

        if currencies is None:
            currencies = ["BTC", "ETH"]

        stats = {
            "orphans_found": 0,
            "orphans_cancelled": 0,
            "instruments_checked": 0,
            "errors": 0
        }

        try:
            # Recupera tutte le posizioni futures aperte su Deribit
            open_instruments = set()
            for currency in currencies:
                try:
                    positions = self.client.get_futures_positions(currency)
                    for pos in positions:
                        size = pos.get("size", 0)
                        instrument = pos.get("instrument_name", "")
                        # Posizione realmente aperta solo se size != 0
                        if instrument and size != 0:
                            open_instruments.add(instrument)
                except Exception as e:
                    logger.error(f"Errore get_futures_positions({currency}): {e}")
                    stats["errors"] += 1

            # Controlla ogni strumento tracciato nel registry
            tracked_instruments = self.registry.get_all_instruments()
            stats["instruments_checked"] = len(tracked_instruments)

            for instrument in tracked_instruments:
                if instrument not in open_instruments:
                    # Posizione chiusa — cerca e cancella ordini orfani
                    trades = self.registry.get_trades_by_instrument(instrument)

                    for trade in trades:
                        companion_ids = self.registry.get_companion_order_ids(trade.trade_id)

                        if not companion_ids:
                            self.registry.close_trade(trade.trade_id)
                            continue

                        logger.info(
                            f"[Orphan] Posizione {instrument} chiusa. "
                            f"Cancello {len(companion_ids)} ordini orfani: {companion_ids}"
                        )
                        stats["orphans_found"] += len(companion_ids)

                        for order_id in companion_ids:
                            try:
                                success = self.client.cancel(order_id)
                                if success:
                                    stats["orphans_cancelled"] += 1
                                    logger.info(f"[Orphan] Cancellato ordine orfano: {order_id}")
                                else:
                                    logger.warning(f"[Orphan] Impossibile cancellare: {order_id}")
                                    stats["errors"] += 1
                            except Exception as e:
                                logger.error(f"[Orphan] Errore cancellazione {order_id}: {e}")
                                stats["errors"] += 1

                        # Rimuovi il trade dal registry
                        self.registry.close_trade(trade.trade_id)

        except Exception as e:
            logger.error(f"Errore in check_orphan_orders: {e}", exc_info=True)
            stats["errors"] += 1

        if stats["orphans_found"] > 0:
            logger.info(
                f"[Orphan Cleanup] Trovati: {stats['orphans_found']} | "
                f"Cancellati: {stats['orphans_cancelled']} | "
                f"Errori: {stats['errors']}"
            )

        return stats

    def get_open_futures_positions(self, currencies: List[str] = None) -> List[Dict]:
        """
        Ritorna le posizioni futures/perpetual aperte su Deribit.
        Utile per le strategie che vogliono conoscere lo stato corrente.

        Args:
            currencies: ["BTC", "ETH"] di default

        Returns:
            Lista di posizioni con size != 0
        """
        if currencies is None:
            currencies = ["BTC", "ETH"]

        all_positions = []
        for currency in currencies:
            try:
                positions = self.client.get_futures_positions(currency)
                open_positions = [p for p in positions if p.get("size", 0) != 0]
                all_positions.extend(open_positions)
            except Exception as e:
                logger.error(f"Errore get_futures_positions({currency}): {e}")

        return all_positions

    def log_registry_summary(self):
        """Logga il riepilogo del registry (utile per debug)."""
        if self.registry:
            logger.info(self.registry.summary())
        else:
            logger.info("Registry non configurato")
