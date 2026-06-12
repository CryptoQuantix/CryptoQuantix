"""
PositioningCollector — archivio storico dei dati di POSIZIONAMENTO Binance
che l'exchange espone solo per gli ultimi ~30 giorni.

Perche' esiste (candidato C8 "positioning extremes", vedi
microevolutive/C8_POSITIONING_EXTREMES.md):
  Top Trader Long/Short Ratio, Open Interest storico e Taker Buy/Sell Ratio
  sono segnali di crowding concettualmente adiacenti a FundingSqueeze, ma
  gli endpoint `futures/data/*` di Binance ritornano SOLO ~30 giorni di
  storia: oggi NON sono validabili con la pipeline multi-ciclo. Questo
  modulo li archivia in SQLite a partire dal 2026-06-12 cosi' che fra
  12+ mesi esista una serie proprietaria su cui fare ricerca.

Garanzie:
  - non tocca MAI il trading: ogni errore e' un warning, mai un raise
  - idempotente: INSERT OR REPLACE su (symbol, metric, ts_ms) — run
    sovrapposti (bot ogni 12h + cron di ridondanza) non duplicano
  - schema-proof: oltre al valore headline salva il record raw JSON

Uso:
    collector = PositioningCollector()
    stats = collector.collect_once()    # {metric/symbol: nuove righe}
    info = collector.status()           # copertura per metrica
Script standalone (cron/Task Scheduler): scripts/collect_positioning.py
"""
import json
import logging
import os
import sqlite3
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

from src.data.kline_provider import _build_ssl_context

logger = logging.getLogger(__name__)

BINANCE_FAPI = "https://fapi.binance.com"
DEFAULT_DB = "data/positioning_history.db"

