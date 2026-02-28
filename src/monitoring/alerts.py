"""
TelegramAlerts — sends trading notifications to Telegram.

Supported event types:
  - TRADE_OPEN: new position opened
  - TRADE_CLOSE_TP: take profit hit
  - TRADE_CLOSE_SL: stop loss hit
  - TRADE_CLOSE_MANUAL: manual close
  - DAILY_PNL: daily P&L summary
  - REGIME_CHANGE: market regime changed
  - API_ERROR: Deribit API issue
  - EMERGENCY: emergency close triggered
  - KILL_SWITCH: daily loss limit hit

Configuration:
  - TELEGRAM_BOT_TOKEN env var
  - TELEGRAM_CHAT_ID env var

Rate limiting: max 1 message per alert type per 60 seconds (prevents spam).
"""
import logging
import os
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from queue import Queue, Empty
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Optional dependency
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class AlertEvent:
    """A notification event to be sent."""
    event_type: str
    message: str
    level: AlertLevel = AlertLevel.INFO
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


# Emoji mapping for readability
LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.CRITICAL: "🚨",
}

EVENT_EMOJI = {
    "TRADE_OPEN": "📈",
    "TRADE_CLOSE_TP": "✅",
    "TRADE_CLOSE_SL": "❌",
    "TRADE_CLOSE_MANUAL": "🔄",
    "DAILY_PNL": "📊",
    "REGIME_CHANGE": "🔀",
    "API_ERROR": "⚡",
    "EMERGENCY": "🚨",
    "KILL_SWITCH": "🛑",
}


