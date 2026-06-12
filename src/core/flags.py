"""
Flag file condivisi tra bot e dashboard (Fasi 3-4 piano dashboard).

La dashboard e' un processo separato che NON chiama mai il bot: ogni
comando passa da un file in data/flags/ che il bot rilegge nei suoi loop.

  - KILL_SWITCH_FLAG    : se presente, RiskManager.is_kill_switch_active()
                          ritorna True -> nessun nuovo ingresso (le posizioni
                          aperte restano gestite normalmente)
  - RESTART_REQUEST_FLAG: il management loop del bot la onora con uno
                          shutdown pulito (il supervisor esterno riavvia)
"""
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

FLAGS_DIR = "data/flags"
KILL_SWITCH_FLAG = os.path.join(FLAGS_DIR, "kill_switch_manual.flag")
RESTART_REQUEST_FLAG = os.path.join(FLAGS_DIR, "restart_request.flag")


def set_flag(path: str, reason: str = "", source: str = "dashboard") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "reason": reason,
        }, f, indent=2)


def clear_flag(path: str) -> bool:
    """Rimuove la flag. True se esisteva."""
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def flag_active(path: str) -> bool:
    return os.path.exists(path)


def flag_info(path: str) -> Optional[Dict[str, Any]]:
    """Contenuto della flag (chi/quando/perche'), None se assente."""
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception:
        return {"created_utc": "?", "source": "?", "reason": "(illeggibile)"}
    return None