# metric -> (endpoint path, campo valore headline, campo timestamp)
# Tutti endpoint PUBBLICI (nessuna chiave API richiesta).
METRICS: Dict[str, Tuple[str, str, str]] = {
    # ratio long/short degli account top trader (per numero di account)
    "top_ls_accounts": ("/futures/data/topLongShortAccountRatio",
                        "longShortRatio", "timestamp"),
    # ratio long/short dei top trader per SIZE delle posizioni (piu' "smart")
    "top_ls_positions": ("/futures/data/topLongShortPositionRatio",
                         "longShortRatio", "timestamp"),
    # ratio long/short di TUTTI gli account (retail incluso)
    "global_ls_accounts": ("/futures/data/globalLongShortAccountRatio",
                           "longShortRatio", "timestamp"),
    # open interest storico (nozionale USD)
    "open_interest": ("/futures/data/openInterestHist",
                      "sumOpenInterestValue", "timestamp"),
    # taker buy/sell volume ratio (proxy CVD aggregato)
    "taker_ratio": ("/futures/data/takerlongshortRatio",
                    "buySellRatio", "timestamp"),
}

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS positioning (
    symbol TEXT NOT NULL,
    metric TEXT NOT NULL,
    ts_ms  INTEGER NOT NULL,
    value  REAL,
    raw    TEXT,
    PRIMARY KEY (symbol, metric, ts_ms)
)
"""


class PositioningCollector:
    """Colleziona e archivia le serie di posizionamento Binance."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB,
        symbols: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
        period: str = "1h",
        limit: int = 500,
        timeout_sec: float = 15.0,
    ):
        """
        Args:
            period: granularita' (1h = 500 punti ~ 20.8 giorni per run;
                    con run ogni 12h l'overlap garantisce continuita')
            limit:  max 500 per gli endpoint futures/data
        """
        self.db_path = db_path
        self.symbols = symbols
        self.period = period
        self.limit = limit
        self.timeout_sec = timeout_sec
        self._ssl_ctx = _build_ssl_context()
        self._init_db()

    # ------------------------------------------------------------------

    def _init_db(self):
        try:
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(CREATE_SQL)
        except Exception as e:
            logger.error(f"[Positioning] init DB fallita: {e}")

    def _fetch_json(self, url: str) -> Optional[list]:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_sec,
                                        context=self._ssl_ctx) as resp:
                return json.loads(resp.read())
        except Exception as ex:
            # proxy aziendali / chain-verification: degrada una volta a
            # contesto non verificato (solo dati di mercato pubblici),
            # stesso comportamento di BinanceKlineProvider
            if "CERTIFICATE" in str(ex).upper() or "SSL" in str(ex).upper():
                import ssl
                self._ssl_ctx = ssl.create_default_context()
                self._ssl_ctx.check_hostname = False
                self._ssl_ctx.verify_mode = ssl.CERT_NONE
                try:
                    with urllib.request.urlopen(url, timeout=self.timeout_sec,
                                                context=self._ssl_ctx) as resp:
                        return json.loads(resp.read())
                except Exception as ex2:
                    logger.warning(f"[Positioning] fetch fallita (post fallback SSL) {url}: {ex2}")
                    return None
            logger.warning(f"[Positioning] fetch fallita {url}: {ex}")
            return None

    # ------------------------------------------------------------------

    def collect_once(self) -> Dict[str, int]:
        """Una passata su tutte le metriche/simboli. Ritorna nuove righe
        per chiave 'metric/symbol'. Non solleva mai."""
        stats: Dict[str, int] = {}
        try:
            conn = sqlite3.connect(self.db_path)
        except Exception as e:
            logger.error(f"[Positioning] DB non apribile: {e}")
            return stats

        try:
            for symbol in self.symbols:
                for metric, (path, value_field, ts_field) in METRICS.items():
                    url = (f"{BINANCE_FAPI}{path}?symbol={symbol}"
                           f"&period={self.period}&limit={self.limit}")
                    data = self._fetch_json(url)
                    if not data or not isinstance(data, list):
                        stats[f"{metric}/{symbol}"] = -1  # fetch fallita
                        continue
                    rows = []
                    for rec in data:
                        try:
                            rows.append((
                                symbol, metric, int(rec[ts_field]),
                                float(rec.get(value_field, 0) or 0),
                                json.dumps(rec, ensure_ascii=True),
                            ))
                        except Exception:
                            continue
                    before = conn.execute(
                        "SELECT COUNT(*) FROM positioning WHERE symbol=? AND metric=?",
                        (symbol, metric)).fetchone()[0]
                    conn.executemany(
                        "INSERT OR REPLACE INTO positioning "
                        "(symbol, metric, ts_ms, value, raw) VALUES (?,?,?,?,?)",
                        rows)
                    conn.commit()
                    after = conn.execute(
                        "SELECT COUNT(*) FROM positioning WHERE symbol=? AND metric=?",
                        (symbol, metric)).fetchone()[0]
                    stats[f"{metric}/{symbol}"] = after - before
                    time.sleep(0.2)  # rispetto rate limit
            logger.info(f"[Positioning] collect_once: {stats}")
        except Exception as e:
            logger.error(f"[Positioning] collect_once errore: {e}")
        finally:
            conn.close()
        return stats

    # ------------------------------------------------------------------

    def status(self) -> List[Dict]:
        """Copertura per (metric, symbol): righe, primo/ultimo timestamp,
        giorni coperti, staleness. Per il pannello dashboard e i check
        trimestrali di C8."""
        out: List[Dict] = []
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        except Exception:
            return out
        try:
            cur = conn.execute(
                "SELECT symbol, metric, COUNT(*), MIN(ts_ms), MAX(ts_ms) "
                "FROM positioning GROUP BY symbol, metric ORDER BY metric, symbol")
            now_ms = int(time.time() * 1000)
            for symbol, metric, n, ts_min, ts_max in cur.fetchall():
                out.append({
                    "metric": metric,
                    "symbol": symbol,
                    "rows": n,
                    "first_ts_ms": ts_min,
                    "last_ts_ms": ts_max,
                    "days_covered": round((ts_max - ts_min) / 86_400_000, 1),
                    "stale_hours": round((now_ms - ts_max) / 3_600_000, 1),
                })
        except Exception as e:
            logger.warning(f"[Positioning] status errore: {e}")
        finally:
            conn.close()
        return out

    def get_series(self, metric: str, symbol: str = "BTCUSDT",
                   last_n: int = 1000) -> List[Tuple[int, float]]:
        """Serie (ts_ms, value) per grafici/ricerca, dal piu' vecchio."""
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            cur = conn.execute(
                "SELECT ts_ms, value FROM ("
                "  SELECT ts_ms, value FROM positioning "
                "  WHERE metric=? AND symbol=? ORDER BY ts_ms DESC LIMIT ?"
                ") ORDER BY ts_ms ASC",
                (metric, symbol, last_n))
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception:
            return []
