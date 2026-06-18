#!/usr/bin/env python3
"""
Corregge nel journal trade chiusi con P&L fantasma (exit_price = entry_price,
pnl_usd = 0) usando i fill reali da Deribit.

Caso tipico: falsa chiusura pre-fix del 2026-06-17 (TB SHORT BTC-PERPETUAL).

Uso:
    python scripts/patch_journal_phantom.py --dry-run
    python scripts/patch_journal_phantom.py
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

DB = os.getenv("JOURNAL_DB_PATH", "data/journal.db")


def _fetch_deribit_fills(instrument: str):
    from src.core.deribit_client import DeribitClient

    client = DeribitClient(
        os.environ["DERIBIT_API_KEY"],
        os.environ["DERIBIT_API_SECRET"],
        os.getenv("DERIBIT_ENV", "test"),
    )
    if not client.authenticate():
        raise RuntimeError("Autenticazione Deribit fallita")
    return client.get_user_trades_by_instrument(instrument, count=50, sorting="asc")


def _match_entry_exit(trades, direction: str):
    """Trova coppia entry + reduce-only close per la direzione del trade."""
    entry_dir = direction.lower()
    close_dir = "buy" if entry_dir == "sell" else "sell"
    entry_fill = None
    close_fill = None
    for t in trades:
        d = (t.get("direction") or "").lower()
        if entry_fill is None and d == entry_dir and not t.get("reduce_only"):
            entry_fill = t
            continue
        if entry_fill is not None and (t.get("reduce_only") or d == close_dir):
            close_fill = t
            break
    return entry_fill, close_fill


def _phantom_rows(conn):
    return conn.execute(
        """
        SELECT trade_id, instrument, direction, entry_price, exit_price,
               quantity, sl_price, tp_price, entry_time, exit_time
        FROM trades
        WHERE status = 'closed'
          AND ABS(pnl_usd) < 0.01
          AND ABS(exit_price - entry_price) < 1.0
        """
    ).fetchall()


def patch_phantoms(dry_run: bool = True) -> int:
    if not os.path.exists(DB):
        print(f"Journal assente: {DB}")
        return 0

    conn = sqlite3.connect(DB)
    rows = _phantom_rows(conn)
    if not rows:
        print("Nessun trade fantasma trovato (pnl≈0 e exit≈entry).")
        conn.close()
        return 0

    patched = 0
    for row in rows:
        trade_id, instrument, direction, ep, xp, qty, sl, tp, et, xt = row
        print(f"\n--- {trade_id} ({instrument} {direction}) ---")
        print(f"  journal: entry={ep} exit={xp} qty={qty}")

        try:
            trades = _fetch_deribit_fills(instrument)
        except Exception as e:
            print(f"  [SKIP] Deribit: {e}")
            continue

        entry_fill, close_fill = _match_entry_exit(trades, direction)
        if not entry_fill or not close_fill:
            print("  [SKIP] impossibile abbinare entry/exit su Deribit")
            continue

        entry_price = float(entry_fill["price"])
        exit_price = float(close_fill["price"])
        size_usd = float(entry_fill.get("amount", 0) or 0)
        if size_usd <= 0:
            size_usd = float(close_fill.get("amount", 0) or 0)
        qty_btc = size_usd / entry_price if entry_price > 0 else float(qty or 0)

        d = direction.lower()
        pnl = (exit_price - entry_price) * qty_btc if d == "buy" else (entry_price - exit_price) * qty_btc

        entry_ts = datetime.fromtimestamp(
            int(entry_fill["timestamp"]) / 1000, tz=timezone.utc
        ).isoformat()
        exit_ts = datetime.fromtimestamp(
            int(close_fill["timestamp"]) / 1000, tz=timezone.utc
        ).isoformat()
        duration = (
            datetime.fromisoformat(exit_ts) - datetime.fromisoformat(entry_ts)
        ).total_seconds() / 60

        risk = abs(entry_price - float(sl or 0))
        r_mult = (pnl / qty_btc) / risk if risk > 0 and qty_btc > 0 else 0.0
        sl_f, tp_f = float(sl or 0), float(tp or 0)
        if sl_f and tp_f:
            reason = "tp" if abs(exit_price - tp_f) < abs(exit_price - sl_f) else "sl"
        else:
            reason = "sl"

        print(f"  Deribit: entry={entry_price} exit={exit_price} size=${size_usd:,.0f}")
        print(f"  P&L=${pnl:+.2f}  durata={duration:.0f}min  reason={reason}")

        if dry_run:
            print("  [DRY-RUN] nessuna modifica")
            patched += 1
            continue

        conn.execute(
            """
            UPDATE trades SET
                entry_price = ?, exit_price = ?, quantity = ?,
                entry_time = ?, exit_time = ?, duration_minutes = ?,
                pnl_usd = ?, r_multiple = ?, exit_reason = ?, win = ?
            WHERE trade_id = ?
            """,
            (
                entry_price, exit_price, qty_btc,
                entry_ts, exit_ts, duration,
                pnl, r_mult, reason, 1 if pnl > 0 else 0,
                trade_id,
            ),
        )
        patched += 1
        print("  [OK] aggiornato")

    if not dry_run:
        conn.commit()
    conn.close()
    return patched


def main():
    parser = argparse.ArgumentParser(description="Corregge trade fantasma nel journal")
    parser.add_argument("--dry-run", action="store_true", help="solo anteprima")
    args = parser.parse_args()
    n = patch_phantoms(dry_run=args.dry_run)
    if args.dry_run and n:
        print("\nEsegui senza --dry-run per applicare le correzioni.")
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
