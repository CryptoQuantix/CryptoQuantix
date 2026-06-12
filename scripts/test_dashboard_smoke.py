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

    at.sidebar.radio[0].set_value("Impostazioni")
    at.run(timeout=120)
    assert not at.exception, f"Pagina impostazioni: eccezione {at.exception}"
    n_widgets = len(at.slider) + len(at.toggle) + len(at.selectbox)
    assert n_widgets > 20, f"widget settings mancanti: {n_widgets}"
    print(f"[OK] pagina 'Impostazioni': {n_widgets} widget, nessuna eccezione")

    at.sidebar.radio[0].set_value("Azioni")
    at.run(timeout=120)
    assert not at.exception, f"Pagina azioni: eccezione {at.exception}"
    print("[OK] pagina 'Azioni' renderizzata senza eccezioni")


def test_env_editor_acceptance():
    """Accettazione Fase 3: modifica di un flag -> .env aggiornato e VALIDO
    (Config.load_strategies non solleva), backup creato, commenti intatti.
    Lavora sul .env reale ma ripristina lo stato esatto a fine test."""
    import shutil
    from src.monitoring.dashboard_app import env_editor

    before = env_editor.parse_env()
    old_level = before.get("LOG_LEVEL", "INFO")
    new_level = "DEBUG" if old_level != "DEBUG" else "WARNING"

    ok, msg, backup = env_editor.apply_changes_safely({"LOG_LEVEL": new_level})
    try:
        assert ok, f"apply_changes_safely fallita: {msg}"
        assert backup and os.path.exists(backup), "backup non creato"
        after = env_editor.parse_env()
        assert after["LOG_LEVEL"] == new_level, "valore non aggiornato"
        # i commenti inline devono sopravvivere alla scrittura chirurgica
        with open(env_editor.ENV_PATH, encoding="utf-8") as f:
            content = f.read()
        assert "STRATEGIE ATTIVE" in content, "struttura/commenti persi"
        print(f"[OK] env editor: LOG_LEVEL {old_level} -> {new_level}, "
              f"validato in subprocess, backup {os.path.basename(backup)}")
    finally:
        if backup and os.path.exists(backup):
            shutil.copy2(backup, env_editor.ENV_PATH)
            os.remove(backup)
    assert env_editor.parse_env().get("LOG_LEVEL") == old_level
    print("[OK] env editor: stato originale ripristinato")


def test_env_editor_rejects_invalid():
    """Un valore che rompe la validazione deve causare RIPRISTINO automatico.
    Rete di sicurezza nel finally: se l'editor regredisce, il test NON deve
    lasciare il .env reale corrotto."""
    import shutil
    from src.monitoring.dashboard_app import env_editor

    before = env_editor.parse_env()
    safety_copy = env_editor.make_backup()
    backup = None
    try:
        ok, msg, backup = env_editor.apply_changes_safely(
            {"DERIBIT_ENV": "ambiente_inesistente"})
        assert not ok, "valore invalido accettato!"
        assert env_editor.parse_env().get("DERIBIT_ENV") == before.get("DERIBIT_ENV"), \
            ".env non ripristinato dopo validazione fallita"
        print(f"[OK] env editor: valore invalido respinto e ripristinato ({msg[:60]}...)")
    finally:
        if env_editor.parse_env().get("DERIBIT_ENV") != before.get("DERIBIT_ENV"):
            shutil.copy2(safety_copy, env_editor.ENV_PATH)
            print("[WARN] .env ripristinato dalla rete di sicurezza del test")
        for f in (safety_copy, backup):
            if f and os.path.exists(f):
                os.remove(f)


def test_kill_switch_flag():
    """Accettazione Fase 4: la flag kill switch e' onorata dal RiskManager."""
    from src.core import flags
    from src.core.risk_manager import RiskManager

    rm = RiskManager(client=None, position_monitor=None, initial_equity=10000)
    flags.clear_flag(flags.KILL_SWITCH_FLAG)
    assert rm.is_kill_switch_active() is False
    flags.set_flag(flags.KILL_SWITCH_FLAG, reason="smoke test")
    try:
        assert rm.is_kill_switch_active() is True, "flag NON onorata"
        can, why = rm.can_open_new_position()
        assert can is False and "Kill switch" in why
    finally:
        flags.clear_flag(flags.KILL_SWITCH_FLAG)
    assert rm.is_kill_switch_active() is False
    print("[OK] kill switch flag: RiskManager blocca e sblocca correttamente")


def test_audit_log():
    """Accettazione Fase 4: ogni azione scrive chi/cosa/quando."""
    from src.monitoring.dashboard_app.audit import audit, read_audit
    audit("smoke_test", {"k": "v"}, "ok")
    entries = read_audit(5)
    assert entries and entries[0]["action"] == "smoke_test"
    assert entries[0]["user"] and entries[0]["ts_utc"]
    print("[OK] audit log: scrittura e rilettura chi/cosa/quando")


if __name__ == "__main__":
    seed_test_journal()
    run_apptest()
    test_env_editor_acceptance()
    test_env_editor_rejects_invalid()
    test_kill_switch_flag()
    test_audit_log()
    print("[OK] smoke test dashboard PASSED")
