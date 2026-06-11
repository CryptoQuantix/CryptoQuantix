#!/usr/bin/env python3
"""
Download multi-cycle dataset: 4 years of BTCUSDT 1m klines + funding.
Covers bear 2022, bull 2023-2025, bear 2025-2026 — needed to validate
strategies across BOTH market phases (single-phase backtests mislead).

Output:
  data/research/btc_1m_4y/btc_1m_<year>.csv.gz  (yearly chunks, <11MB each,
                                                 repo-friendly; t,o,h,l,c,v,bv)
  data/research/btc_funding_4y.json
"""
import gzip
import io
import json
import logging
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("multicycle_dl")

BINANCE_BASE = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
DAYS = 1460
LIMIT = 1500
OUT_DIR = "data/research"
KLINES_DIR = os.path.join(OUT_DIR, "btc_1m_4y")   # yearly chunks
FUNDING_PATH = os.path.join(OUT_DIR, "btc_funding_4y.json")


def _build_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


SSL_CTX = _build_ssl_context()


def fetch(url, retries=6):
    global SSL_CTX
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30, context=SSL_CTX) as resp:
                return json.loads(resp.read())
        except Exception as ex:
            if "CERTIFICATE" in str(ex).upper() or "SSL" in str(ex).upper():
                logger.warning("SSL verify failed - switching to unverified context")
                SSL_CTX = ssl.create_default_context()
                SSL_CTX.check_hostname = False
                SSL_CTX.verify_mode = ssl.CERT_NONE
                continue
            wait = min(2 ** attempt, 30)
            logger.warning(f"fetch error ({ex}); retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"failed after {retries} retries: {url}")


def download_klines():
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - DAYS * 86_400_000
    rows = []
    cur = start_ms
    calls = 0
    while cur < end_ms:
        url = (f"{BINANCE_BASE}/fapi/v1/klines?symbol={SYMBOL}&interval=1m"
               f"&startTime={cur}&endTime={end_ms}&limit={LIMIT}")
        data = fetch(url)
        if not data:
            break
        for k in data:
            rows.append(f"{int(k[0])},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]},{k[9]}")
        calls += 1
        if len(data) < LIMIT:
            break
        cur = int(data[-1][0]) + 60_000
        if calls % 100 == 0:
            pct = (cur - start_ms) / (end_ms - start_ms) * 100
            logger.info(f"klines: {len(rows):,} rows ({pct:.0f}%)")
        time.sleep(0.05)
    logger.info(f"klines done: {len(rows):,} rows, {calls} calls")
    return rows


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
    os.makedirs(KLINES_DIR, exist_ok=True)
    rows = download_klines()
    if len(rows) < 500_000:
        logger.error(f"too few rows ({len(rows)}) - aborting save")
        sys.exit(1)

    # Save in yearly chunks so each file stays well under GitHub size limits
    by_year = {}
    for row in rows:
        ts_ms = int(row.split(",", 1)[0])
        year = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).year
        by_year.setdefault(year, []).append(row)
    for year, yr_rows in sorted(by_year.items()):
        path = os.path.join(KLINES_DIR, f"btc_1m_{year}.csv.gz")
        with gzip.open(path, "wt") as f:
            f.write("t,o,h,l,c,v,bv\n")
            f.write("\n".join(yr_rows))
        logger.info(f"saved {path} ({len(yr_rows):,} rows, "
                    f"{os.path.getsize(path)/1e6:.1f} MB)")

    rates = download_funding()
    with open(FUNDING_PATH, "w") as f:
        json.dump(rates, f)
    logger.info(f"saved {FUNDING_PATH}")

    t0 = int(rows[0].split(",")[0]); t1 = int(rows[-1].split(",")[0])
    logger.info(f"period: {datetime.fromtimestamp(t0/1000, tz=timezone.utc):%Y-%m-%d} -> "
                f"{datetime.fromtimestamp(t1/1000, tz=timezone.utc):%Y-%m-%d}")


if __name__ == "__main__":
    main()
