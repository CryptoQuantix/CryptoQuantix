"""
TradeLogger — records complete trade context for analysis and ML.

At trade entry, captures:
  - Trade metadata (instrument, direction, size, prices)
  - Market regime at entry
  - Full orderflow snapshot (CVD, delta, imbalance, OI, etc.)
  - Strategy signal details
  - Risk metrics (equity, daily loss, position sizing)

At trade exit, adds:
  - Exit price, reason, P&L, R-multiple
  - Market state at exit

Storage: SQLite (default) + JSON export for ML datasets.
"""
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeSnapshot:
    """Complete snapshot of a trade (entry + exit data)."""
    # --- Identity ---
    trade_id: str
    strategy: str
    instrument: str
    direction: str          # "buy" or "sell"

    # --- Prices ---
    entry_price: float
    sl_price: float
    tp_price: float
    exit_price: float = 0.0
    quantity: float = 0.0

    # --- Timing ---
    entry_time: str = ""
    exit_time: str = ""
    duration_minutes: float = 0.0

    # --- Outcome ---
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    exit_reason: str = ""    # "tp", "sl", "manual", "time"
    win: bool = False

    # --- Market context at entry ---
    regime: str = "UNKNOWN"
    regime_confidence: float = 0.0

    # --- Orderflow at entry ---
    cvd_1m: float = 0.0
    cvd_5m: float = 0.0
    cvd_15m: float = 0.0
    book_imbalance: float = 0.5
    aggression_ratio: float = 0.5
    volume_zscore: float = 0.0
    vwap_z: float = 0.0
    oi_change_pct: float = 0.0
    kyle_lambda: float = 0.0
    is_absorption: bool = False
    liq_vacuum: bool = False

    # --- Risk metrics ---
    equity_at_entry: float = 0.0
    risk_pct: float = 0.0
    daily_pnl_before: float = 0.0

    # --- Signal metadata ---
    signal_data: str = "{}"   # JSON string of full signal dict

    # --- Status ---
    status: str = "open"    # "open" or "closed"


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    strategy TEXT,
    instrument TEXT,
    direction TEXT,
    entry_price REAL,
    sl_price REAL,
    tp_price REAL,
    exit_price REAL,
    quantity REAL,
    entry_time TEXT,
    exit_time TEXT,
    duration_minutes REAL,
    pnl_usd REAL,
    r_multiple REAL,
    exit_reason TEXT,
    win INTEGER,
    regime TEXT,
    regime_confidence REAL,
    cvd_1m REAL,
    cvd_5m REAL,
    cvd_15m REAL,
    book_imbalance REAL,
    aggression_ratio REAL,
    volume_zscore REAL,
    vwap_z REAL,
    oi_change_pct REAL,
    kyle_lambda REAL,
    is_absorption INTEGER,
    liq_vacuum INTEGER,
    equity_at_entry REAL,
    risk_pct REAL,
    daily_pnl_before REAL,
    signal_data TEXT,
    status TEXT
)
"""


class TradeLogger:
    """
    Persistent trade journal with full context snapshots.

    Usage:
        logger_obj = TradeLogger()
        # On entry:
        trade_id = logger_obj.log_entry(snapshot)
        # On exit:
        logger_obj.log_exit(trade_id, exit_price=50500, pnl=125.0, reason="tp")
    """

    def __init__(
        self,
        db_path: str = "data/journal.db",
        export_path: str = "data/journal_export.json",
        position_log_path: str = "logs/positions.log",
    ):
        self.db_path = db_path
        self.export_path = export_path
        self._conn: Optional[sqlite3.Connection] = None
        self._open_trades: Dict[str, TradeSnapshot] = {}
        self._init_db()

        # Human-readable position log
        try:
            from src.monitoring.position_log import PositionLog
            self._position_log = PositionLog(position_log_path)
        except Exception as e:
            logger.warning(f"[TradeLogger] PositionLog not available: {e}")
            self._position_log = None

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute(CREATE_TABLE_SQL)
            self._conn.commit()

            # Load open trades back into memory
            cursor = self._conn.execute(
                "SELECT * FROM trades WHERE status = 'open'"
            )
            cols = [d[0] for d in cursor.description]
            for row in cursor.fetchall():
                snap = TradeSnapshot(**{
                    k: (bool(v) if k in ("win", "is_absorption", "liq_vacuum") else v)
                    for k, v in zip(cols, row)
                })
                self._open_trades[snap.trade_id] = snap

            logger.info(
                f"[TradeLogger] DB initialized at {self.db_path} | "
                f"{len(self._open_trades)} open trades restored"
            )
        except Exception as e:
            logger.error(f"[TradeLogger] DB init error: {e}")

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log_entry(self, snapshot: TradeSnapshot) -> str:
        """
        Log a trade entry.

        Args:
            snapshot: TradeSnapshot with entry data filled in

        Returns:
            trade_id
        """
        snapshot.entry_time = snapshot.entry_time or datetime.now(timezone.utc).isoformat()
        snapshot.status = "open"

        self._open_trades[snapshot.trade_id] = snapshot
        self._upsert(snapshot)

        logger.info(
            f"[Journal] ENTRY: {snapshot.instrument} {snapshot.direction.upper()} "
            f"@ {snapshot.entry_price:.2f} | "
            f"regime={snapshot.regime} | strategy={snapshot.strategy}"
        )

        if self._position_log:
            self._position_log.log_open(snapshot, equity_before=snapshot.equity_at_entry)

        return snapshot.trade_id

    def log_exit(
        self,
        trade_id: str,
        exit_price: float,
        pnl_usd: float,
        exit_reason: str = "unknown",
    ):
        """Update a trade with exit data."""
        snap = self._open_trades.get(trade_id)
        if not snap:
            # Try to load from DB
            snap = self._load_trade(trade_id)
        if not snap:
            logger.warning(f"[Journal] trade_id {trade_id} not found")
            return

        snap.exit_price = exit_price
        snap.pnl_usd = pnl_usd
        snap.exit_reason = exit_reason
        snap.win = pnl_usd > 0
        snap.exit_time = datetime.now(timezone.utc).isoformat()
        snap.status = "closed"

        # Compute duration
        try:
            from datetime import datetime as dt
            entry_dt = dt.fromisoformat(snap.entry_time)
            exit_dt = dt.fromisoformat(snap.exit_time)
            snap.duration_minutes = (exit_dt - entry_dt).total_seconds() / 60
        except Exception:
            pass

        # Compute R-multiple
        risk = abs(snap.entry_price - snap.sl_price)
        if risk > 0 and snap.quantity > 0:
            snap.r_multiple = (pnl_usd / snap.quantity) / risk
        else:
            snap.r_multiple = 0.0

        self._upsert(snap)
        self._open_trades.pop(trade_id, None)

        logger.info(
            f"[Journal] EXIT: {snap.instrument} {snap.direction.upper()} "
            f"@ {exit_price:.2f} | P&L=${pnl_usd:+,.2f} R={snap.r_multiple:+.2f} | "
            f"reason={exit_reason}"
        )

        if self._position_log:
            equity_after = snap.equity_at_entry + snap.pnl_usd
            self._position_log.log_close(snap, equity_after=equity_after)

    def log_entry_from_signal(
        self,
        trade_id: str,
        signal: Dict[str, Any],
        quantity: float,
        orderflow_snap=None,
        regime=None,
        equity: float = 0.0,
        daily_pnl: float = 0.0,
    ) -> TradeSnapshot:
        """
        Convenience method: build TradeSnapshot from signal dict + context.
        """
        regime_str = "UNKNOWN"
        regime_conf = 0.0
        if regime:
            regime_str = getattr(regime, "regime", regime) if hasattr(regime, "regime") else str(regime)
            if hasattr(regime_str, "value"):
                regime_str = regime_str.value
            regime_conf = getattr(regime, "confidence", 0.0)

        snap = TradeSnapshot(
            trade_id=trade_id,
            strategy=signal.get("strategy", ""),
            instrument=signal.get("instrument", ""),
            direction=signal.get("direction", "buy").lower(),
            entry_price=signal.get("price", 0.0),
            sl_price=signal.get("stop_loss", 0.0),
            tp_price=signal.get("take_profit", 0.0),
            quantity=quantity,
            regime=regime_str,
            regime_confidence=regime_conf,
            equity_at_entry=equity,
            daily_pnl_before=daily_pnl,
            signal_data=json.dumps(signal, default=str),
        )

        if orderflow_snap:
            snap.cvd_1m = getattr(orderflow_snap, "cvd_1m", 0.0)
            snap.cvd_5m = getattr(orderflow_snap, "cvd_5m", 0.0)
            snap.cvd_15m = getattr(orderflow_snap, "cvd_15m", 0.0)
            snap.book_imbalance = getattr(orderflow_snap, "book_imbalance", 0.5)
            snap.aggression_ratio = getattr(orderflow_snap, "aggression_ratio", 0.5)
            snap.volume_zscore = getattr(orderflow_snap, "volume_zscore", 0.0)
            snap.vwap_z = getattr(orderflow_snap, "vwap_z", 0.0)
            snap.oi_change_pct = getattr(orderflow_snap, "oi_change_pct", 0.0)
            snap.kyle_lambda = getattr(orderflow_snap, "kyle_lambda", 0.0)
            snap.is_absorption = getattr(orderflow_snap, "is_absorption", False)
            snap.liq_vacuum = getattr(orderflow_snap, "is_liq_vacuum", False)

        self.log_entry(snap)
        return snap

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent_trades(self, n: int = 50, status: str = None) -> List[Dict]:
        """Get N most recent trades as list of dicts."""
        try:
            query = "SELECT * FROM trades"
            params = []
            if status:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY entry_time DESC LIMIT ?"
            params.append(n)
            cursor = self._conn.execute(query, params)
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[Journal] Query error: {e}")
            return []

    def get_open_trades(self) -> Dict[str, TradeSnapshot]:
        return dict(self._open_trades)

    def get_trade(self, trade_id: str) -> Optional[TradeSnapshot]:
        return self._open_trades.get(trade_id) or self._load_trade(trade_id)

    def export_to_json(self) -> str:
        """Export all trades to JSON file for ML dataset creation."""
        trades = self.get_recent_trades(n=10000)
        os.makedirs(os.path.dirname(self.export_path) or ".", exist_ok=True)
        with open(self.export_path, "w") as f:
            json.dump(trades, f, indent=2, default=str)
        logger.info(f"[Journal] Exported {len(trades)} trades to {self.export_path}")
        return self.export_path

    def get_stats(self) -> Dict:
        """Get overall statistics."""
        try:
            cursor = self._conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) as wins,
                    SUM(pnl_usd) as total_pnl,
                    AVG(r_multiple) as avg_r,
                    AVG(duration_minutes) as avg_duration
                FROM trades WHERE status = 'closed'
            """)
            row = cursor.fetchone()
            if row:
                total, wins, pnl, avg_r, avg_dur = row
                total = total or 0
                wins = wins or 0
                return {
                    "total_closed": total,
                    "wins": wins,
                    "losses": total - wins,
                    "winrate": wins / total if total > 0 else 0.0,
                    "total_pnl": pnl or 0.0,
                    "avg_r_multiple": avg_r or 0.0,
                    "avg_duration_min": avg_dur or 0.0,
                    "open_trades": len(self._open_trades),
                }
        except Exception as e:
            logger.error(f"[Journal] Stats error: {e}")
        return {}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _upsert(self, snap: TradeSnapshot):
        """Insert or update trade in DB."""
        if not self._conn:
            return
        try:
            d = asdict(snap)
            d["win"] = int(d["win"])
            d["is_absorption"] = int(d["is_absorption"])
            d["liq_vacuum"] = int(d["liq_vacuum"])
            cols = list(d.keys())
            placeholders = ",".join(["?"] * len(cols))
            updates = ",".join([f"{c}=excluded.{c}" for c in cols if c != "trade_id"])
            sql = (
                f"INSERT INTO trades ({','.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(trade_id) DO UPDATE SET {updates}"
            )
            self._conn.execute(sql, list(d.values()))
            self._conn.commit()
        except Exception as e:
            logger.error(f"[Journal] Upsert error: {e}")

    def _load_trade(self, trade_id: str) -> Optional[TradeSnapshot]:
        try:
            cursor = self._conn.execute(
                "SELECT * FROM trades WHERE trade_id = ?", [trade_id]
            )
            row = cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                return TradeSnapshot(**{
                    k: (bool(v) if k in ("win", "is_absorption", "liq_vacuum") else v)
                    for k, v in zip(cols, row)
                })
        except Exception:
            pass
        return None

    def close(self):
        if self._conn:
            self._conn.close()
