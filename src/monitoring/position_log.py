"""
PositionLog — log leggibile di apertura/chiusura posizioni.

Mostra ogni valore sia in USD che in BTC, cosi' e' facile capire
quanto si guadagna o si perde in termini reali di Bitcoin.

File: logs/positions.log
"""
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.journal.trade_logger import TradeSnapshot

logger = logging.getLogger(__name__)

_SEP  = "=" * 60
_LINE = "-" * 60


def _btc(usd: float, btc_price: float) -> str:
    """Converti USD in BTC e formatta come '0.00051234 BTC'."""
    if btc_price <= 0:
        return "N/A BTC"
    return f"{usd / btc_price:.8f} BTC"


class PositionLog:
    """
    Scrive un log human-readable di trade aperti e chiusi,
    con valori in USD e BTC per ogni riga significativa.

    Usage:
        plog = PositionLog("logs/positions.log")
        plog.log_open(snapshot, equity_before=10000.0)
        plog.log_close(snapshot, equity_after=10034.40)
    """

    def __init__(self, log_path: str = "logs/positions.log"):
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

        # Dedicated file logger — non usa il root logger per non sporcare il log principale
        self._file_logger = logging.getLogger(f"position_log.{id(self)}")
        self._file_logger.setLevel(logging.INFO)
        self._file_logger.propagate = False  # non scrive nel log principale

        handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._file_logger.addHandler(handler)

        logger.info(f"[PositionLog] Log posizioni: {log_path}")

    # ------------------------------------------------------------------

    def log_open(self, snapshot: "TradeSnapshot", equity_before: float):
        """Scrive il blocco di apertura posizione."""
        try:
            ts        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            direction = "LONG" if snapshot.direction.lower() == "buy" else "SHORT"
            ep        = snapshot.entry_price   # BTC price at entry (USD)

            size_usd   = snapshot.quantity * ep
            risk_usd   = snapshot.quantity * abs(ep - snapshot.sl_price)
            target_usd = snapshot.quantity * abs(snapshot.tp_price - ep) if snapshot.tp_price else 0.0
            rr         = target_usd / risk_usd if risk_usd > 0 else 0.0

            # Equity in BTC (usa entry price come riferimento BTC/USD)
            eq_btc = equity_before / ep if ep > 0 else 0.0

            lines = [
                "",
                _SEP,
                f"POSIZIONE APERTA   {ts}",
                _LINE,
                f"Strategia   : {snapshot.strategy}",
                f"Strumento   : {snapshot.instrument}",
                f"Direzione   : {direction}",
                f"",
                f"  Prezzo BTC  : ${ep:,.2f}",
                f"  Size        : {snapshot.quantity:.6f} BTC  =  ${size_usd:,.2f}",
                f"  Entry       : ${ep:,.2f}",
                f"  Stop Loss   : ${snapshot.sl_price:,.2f}  |  rischio: ${risk_usd:,.2f}  ({_btc(risk_usd, ep)})",
            ]
            if snapshot.tp_price:
                lines.append(
                    f"  Take Profit : ${snapshot.tp_price:,.2f}  |  target: +${target_usd:,.2f}  "
                    f"(+{_btc(target_usd, ep)})  R/R {rr:.1f}x"
                )
            lines += [
                f"",
                f"  Regime      : {snapshot.regime}",
                f"",
                f"  Conto prima : ${equity_before:,.2f}  ({eq_btc:.6f} BTC)",
                _SEP,
            ]
            self._write(lines)
        except Exception as e:
            logger.debug(f"[PositionLog] log_open error: {e}")

    def log_close(self, snapshot: "TradeSnapshot", equity_after: float):
        """Scrive il blocco di chiusura posizione con P&L in USD e BTC."""
        try:
            ts        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            direction = "LONG" if snapshot.direction.lower() == "buy" else "SHORT"
            pnl       = snapshot.pnl_usd
            ep        = snapshot.entry_price    # prezzo BTC all'ingresso
            xp        = snapshot.exit_price     # prezzo BTC all'uscita

            pnl_pct    = pnl / snapshot.equity_at_entry * 100 if snapshot.equity_at_entry > 0 else 0.0
            pnl_btc    = pnl / xp if xp > 0 else 0.0   # P&L in BTC al prezzo di uscita
            eq_before  = snapshot.equity_at_entry
            eq_btc_bef = eq_before / ep if ep > 0 else 0.0
            eq_btc_aft = equity_after / xp if xp > 0 else 0.0

            sign = "+" if pnl >= 0 else "-"
            pnl_usd_str = f"{sign}${abs(pnl):,.2f}"
            pnl_btc_str = f"{sign}{abs(pnl_btc):.8f} BTC"
            pnl_pct_str = f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%"

            motivo_map = {
                "tp":     "TP raggiunto",
                "sl":     "SL colpito",
                "manual": "Chiuso manualmente",
                "time":   "Scadenza tempo",
            }
            motivo = motivo_map.get((snapshot.exit_reason or "").lower(), snapshot.exit_reason or "?")

            lines = [
                "",
                _SEP,
                f"POSIZIONE CHIUSA   {ts}",
                _LINE,
                f"Strumento   : {snapshot.instrument}  {direction}",
                f"Durata      : {snapshot.duration_minutes:.0f} min",
                f"",
                f"  Entry       : ${ep:,.2f}",
                f"  Exit        : ${xp:,.2f}",
                f"  Motivo      : {motivo}",
                f"",
                f"  P&L         : {pnl_usd_str}  ({pnl_btc_str})  {pnl_pct_str}",
                f"",
                f"  Conto prima : ${eq_before:,.2f}  ({eq_btc_bef:.6f} BTC)",
                f"  Conto dopo  : ${equity_after:,.2f}  ({eq_btc_aft:.6f} BTC)",
                _SEP,
            ]
            self._write(lines)
        except Exception as e:
            logger.debug(f"[PositionLog] log_close error: {e}")

    def _write(self, lines):
        for line in lines:
            self._file_logger.info(line)
