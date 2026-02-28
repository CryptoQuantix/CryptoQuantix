"""
OrderRegistry — traccia SL/TP order IDs per ogni trade aperto.

Problema risolto: quando SL o TP si triggera, l'ordine "compagno"
rimane aperto su Deribit come "orphan". Questo registro permette
di rilevarli e cancellarli automaticamente quando la posizione chiude.

Flusso:
  1. execute_generic_trade() piazza SL+TP → li registra qui
  2. PositionMonitor.check_orphan_orders() (ogni 5s):
     - Verifica posizioni aperte su Deribit
     - Per ogni strumento nel registry senza posizione aperta
       → cancella gli ordini compagni rimasti → pulisce il registry
"""
import uuid
import threading
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Record di un singolo trade con i suoi ordini associati."""
    trade_id: str
    instrument: str
    direction: str          # "buy" | "sell"
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    trail_order_id: Optional[str] = None
    label: str = ""


class OrderRegistry:
    """
    Registry thread-safe: mappa trade_id → {SL order_id, TP order_id, trail order_id}.
    Permette il cleanup automatico degli ordini orfani quando una posizione si chiude.
    """

    def __init__(self):
        self._records: Dict[str, TradeRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registrazione
    # ------------------------------------------------------------------

    def register_trade(
        self,
        instrument: str,
        direction: str,
        sl_order_id: Optional[str] = None,
        tp_order_id: Optional[str] = None,
        trail_order_id: Optional[str] = None,
        label: str = ""
    ) -> str:
        """
        Registra un nuovo trade e restituisce il suo trade_id univoco.

        Args:
            instrument:     Strumento (es. BTC-PERPETUAL)
            direction:      "buy" o "sell"
            sl_order_id:    Order ID dello stop loss (opzionale)
            tp_order_id:    Order ID del take profit (opzionale)
            trail_order_id: Order ID del trailing stop (opzionale)
            label:          Label del trade per tracciabilità

        Returns:
            trade_id (UUID string)
        """
        trade_id = str(uuid.uuid4())
        record = TradeRecord(
            trade_id=trade_id,
            instrument=instrument,
            direction=direction,
            sl_order_id=sl_order_id,
            tp_order_id=tp_order_id,
            trail_order_id=trail_order_id,
            label=label
        )
        with self._lock:
            self._records[trade_id] = record

        logger.info(
            f"[Registry] Trade registrato {trade_id[:8]} | "
            f"{instrument} {direction.upper()} | "
            f"SL={sl_order_id or 'n/a'} TP={tp_order_id or 'n/a'} Trail={trail_order_id or 'n/a'}"
        )
        return trade_id

    def update_trade(
        self,
        trade_id: str,
        sl_order_id: Optional[str] = None,
        tp_order_id: Optional[str] = None,
        trail_order_id: Optional[str] = None
    ):
        """
        Aggiorna gli order ID di un trade esistente.
        Utile quando il trailing stop viene spostato e l'order ID cambia.
        """
        with self._lock:
            rec = self._records.get(trade_id)
            if not rec:
                logger.warning(f"[Registry] update_trade: trade_id {trade_id[:8]} non trovato")
                return
            if sl_order_id is not None:
                rec.sl_order_id = sl_order_id
            if tp_order_id is not None:
                rec.tp_order_id = tp_order_id
            if trail_order_id is not None:
                rec.trail_order_id = trail_order_id

        logger.debug(f"[Registry] Trade {trade_id[:8]} aggiornato")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_companion_order_ids(self, trade_id: str) -> List[str]:
        """Restituisce tutti gli order ID non-None (SL + TP + trail) per un trade."""
        with self._lock:
            rec = self._records.get(trade_id)
            if not rec:
                return []
            return [
                oid for oid in [rec.sl_order_id, rec.tp_order_id, rec.trail_order_id]
                if oid is not None
            ]

    def get_trades_by_instrument(self, instrument: str) -> List[TradeRecord]:
        """Restituisce tutti i trade record per un dato strumento."""
        with self._lock:
            return [r for r in self._records.values() if r.instrument == instrument]

    def get_all_instruments(self) -> List[str]:
        """Restituisce la lista unica di strumenti con trade aperti nel registry."""
        with self._lock:
            return list({r.instrument for r in self._records.values()})

    def get_all_trade_ids(self) -> List[str]:
        """Restituisce tutti i trade_id registrati."""
        with self._lock:
            return list(self._records.keys())

    def has_trades(self) -> bool:
        """True se ci sono trade registrati."""
        with self._lock:
            return bool(self._records)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close_trade(self, trade_id: str):
        """Rimuove un trade dal registry dopo che è stato chiuso e pulito."""
        with self._lock:
            removed = self._records.pop(trade_id, None)
        if removed:
            logger.info(f"[Registry] Trade {trade_id[:8]} rimosso ({removed.instrument})")
        else:
            logger.debug(f"[Registry] close_trade: {trade_id[:8]} non trovato (già rimosso?)")

    def close_all_by_instrument(self, instrument: str):
        """Rimuove tutti i trade per uno strumento (es. dopo chiusura forzata)."""
        with self._lock:
            ids_to_remove = [
                tid for tid, rec in self._records.items()
                if rec.instrument == instrument
            ]
            for tid in ids_to_remove:
                del self._records[tid]
        if ids_to_remove:
            logger.info(f"[Registry] Rimossi {len(ids_to_remove)} trade per {instrument}")

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """Riepilogo human-readable di tutti i trade tracciati."""
        with self._lock:
            if not self._records:
                return "Registry vuoto"
            lines = [f"Registry ({len(self._records)} trade aperti):"]
            for rec in self._records.values():
                lines.append(
                    f"  [{rec.trade_id[:8]}] {rec.instrument} {rec.direction.upper()} "
                    f"label={rec.label or 'n/a'} | "
                    f"SL={rec.sl_order_id or '-'} "
                    f"TP={rec.tp_order_id or '-'} "
                    f"Trail={rec.trail_order_id or '-'}"
                )
            return "\n".join(lines)
