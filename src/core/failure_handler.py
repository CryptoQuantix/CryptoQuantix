"""
FailureHandler — gestisce i failure della connessione e le emergenze.

Responsabilità:
  1. Reconnect automatico a Deribit con exponential backoff
  2. Loop indipendente di check posizione (ogni 5s) — indipendente dal signal engine
  3. Emergency close: se API down per troppo tempo E posizione aperta → chiude tutto
  4. Rilevamento e log di anomalie API (latenza, errori ripetuti)

Progettato per girare come thread separato in background,
indipendente dal main trading loop.
"""
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from src.core.deribit_client import DeribitClient

logger = logging.getLogger(__name__)


class FailureHandler:
    """
    Monitora la salute della connessione Deribit e gestisce i failure.

    Uso:
        handler = FailureHandler(client, emergency_close_fn=close_all)
        handler.start()  # avvia thread background
        # ... trading loop ...
        handler.stop()
    """

    def __init__(
        self,
        client: DeribitClient,
        emergency_close_fn: Optional[Callable] = None,
        check_interval_sec: float = 5.0,
        max_api_down_sec: float = 30.0,
        max_reconnect_attempts: int = 10,
        currencies: Optional[List[str]] = None
    ):
        """
        Args:
            client:                 Deribit REST client
            emergency_close_fn:     Funzione da chiamare in caso di emergenza
                                    (es. position_monitor.close_all_futures)
                                    Se None, logga solo il warning
            check_interval_sec:     Intervallo check posizioni (secondi)
            max_api_down_sec:       Secondi di API irraggiungibile prima di emergency close
            max_reconnect_attempts: Tentativi max prima di arrendersi
            currencies:             Valute da monitorare (default: ["BTC", "ETH"])
        """
        self.client = client
        self.emergency_close_fn = emergency_close_fn
        self.check_interval_sec = check_interval_sec
        self.max_api_down_sec = max_api_down_sec
        self.max_reconnect_attempts = max_reconnect_attempts
        self.currencies = currencies or ["BTC", "ETH"]

        # State
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_successful_ping: Optional[datetime] = None
        self._consecutive_failures: int = 0
        self._emergency_triggered: bool = False
        self._api_error_count: int = 0

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Avvia il thread di monitoraggio in background."""
        if self._running:
            logger.warning("[FailureHandler] Già in esecuzione")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="FailureHandler",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[FailureHandler] Avviato — check ogni {self.check_interval_sec}s | "
            f"max API down: {self.max_api_down_sec}s"
        )

    def stop(self):
        """Ferma il thread di monitoraggio."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("[FailureHandler] Fermato")

    # ------------------------------------------------------------------
    # Main monitor loop
    # ------------------------------------------------------------------

    def _monitor_loop(self):
        """Loop principale eseguito nel thread background."""
        while self._running:
            try:
                self._perform_health_check()
            except Exception as e:
                logger.error(f"[FailureHandler] Errore nel monitor loop: {e}", exc_info=True)

            time.sleep(self.check_interval_sec)

    def _perform_health_check(self):
        """Esegue un singolo ciclo di health check."""
        # 1. Ping API con un endpoint leggero
        api_ok = self._ping_api()

        if api_ok:
            self._on_api_success()
        else:
            self._on_api_failure()

    def _ping_api(self) -> bool:
        """
        Verifica che l'API Deribit risponda.
        Usa get_index_price (endpoint pubblico leggero).
        """
        try:
            result = self.client.get_index_price("BTC")
            return result is not None and result > 0
        except Exception as e:
            logger.debug(f"[FailureHandler] Ping fallito: {e}")
            return False

    def _on_api_success(self):
        """Chiamato quando l'API risponde correttamente."""
        self._last_successful_ping = datetime.now()
        self._consecutive_failures = 0

        if self._api_error_count > 0:
            logger.info(
                f"[FailureHandler] Connessione ripristinata "
                f"(aveva {self._api_error_count} errori consecutivi)"
            )
            self._api_error_count = 0

    def _on_api_failure(self):
        """Chiamato quando l'API non risponde."""
        self._consecutive_failures += 1
        self._api_error_count += 1

        now = datetime.now()
        if self._last_successful_ping is None:
            down_since = now
        else:
            down_since = self._last_successful_ping

        seconds_down = (now - down_since).total_seconds()

        logger.warning(
            f"[FailureHandler] API non raggiungibile — "
            f"fallimenti consecutivi: {self._consecutive_failures} | "
            f"down da: {seconds_down:.0f}s"
        )

        # Tentativo di re-autenticazione con backoff
        if self._consecutive_failures <= self.max_reconnect_attempts:
            self._attempt_reconnect(self._consecutive_failures)
        else:
            logger.error(
                f"[FailureHandler] {self._consecutive_failures} fallimenti consecutivi — "
                "max tentativi raggiunto"
            )

        # Emergency close se down per troppo tempo
        if seconds_down >= self.max_api_down_sec and not self._emergency_triggered:
            self._trigger_emergency_close(seconds_down)

    def _attempt_reconnect(self, attempt: int):
        """
        Tenta re-autenticazione con exponential backoff.
        Backoff: 1s, 2s, 4s, 8s, 16s, ... (capped a 60s)
        """
        wait = min(2 ** (attempt - 1), 60)
        logger.info(f"[FailureHandler] Tentativo reconnect #{attempt} (attesa {wait}s)...")
        time.sleep(wait)

        try:
            success = self.client.authenticate()
            if success:
                logger.info(f"[FailureHandler] Re-autenticazione riuscita al tentativo #{attempt}")
                self._consecutive_failures = 0
            else:
                logger.warning(f"[FailureHandler] Re-autenticazione fallita al tentativo #{attempt}")
        except Exception as e:
            logger.error(f"[FailureHandler] Errore durante reconnect: {e}")

    def _trigger_emergency_close(self, seconds_down: float):
        """
        Triggera la chiusura d'emergenza di tutte le posizioni aperte.
        Chiamato quando l'API è down da troppo tempo.
        """
        self._emergency_triggered = True

        logger.critical(
            f"[EMERGENCY] API Deribit irraggiungibile da {seconds_down:.0f}s "
            f"(soglia: {self.max_api_down_sec}s). "
            "Tentativo chiusura d'emergenza posizioni..."
        )

        if self.emergency_close_fn is None:
            logger.critical(
                "[EMERGENCY] Nessuna emergency_close_fn configurata. "
                "ATTENZIONE: posizioni potrebbero essere ancora aperte!"
            )
            return

        try:
            self.emergency_close_fn()
            logger.critical("[EMERGENCY] Chiusura d'emergenza eseguita")
        except Exception as e:
            logger.critical(f"[EMERGENCY] Errore durante chiusura d'emergenza: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Stato corrente del FailureHandler."""
        now = datetime.now()
        seconds_since_ping = (
            (now - self._last_successful_ping).total_seconds()
            if self._last_successful_ping else None
        )

        return {
            "running": self._running,
            "last_successful_ping": (
                self._last_successful_ping.isoformat()
                if self._last_successful_ping else "mai"
            ),
            "seconds_since_last_ping": seconds_since_ping,
            "consecutive_failures": self._consecutive_failures,
            "api_error_count": self._api_error_count,
            "emergency_triggered": self._emergency_triggered,
            "api_healthy": self._consecutive_failures == 0
        }

    def reset_emergency(self):
        """
        Reset del flag emergency (da chiamare manualmente dopo verifica manuale).
        Non resetta automaticamente — richiede intervento umano.
        """
        if self._emergency_triggered:
            logger.info("[FailureHandler] Emergency flag resettato manualmente")
            self._emergency_triggered = False
