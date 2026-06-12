"""
Smoke test dashboard: semina un journal di TEST con trade sintetici
(usando TradeLogger, cosi' lo schema e' identico a quello del bot) e
renderizza entrambe le pagine con streamlit.testing.AppTest.

Uso:  python scripts/test_dashboard_smoke.py
NB: non tocca data/journal.db reale (usa data/journal_test.db).
"""
import os
import random
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

TEST_DB = "data/journal_test.db"
# La dashboard legge JOURNAL_DB_PATH all'import: impostarlo PRIMA di AppTest
os.environ["JOURNAL_DB_PATH"] = TEST_DB


def seed_test_journal():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    from src.journal.trade_logger import TradeLogger, TradeSnapshot

    tl = TradeLogger(
        db_path=TEST_DB,
        export_path="data/journal_test_export.json",
        position_log_path="logs/positions_test.log",
    )
    rng = random.Random(42)
    strategies = [
        ("TrendBreakdown", "BTC-PERPETUAL", "sell"),
        ("TrendBreakdown", "ETH-PERPETUAL", "buy"),
        ("FundingSqueeze", "BTC-PERPETUAL", "sell"),
        ("MacroCore", "BTC-PERPETUAL", "buy"),
    ]
    t0 = datetime.now(timezone.utc) - timedelta(days=30)
    for i in range(24):
        strat, instr, direction = strategies[i % len(strategies)]
        entry_px = 65000.0 if "BTC" in instr else 3200.0
        entry_px *= 1 + rng.uniform(-0.05, 0.05)
        sl = entry_px * (0.98 if direction == "buy" else 1.02)
        tp = entry_px * (1.04 if direction == "buy" else 0.96)
        qty = rng.choice([200.0, 500.0, 1000.0])
        entry_time = t0 + timedelta(days=i, hours=rng.randint(0, 20))
        snap = TradeSnapshot(
            trade_id=f"test_{i:03d}",
            strategy=strat, instrument=instr, direction=direction,
            entry_price=entry_px, sl_price=sl, tp_price=tp, quantity=qty,
            entry_time=entry_time.isoformat(),
            regime="TREND_DOWN", equity_at_entry=10000.0, risk_pct=0.01,
        )
        tl.log_entry(snap)
        win = rng.random() < 0.55
        if direction == "buy":
            exit_px = tp if win else sl
        else:
            exit_px = tp if win else sl
        pnl = qty * (exit_px - entry_px) / entry_px
        if direction == "sell":
            pnl = -pnl
        tl.log_exit(f"test_{i:03d}", exit_price=exit_px, pnl_usd=pnl,
                    exit_reason="tp" if win else "sl")
    # 1 trade lasciato APERTO per la vista journal della pagina live
    tl.log_entry(TradeSnapshot(
        trade_id="test_open", strategy="MacroCore", instrument="BTC-PERPETUAL",
        direction="buy", entry_price=64000.0, sl_price=60000.0, tp_price=0.0,
        quantity=800.0, entry_time=datetime.now(timezone.utc).isoformat(),
        equity_at_entry=10000.0,
    ))
    tl.close()
    print(f"[OK] seed: 24 chiusi + 1 aperto in {TEST_DB}")


def run_apptest():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file("scripts/run_dashboard.py", default_timeout=120)
    at.run()
    assert not at.exception, f"Pagina live: eccezione {at.exception}"
    print("[OK] pagina 'Trade in corso' renderizzata senza eccezioni")
    errors = [e.value for e in at.error]
    if errors:
        print(f"     (st.error mostrati, attesi senza venue/chiavi: {errors})")

    at.sidebar.radio[0].set_value("Rischio & Esposizione")
    at.run()
    assert not at.exception, f"Pagina rischio: eccezione {at.exception}"
    print(f"[OK] pagina 'Rischio & Esposizione': {len(at.metric)} metriche, "
          f"{len(at.dataframe)} tabelle, nessuna eccezione")

    at.sidebar.radio[0].set_value("Storico Operazioni")
    at.run()
    assert not at.exception, f"Pagina storico: eccezione {at.exception}"
    # Verifica che i numeri aggregati siano renderizzati
    metrics = [m.label for m in at.metric]
    assert any("P&L" in m for m in metrics), f"metriche mancanti: {metrics}"
    assert len(at.dataframe) >= 1, "tabella storico mancante"
    print(f"[OK] pagina 'Storico Operazioni': {len(at.metric)} metriche, "
          f"{len(at.dataframe)} tabelle, nessuna eccezione")


if __name__ == "__main__":
    seed_test_journal()
    run_apptest()
    print("[OK] smoke test dashboard PASSED")
