#!/usr/bin/env python3
"""
Download extended research dataset from Binance Futures:
  - 270 days of 1m BTCUSDT klines (with taker buy volume)
  - full funding rate history for the same period

Output:
  data/research/btc_1m_research.json.gz   (gzipped list of candle dicts)
  data/research/btc_funding.json          (list of {ts, rate})
"""
import gzip
import json
import logging
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone

def _build_ssl_context():
    """Try certifi bundle first; fall back to unverified (public market data only)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

SSL_CTX = _build_ssl_context()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("research_dl")

BINANCE_BASE = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
DAYS = 270
LIMIT = 1500
OUT_DIR = "data/research"
KLINES_PATH = os.path.join(OUT_DIR, "btc_1m_research.json.gz")
FUNDING_PATH = os.path.join(OUT_DIR, "btc_funding.json")


def fetch(url, retries=5):
    global SSL_CTX
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30, context=SSL_CTX) as resp:
                return json.loads(resp.read())
        except Exception as ex:
            if "CERTIFICATE" in str(ex).upper() or "SSL" in str(ex).upper():
                logger.warning("SSL verify failed — switching to unverified context")
                SSL_CTX = ssl.create_default_context()
                SSL_CTX.check_hostname = False
                SSL_CTX.verify_mode = ssl.CERT_NONE
                continue
            wait = 2 ** attempt
            logger.warning(f"fetch error ({ex}); retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"failed after {retries} retries: {url}")


def download_klines():
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - DAYS * 86_400_000
    candles = []
    cur = start_ms
    calls = 0
    while cur < end_ms:
        url = (f"{BINANCE_BASE}/fapi/v1/klines?symbol={SYMBOL}&interval=1m"
               f"&startTime={cur}&endTime={end_ms}&limit={LIMIT}")
        data = fetch(url)
        if not data:
            break
        for k in data:
            vol = float(k[5])
            bv = float(k[9])
            candles.append({
                "t": int(k[0]),
                "o": float(k[1]), "h": float(k[2]),
                "l": float(k[3]), "c": float(k[4]),
                "v": vol, "bv": bv,
                "n": int(k[8]),          # trade count
                "q": float(k[7]),        # quote volume
            })
        calls += 1
        if len(data) < LIMIT:
            break
        cur = int(data[-1][0]) + 60_000
        if calls % 25 == 0:
            pct = (cur - start_ms) / (end_ms - start_ms) * 100
            logger.info(f"klines: {len(candles):,} candles ({pct:.0f}%)")
        time.sleep(0.06)
    logger.info(f"klines done: {len(candles):,} candles, {calls} calls")
    return candles


def download_funding():
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - DAYS * 86_400_000
    rates = []
    cur = start_ms
    while cur < end_ms:
        url = (f"{BINANCE_BASE}/fapi/v1/fundingRate?symbol={SYMBOL}"
               f"&startTime={cur}&endTime={end_ms}&limit=1000")
        data = fetch(url)
        if not data:
            break
        for r in data:
            rates.append({"t": int(r["fundingTime"]), "rate": float(r["fundingRate"])})
        if len(data) < 1000:
            break
        cur = int(data[-1]["fundingTime"]) + 1
        time.sleep(0.1)
    logger.info(f"funding done: {len(rates)} entries")
    return rates


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    candles = download_klines()
    if len(candles) < 100_000:
        logger.error(f"too few candles ({len(candles)}) — aborting save")
        sys.exit(1)
    with gzip.open(KLINES_PATH, "wt") as f:
        json.dump(candles, f)
    logger.info(f"saved {KLINES_PATH} ({os.path.getsize(KLINES_PATH)/1e6:.1f} MB)")

    rates = download_funding()
    with open(FUNDING_PATH, "w") as f:
        json.dump(rates, f)
    logger.info(f"saved {FUNDING_PATH}")

    first = datetime.fromtimestamp(candles[0]["t"]/1000, tz=timezone.utc)
    last = datetime.fromtimestamp(candles[-1]["t"]/1000, tz=timezone.utc)
    logger.info(f"period: {first:%Y-%m-%d} -> {last:%Y-%m-%d}  "
                f"price {candles[0]['c']:,.0f} -> {candles[-1]['c']:,.0f}")


if __name__ == "__main__":
    main()
