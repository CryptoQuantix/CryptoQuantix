"""
SignalLog — traccia tutti i segnali generati dalle strategie,
sia eseguiti che bloccati dai filtri (regime, scoring, rate limit).

Permette di rispondere a: "se avessimo tradato quel segnale bloccato,
avremmo guadagnato o perso?"

Schema SQLite:
  signal_log(id, timestamp, strategy, direction, price, sl, tp,
             regime, executed, block_reason,
             outcome, exit_price, pnl_r, checked_at)
"""
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS signal_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    strategy     TEXT    NOT NULL,
    direction    TEXT    NOT NULL,
    price        REAL    NOT NULL,
    sl           REAL    NOT NULL,
    tp           REAL    NOT NULL,
    regime       TEXT    DEFAULT 'UNKNOWN',
    executed     INTEGER NOT NULL DEFAULT 0,
    block_reason TEXT,
    outcome      TEXT,
    exit_price   REAL,
    pnl_r        REAL,
    checked_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sl_executed  ON signal_log(executed);
CREATE INDEX IF NOT EXISTS idx_sl_outcome   ON signal_log(outcome);
CREATE INDEX IF NOT EXISTS idx_sl_strategy  ON signal_log(strategy);
CREATE INDEX IF NOT EXISTS idx_sl_timestamp ON signal_log(timestamp);
"""


class SignalLog:
    """Thread-safe SQLite signal journal."""

    def __init__(self, db_path: str = "data/signal_log.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db = db_path
        self._init_db()
        count = self._count()
        logger.info(f"[SignalLog] DB: {db_path} | {count} segnali storici")

    # ------------------------------------------------------------------ #
    # Setup
    # ------------------------------------------------------------------ #

    def _init_db(self):
        with sqlite3.connect(self._db) as conn:
            conn.executescript(_DDL)
            conn.commit()

    def _count(self) -> int:
        with sqlite3.connect(self._db) as conn:
            return conn.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0]

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def log_signal(
        self,
        strategy: str,
        direction: str,
        price: float,
        sl: float,
        tp: float,
        regime: str = "UNKNOWN",
        executed: bool = False,
        block_reason: Optional[str] = None,
    ) -> int:
        """Registra un segnale. Ritorna l'id della riga."""
        if price <= 0 or sl <= 0 or tp <= 0:
            return -1
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db) as conn:
            cur = conn.execute(
                """INSERT INTO signal_log
                   (timestamp, strategy, direction, price, sl, tp, regime, executed, block_reason)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ts, strategy, direction, price, sl, tp, regime,
                 1 if executed else 0, block_reason),
            )
            conn.commit()
            return cur.lastrowid

    def update_outcome(
        self,
        row_id: int,
        outcome: str,
        exit_price: float,
        pnl_r: float,
    ):
        """Aggiorna l'esito di un segnale bloccato (WIN/LOSS/EXPIRED)."""
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self._db) as conn:
            conn.execute(
                """UPDATE signal_log
                   SET outcome=?, exit_price=?, pnl_r=?, checked_at=?
                   WHERE id=?""",
                (outcome, exit_price, pnl_r, ts, row_id),
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    # Read
    # ------------------------------------------------------------------ #

    def get_pending(self, max_age_hours: int = 24) -> List[Dict]:
        """Segnali bloccati senza esito ancora — da controllare."""
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM signal_log
                   WHERE executed = 0
                     AND outcome IS NULL
                     AND timestamp >= datetime('now', ?)
                   ORDER BY timestamp ASC""",
                (f"-{max_age_hours} hours",),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> Dict:
        """Statistiche aggregate per analisi settimanale."""
        with sqlite3.connect(self._db) as conn:
            conn.row_factory = sqlite3.Row

            # Per strategia e tipo (eseguito/bloccato)
            rows = conn.execute(
                """SELECT
                       strategy,
                       executed,
                       block_reason,
                       COUNT(*)                                          AS n,
                       AVG(pnl_r)                                       AS avg_pnl_r,
                       SUM(CASE WHEN outcome='WIN'  THEN 1 ELSE 0 END)  AS wins,
                       SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END)  AS losses
                   FROM signal_log
                   WHERE timestamp >= datetime('now', '-30 days')
                   GROUP BY strategy, executed, block_reason
                   ORDER BY strategy, executed DESC"""
            ).fetchall()
            return {"by_strategy": [dict(r) for r in rows]}

    def print_report(self):
        """Stampa report leggibile a console."""
        stats = self.get_stats()
        rows = stats["by_strategy"]
        if not rows:
            print("[SignalLog] Nessun dato ancora.")
            return

        print("\n" + "=" * 72)
        print("SIGNAL LOG REPORT — ultimi 30 giorni")
        print("=" * 72)
        print(f"{'Strategia':<22} {'Tipo':<10} {'Motivo':<28} {'N':>5} {'WR%':>6} {'E(R)':>7}")
        print("-" * 72)
        for r in rows:
            tipo = "ESEGUITO" if r["executed"] else "BLOCCATO"
            motivo = r["block_reason"] or "-"
            n = r["n"]
            wins = r["wins"] or 0
            losses = r["losses"] or 0
            wr = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            er = r["avg_pnl_r"] if r["avg_pnl_r"] is not None else 0
            print(f"{r['strategy']:<22} {tipo:<10} {motivo:<28} {n:>5} {wr:>5.1f}% {er:>+7.3f}R")
        print("=" * 72)
