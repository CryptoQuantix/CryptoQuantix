"""
Run manuale / cron del PositioningCollector (candidato C8).

Il bot async lo esegue gia' ogni 12h; questo script serve come:
  - primo backfill (cattura i ~30 giorni disponibili su Binance)
  - RIDONDANZA via Task Scheduler/cron: se il bot resta giu' piu' di
    ~20 giorni il buco dati diventa permanente — un job giornaliero
    indipendente lo previene (vedi C8_POSITIONING_EXTREMES.md)

Uso:
    python scripts/collect_positioning.py            # una passata
    python scripts/collect_positioning.py --status   # solo copertura
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import logging
logging.basicConfig(level=logging.INFO, format="%(message)s")

from src.data.positioning_collector import PositioningCollector


def main():
    collector = PositioningCollector()

    if "--status" not in sys.argv:
        print("[C8] Collecting positioning data (Binance futures/data)...")
        stats = collector.collect_once()
        for key, n in sorted(stats.items()):
            mark = "[FAIL]" if n < 0 else "[OK]"
            print(f"  {mark} {key}: {'fetch fallita' if n < 0 else f'+{n} righe nuove'}")

    print("\n[C8] Copertura archivio data/positioning_history.db:")
    status = collector.status()
    if not status:
        print("  (vuoto)")
        return
    for s in status:
        stale = " !!! STALE" if s["stale_hours"] > 48 else ""
        print(f"  {s['metric']:<20} {s['symbol']:<8} "
              f"{s['rows']:>6} righe | {s['days_covered']:>6.1f} giorni | "
              f"ultimo dato {s['stale_hours']:.0f}h fa{stale}")


if __name__ == "__main__":
    main()
