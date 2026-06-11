"""
KlineProvider — closed higher-timeframe candles + funding rate from Binance REST.

Why this exists: OrderflowEngine's candle history holds at most ~8h of 1m
candles and ~25h of 15m candles, but trend strategies need 48h+ of 1h bars.
This provider fetches closed 1h klines (and current funding) via REST with a
short cache, and is INJECTABLE: backtests replace it with a historical-window
provider so the exact same strategy code runs live and in simulation.

API:
    provider = BinanceKlineProvider()
    candles = provider.get_klines("BTCUSDT", interval="1h", limit=60)
      -> list of dicts (oldest first), ONLY CLOSED bars:
         {ts_ms, open, high, low, close, volume, buy_volume, buy_ratio}
    rate = provider.get_funding_rate("BTCUSDT")   # current period rate
    now  = provider.now_ms()                       # data-driven clock
"""
import json
import logging
import ssl
import time
import urllib.request
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

BINANCE_FAPI = "https://fapi.binance.com"


def _build_ssl_context() -> ssl.SSLContext:
    """certifi bundle if available, else unverified (public market data only)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


class BinanceKlineProvider:
    """REST provider with per-(symbol, interval) cache."""

    def __init__(self, cache_ttl_sec: float = 55.0, timeout_sec: float = 10.0):
        self.cache_ttl_sec = cache_ttl_sec
        self.timeout_sec = timeout_sec
        self._ssl_ctx = _build_ssl_context()
        self._kline_cache: Dict[str, tuple] = {}   # key -> (fetch_time, candles)
        self._funding_cache: Dict[str, tuple] = {}  # symbol -> (fetch_time, rate)

    # ------------------------------------------------------------------
    def _fetch_json(self, url: str):
        try:
            with urllib.request.urlopen(url, timeout=self.timeout_sec,
                                        context=self._ssl_ctx) as resp:
                return json.loads(resp.read())
        except Exception as ex:
            if "CERTIFICATE" in str(ex).upper() or "SSL" in str(ex).upper():
                # corporate proxy / strict-chain environments: degrade once
                self._ssl_ctx = ssl.create_default_context()
                self._ssl_ctx.check_hostname = False
                self._ssl_ctx.verify_mode = ssl.CERT_NONE
                try:
                    with urllib.request.urlopen(url, timeout=self.timeout_sec,
                                                context=self._ssl_ctx) as resp:
                        return json.loads(resp.read())
                except Exception as ex2:
                    logger.warning(f"[KlineProvider] fetch failed after SSL fallback: {ex2}")
                    return None
            logger.warning(f"[KlineProvider] fetch failed: {ex}")
            return None

    # ------------------------------------------------------------------
    def get_klines(self, symbol: str, interval: str = "1h",
                   limit: int = 60) -> List[Dict]:
        """Closed candles only, oldest first. Empty list on failure."""
        key = f"{symbol.upper()}_{interval}_{limit}"
        cached = self._kline_cache.get(key)
        if cached and time.time() - cached[0] < self.cache_ttl_sec:
            return cached[1]

        url = (f"{BINANCE_FAPI}/fapi/v1/klines?symbol={symbol.upper()}"
               f"&interval={interval}&limit={limit + 1}")
        data = self._fetch_json(url)
        if not data:
            return cached[1] if cached else []

        candles = []
        for k in data:
            vol = float(k[5])
            bv = float(k[9])
            candles.append({
                "ts_ms": int(k[0]),
                "open": float(k[1]), "high": float(k[2]),
                "low": float(k[3]), "close": float(k[4]),
                "volume": vol, "buy_volume": bv,
                "buy_ratio": (bv / vol) if vol > 0 else 0.5,
                "close_ts_ms": int(k[6]),
            })
        # Drop the in-progress bar (its close_time is in the future)
        now_ms = int(time.time() * 1000)
        candles = [c for c in candles if c["close_ts_ms"] <= now_ms]
        self._kline_cache[key] = (time.time(), candles)
        return candles

    # ------------------------------------------------------------------
    def get_funding_rate(self, symbol: str) -> Optional[float]:
        """Current-period funding rate (e.g. 0.0001 = 0.01% per 8h)."""
        cached = self._funding_cache.get(symbol.upper())
        if cached and time.time() - cached[0] < self.cache_ttl_sec:
            return cached[1]

        url = f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol.upper()}"
        data = self._fetch_json(url)
        if not data or "lastFundingRate" not in data:
            return cached[1] if cached else None
        rate = float(data["lastFundingRate"])
        self._funding_cache[symbol.upper()] = (time.time(), rate)
        return rate

    # ------------------------------------------------------------------
    def now_ms(self) -> int:
        """Data-clock: wall time live; backtest providers override this."""
        return int(time.time() * 1000)
