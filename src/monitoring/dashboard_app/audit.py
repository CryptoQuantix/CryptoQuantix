"""
Audit log delle azioni della dashboard (criterio di accettazione Fase 4:
ogni azione scrive chi/cosa/quando).

File: logs/dashboard_actions.log — una riga JSON per azione, append-only.
"""
import getpass
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = "logs/dashboard_actions.log"


def audit(action: str, details: Dict[str, Any], result: str) -> None:
    """Registra un'azione. Non solleva mai (l'audit non deve bloccare)."""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH) or ".", exist_ok=True)
        entry = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "user": getpass.getuser(),
            "action": action,
            "details": details,
            "result": result,
        }
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
    except Exception as e:
        logger.error(f"[Audit] scrittura fallita: {e}")


def read_audit(last_n: int = 50) -> List[Dict[str, Any]]:
    """Ultime N azioni, piu' recente per prima."""
    try:
        if not os.path.exists(AUDIT_LOG_PATH):
            return []
        with open(AUDIT_LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        out = []
        for line in reversed(lines[-last_n:]):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []
