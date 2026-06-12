"""
Editor sicuro del file .env (Fase 3).

Garanzie:
  - backup automatico .env.bak.<timestamp> PRIMA di ogni scrittura
  - modifica SOLO le righe delle chiavi cambiate: commenti, ordine e
    struttura del file restano intatti
  - validazione post-scrittura in un SUBPROCESS pulito
    (load_dotenv + Config.load_strategies + Config.validate): se fallisce,
    il file viene RIPRISTINATO dal backup automaticamente
  - i secrets non passano mai di qui (la pagina non li espone né li scrive)
"""
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ENV_PATH = ".env"


def _backup_dir(path: str) -> str:
    """Cartella dei backup: ENV_BACKUP_DIR se impostata (in Docker punta a
    data/env_backups, bind-mounted -> sopravvive al container), altrimenti
    accanto al .env come da piano originale."""
    return os.getenv("ENV_BACKUP_DIR", "") or (os.path.dirname(path) or ".")

# Riga "KEY=value" con eventuale commento inline (# preceduto da spazi)
_LINE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>[^#]*?)(?P<comment>\s+#.*)?$")


def parse_env(path: str = ENV_PATH) -> Dict[str, str]:
    """Valori correnti dal file (raw, senza interpolazioni)."""
    values: Dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _LINE_RE.match(line.strip())
            if m:
                values[m.group("key")] = m.group("value").strip()
    return values


def make_backup(path: str = ENV_PATH) -> str:
    """Copia .env -> <backup_dir>/.env.bak.YYYYMMDD_HHMMSS. Ritorna il path."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = _backup_dir(path)
    os.makedirs(d, exist_ok=True)
    backup_path = os.path.join(d, f"{os.path.basename(path)}.bak.{ts}")
    shutil.copy2(path, backup_path)
    return backup_path


def list_backups(path: str = ENV_PATH) -> List[str]:
    base = os.path.basename(path) + ".bak."
    d = _backup_dir(path)
    if not os.path.isdir(d):
        return []
    return sorted(
        (os.path.join(d, f) for f in os.listdir(d) if f.startswith(base)),
        reverse=True,
    )


def write_env_changes(changes: Dict[str, str], path: str = ENV_PATH) -> List[str]:
    """
    Applica le modifiche riga per riga preservando commenti e struttura.
    Ritorna le chiavi NON trovate nel file (non vengono aggiunte: tutte le
    chiavi editabili esistono gia' nel .env riordinato).
    """
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    pending = dict(changes)
    out_lines = []
    for line in lines:
        m = _LINE_RE.match(line.strip())
        if m and m.group("key") in pending:
            key = m.group("key")
            comment = m.group("comment") or ""
            newline = "\n" if line.endswith("\n") else ""
            out_lines.append(f"{key}={pending.pop(key)}{comment}{newline}")
        else:
            out_lines.append(line)

    # NB: scrittura IN PLACE (open 'w', stesso inode) e mai os.replace:
    # in Docker il .env e' un bind mount di SINGOLO FILE e sostituire
    # l'inode romperebbe il mount. Non "ottimizzare" in atomic-replace.
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.writelines(out_lines)
    return list(pending.keys())


def validate_env(path: str = ENV_PATH, timeout_sec: int = 60) -> Tuple[bool, str]:
    """
    Valida il .env in un subprocess pulito (il processo dashboard ha gia'
    os.environ popolato: solo un processo nuovo legge davvero il file).
    Criterio di accettazione Fase 3: Config.load_strategies() non solleva
    e Config.validate() passa.
    """
    # override=True: il FILE e' autoritativo (il subprocess eredita
    # os.environ del processo dashboard, che ha gia' i vecchi valori)
    code = (
        "from dotenv import load_dotenv; load_dotenv(override=True); "
        "from config import Config; Config.load_strategies(); "
        "import sys; sys.exit(0 if Config.validate() else 1)"
    )
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"  # validate() stampa simboli unicode
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.abspath(os.path.dirname(path) or "."),
            capture_output=True, timeout=timeout_sec, env=env,
            # il figlio emette UTF-8 (PYTHONIOENCODING): decodifica coerente
            encoding="utf-8", errors="replace",
        )
        ok = proc.returncode == 0
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return ok, output
    except Exception as e:
        return False, f"validazione non eseguibile: {e}"


def apply_changes_safely(
    changes: Dict[str, str], path: str = ENV_PATH
) -> Tuple[bool, str, Optional[str]]:
    """
    backup -> scrittura -> validazione; ripristino automatico se invalida.

    Returns:
        (ok, messaggio, backup_path)
    """
    if not changes:
        return False, "nessuna modifica da applicare", None
    if not os.path.exists(path):
        return False, f"{path} non trovato", None

    backup_path = make_backup(path)
    missing = write_env_changes(changes, path)
    if missing:
        shutil.copy2(backup_path, path)
        return False, f"chiavi non presenti nel .env: {missing} — ripristinato", backup_path

    ok, output = validate_env(path)
    if not ok:
        shutil.copy2(backup_path, path)
        return False, (
            f"validazione FALLITA — .env ripristinato dal backup. Dettaglio: "
            f"{output[:500]}"
        ), backup_path

    return True, f"{len(changes)} chiavi aggiornate e validate", backup_path