class TelegramAlerts:
    """
    Async-friendly Telegram notification system.
    Uses a background thread to avoid blocking the trading loop.

    Usage:
        alerts = TelegramAlerts()
        alerts.send_trade_open("BTC-PERPETUAL", "BUY", 50000, 49000, 51500)
        alerts.send_daily_pnl(250.0, 5, 3)
    """

    TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: str = None,
        chat_id: str = None,
        enabled: bool = True,
        rate_limit_sec: float = 60.0,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled = enabled and bool(self.bot_token) and bool(self.chat_id)
        self.rate_limit_sec = rate_limit_sec

        if enabled and not self.enabled:
            logger.warning(
                "[Alerts] Telegram disabled — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )

        # Rate limiting: {event_type: last_sent_timestamp}
        self._last_sent: Dict[str, float] = {}

        # Background queue for non-blocking sends
        self._queue: Queue = Queue(maxsize=100)
        self._thread = threading.Thread(
            target=self._sender_loop, daemon=True, name="AlertSender"
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # High-level send methods
    # ------------------------------------------------------------------

    def send_trade_open(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        strategy: str = "",
        regime: str = "",
        quantity: float = 0.0,
    ):
        emoji = "🟢" if direction.upper() == "BUY" else "🔴"
        msg = (
            f"{emoji} *TRADE APERTO*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• Strumento: `{instrument}`\n"
            f"• Direzione: *{direction.upper()}*\n"
            f"• Entry: `${entry_price:,.2f}`\n"
            f"• Stop Loss: `${sl_price:,.2f}`\n"
            f"• Take Profit: `${tp_price:,.2f}`\n"
            f"• R/R: `{abs(tp_price - entry_price) / abs(entry_price - sl_price):.1f}x`\n"
            f"• Quantità: `{quantity:.4f}`\n"
            f"• Strategia: `{strategy}`\n"
            f"• Regime: `{regime}`\n"
            f"• Ora: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
        )
        self._enqueue(AlertEvent("TRADE_OPEN", msg, AlertLevel.INFO))

    def send_trade_close(
        self,
        instrument: str,
        direction: str,
        close_reason: str,
        pnl_usd: float,
        entry_price: float,
        exit_price: float,
        r_multiple: float = 0.0,
    ):
        if close_reason == "tp":
            event_type = "TRADE_CLOSE_TP"
            emoji = "✅"
            prefix = "TAKE PROFIT"
        elif close_reason == "sl":
            event_type = "TRADE_CLOSE_SL"
            emoji = "❌"
            prefix = "STOP LOSS"
        else:
            event_type = "TRADE_CLOSE_MANUAL"
            emoji = "🔄"
            prefix = "CHIUSO"

        pnl_emoji = "📈" if pnl_usd >= 0 else "📉"
        msg = (
            f"{emoji} *{prefix}*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• Strumento: `{instrument}`\n"
            f"• Direzione: `{direction.upper()}`\n"
            f"• Entry: `${entry_price:,.2f}`\n"
            f"• Exit: `${exit_price:,.2f}`\n"
            f"• P&L: {pnl_emoji} `${pnl_usd:+,.2f}`\n"
            f"• R-multiple: `{r_multiple:+.2f}R`\n"
            f"• Ora: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
        )
        level = AlertLevel.WARNING if close_reason == "sl" else AlertLevel.INFO
        self._enqueue(AlertEvent(event_type, msg, level))

    def send_daily_pnl(
        self,
        daily_pnl: float,
        total_trades: int,
        winning_trades: int,
        equity: float = 0.0,
    ):
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0
        msg = (
            f"📊 *RIEPILOGO GIORNALIERO*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• P&L: {pnl_emoji} `${daily_pnl:+,.2f}`\n"
            f"• Trade totali: `{total_trades}`\n"
            f"• Win rate: `{win_rate:.0f}%` ({winning_trades}/{total_trades})\n"
            f"• Equity: `${equity:,.2f}`\n"
            f"• Data: `{datetime.now(timezone.utc).strftime('%Y-%m-%d UTC')}`"
        )
        self._enqueue(AlertEvent("DAILY_PNL", msg, AlertLevel.INFO))

    def send_regime_change(self, symbol: str, old_regime: str, new_regime: str, confidence: float):
        msg = (
            f"🔀 *CAMBIO REGIME*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• Simbolo: `{symbol}`\n"
            f"• Da: `{old_regime}`\n"
            f"• A: *{new_regime}*\n"
            f"• Confidenza: `{confidence:.0%}`\n"
            f"• Ora: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
        )
        self._enqueue(AlertEvent("REGIME_CHANGE", msg, AlertLevel.INFO))

    def send_api_error(self, error_msg: str, consecutive_failures: int):
        msg = (
            f"⚡ *ERRORE API DERIBIT*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• Errore: `{error_msg[:200]}`\n"
            f"• Fallimenti consecutivi: `{consecutive_failures}`\n"
            f"• Ora: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
        )
        self._enqueue(AlertEvent("API_ERROR", msg, AlertLevel.WARNING))

    def send_emergency(self, reason: str):
        msg = (
            f"🚨 *EMERGENZA — CHIUSURA POSIZIONI*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• Motivo: `{reason}`\n"
            f"• Azione: Tutte le posizioni chiuse\n"
            f"• Ora: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`\n"
            f"⚠️ Verifica manuale richiesta!"
        )
        self._enqueue(AlertEvent("EMERGENCY", msg, AlertLevel.CRITICAL))

    def send_kill_switch(self, daily_pnl: float, max_loss_pct: float, equity: float):
        msg = (
            f"🛑 *KILL SWITCH ATTIVATO*\n"
            f"━━━━━━━━━━━━━━━\n"
            f"• P&L giornaliero: `${daily_pnl:+,.2f}`\n"
            f"• Limite: `{max_loss_pct:.0%}` di equity\n"
            f"• Equity corrente: `${equity:,.2f}`\n"
            f"• Trading sospeso per oggi\n"
            f"• Ora: `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
        )
        self._enqueue(AlertEvent("KILL_SWITCH", msg, AlertLevel.CRITICAL))

    def send_custom(self, message: str, level: AlertLevel = AlertLevel.INFO):
        self._enqueue(AlertEvent("CUSTOM", message, level))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enqueue(self, event: AlertEvent):
        """Add event to send queue (non-blocking)."""
        # Rate limiting per event type
        now = time.time()
        last = self._last_sent.get(event.event_type, 0)
        if now - last < self.rate_limit_sec and event.level != AlertLevel.CRITICAL:
            logger.debug(f"[Alerts] Rate-limited: {event.event_type}")
            return

        try:
            self._queue.put_nowait(event)
        except Exception:
            pass  # Queue full — drop

    def _sender_loop(self):
        """Background thread: sends queued messages to Telegram."""
        while True:
            try:
                event = self._queue.get(timeout=5)
                self._send(event)
                self._last_sent[event.event_type] = time.time()
                time.sleep(0.1)  # Telegram API rate limit: ~30 msgs/sec
            except Empty:
                continue
            except Exception as e:
                logger.debug(f"[Alerts] Sender loop error: {e}")

    def _send(self, event: AlertEvent):
        """Actually send the Telegram message."""
        if not self.enabled:
            # Log to console if Telegram not configured
            logger.info(f"[ALERT/{event.event_type}] {event.message[:100]}")
            return

        if not HAS_REQUESTS:
            logger.warning("[Alerts] requests library not installed")
            return

        try:
            url = self.TELEGRAM_API_URL.format(token=self.bot_token)
            payload = {
                "chat_id": self.chat_id,
                "text": event.message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }
            resp = requests.post(url, json=payload, timeout=10)
            if not resp.ok:
                logger.warning(f"[Alerts] Telegram error {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.warning(f"[Alerts] Send failed: {e}")

    def test_connection(self) -> bool:
        """Test Telegram bot connection."""
        if not self.enabled:
            logger.info("[Alerts] Telegram not configured — test skipped")
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            resp = requests.get(url, timeout=5)
            if resp.ok:
                name = resp.json().get("result", {}).get("username", "unknown")
                logger.info(f"[Alerts] Telegram bot connected: @{name}")
                return True
            return False
        except Exception as e:
            logger.warning(f"[Alerts] Connection test failed: {e}")
            return False
