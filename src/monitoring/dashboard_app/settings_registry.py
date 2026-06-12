"""
Registro dei parametri editabili dalla dashboard (Fase 3).

Ogni voce definisce: tipo di widget, BOUND = range validato/sensato,
valore validato di riferimento e se e' un parametro di strategia
(strategy_param=True -> banner "modifica = invalidazione backtest").

I secrets (DERIBIT_API_KEY/SECRET, TELEGRAM_*) NON sono qui: la pagina
mostra solo "impostata si'/no" e non li scrive mai.
"""
from typing import Any, Dict, List

# kind: bool | int | float | select | text
SETTINGS: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------
    # Rischio & operativo (parametri liberi — nessuna invalidazione)
    # ------------------------------------------------------------------
    {"key": "DERIBIT_ENV", "group": "Rischio & Operativo", "kind": "select",
     "options": ["test", "prod"], "label": "Ambiente Deribit",
     "help": "ATTENZIONE: prod = denaro reale", "strategy_param": False},
    {"key": "INITIAL_EQUITY", "group": "Rischio & Operativo", "kind": "int",
     "min": 1000, "max": 1_000_000, "step": 1000, "label": "Equity iniziale ($)",
     "strategy_param": False},
    {"key": "BASE_RISK_PCT", "group": "Rischio & Operativo", "kind": "float",
     "min": 0.001, "max": 0.03, "step": 0.001, "validated": "0.01",
     "label": "Rischio base per trade", "strategy_param": False,
     "help": "C4: 1% baseline; 1.5% = Calmar migliore ma DD 23%"},
    {"key": "MAX_DAILY_LOSS_PCT", "group": "Rischio & Operativo", "kind": "float",
     "min": 0.01, "max": 0.10, "step": 0.005, "validated": "0.03",
     "label": "Kill switch giornaliero (perdita max)", "strategy_param": False},
    {"key": "MAX_OPEN_TRADES", "group": "Rischio & Operativo", "kind": "int",
     "min": 1, "max": 10, "step": 1, "validated": "3",
     "label": "Max posizioni aperte", "strategy_param": False},
    {"key": "MAX_GROSS_EXPOSURE", "group": "Rischio & Operativo", "kind": "float",
     "min": 0.5, "max": 3.0, "step": 0.1, "validated": "1.5",
     "label": "Cap esposizione lorda (x equity)", "strategy_param": False,
     "help": "anti-oversizing multi-strategia"},
    {"key": "MONITORING_INTERVAL_MINUTES", "group": "Rischio & Operativo",
     "kind": "int", "min": 5, "max": 60, "step": 5, "validated": "15",
     "label": "Intervallo scan (minuti)", "strategy_param": False},
    {"key": "LOG_LEVEL", "group": "Rischio & Operativo", "kind": "select",
     "options": ["DEBUG", "INFO", "WARNING"], "label": "Log level",
     "strategy_param": False},

    # ------------------------------------------------------------------
    # Trend Breakdown (parametri VALIDATI — banner invalidazione)
    # ------------------------------------------------------------------
    {"key": "TB_ENABLED", "group": "Trend Breakdown", "kind": "bool",
     "label": "Abilitata", "strategy_param": False},
    {"key": "TB_SYMBOLS", "group": "Trend Breakdown", "kind": "text",
     "validated": "BTCUSDT,ETHUSDT", "label": "Simboli (istanza per simbolo)",
     "strategy_param": True},
    {"key": "TB_SHORT_SYMBOLS", "group": "Trend Breakdown", "kind": "text",
     "validated": "BTCUSDT", "label": "Simboli con short abilitato",
     "help": "short validato SOLO su BTC (ETH: PF 0.87)", "strategy_param": True},
    {"key": "TB_ENABLE_LONG", "group": "Trend Breakdown", "kind": "bool",
     "label": "Lato long abilitato", "strategy_param": True},
    {"key": "TB_LOOKBACK_H", "group": "Trend Breakdown", "kind": "int",
     "min": 24, "max": 96, "step": 4, "validated": "48",
     "label": "Lookback short (barre 1h)", "strategy_param": True},
    {"key": "TB_LOOKBACK_LONG_H", "group": "Trend Breakdown", "kind": "int",
     "min": 96, "max": 336, "step": 24, "validated": "168",
     "label": "Lookback long (barre 1h)",
     "help": "solo il breakout 168h sopravvive alla validazione",
     "strategy_param": True},
    {"key": "TB_SMA_H", "group": "Trend Breakdown", "kind": "int",
     "min": 24, "max": 96, "step": 4, "validated": "48",
     "label": "SMA filtro trend (1h)", "strategy_param": True},
    {"key": "TB_SL_ATR_MULT", "group": "Trend Breakdown", "kind": "float",
     "min": 1.5, "max": 3.0, "step": 0.1, "validated": "2.0",
     "label": "SL (x ATR 1h)", "strategy_param": True},
    {"key": "TB_RR_RATIO", "group": "Trend Breakdown", "kind": "float",
     "min": 1.0, "max": 3.0, "step": 0.5, "validated": "2.0",
     "label": "TP short (R)", "strategy_param": True},
    {"key": "TB_RR_LONG", "group": "Trend Breakdown", "kind": "float",
     "min": 0.0, "max": 4.0, "step": 0.5, "validated": "0",
     "label": "TP long (R, 0 = nessuno)",
     "help": "0 = let winners run: raddoppia l'edge vs TP 3R",
     "strategy_param": True},
    {"key": "TB_MAX_HOLD_HOURS", "group": "Trend Breakdown", "kind": "int",
     "min": 12, "max": 48, "step": 4, "validated": "24",
     "label": "Time exit short (ore)", "strategy_param": True},
    {"key": "TB_MAX_HOLD_LONG_HOURS", "group": "Trend Breakdown", "kind": "int",
     "min": 48, "max": 336, "step": 24, "validated": "168",
     "label": "Time exit long (ore)", "strategy_param": True},
    {"key": "TB_FLOW_CONFIRM", "group": "Trend Breakdown", "kind": "float",
     "min": 0.40, "max": 0.60, "step": 0.01, "validated": "0.50",
     "label": "Gate buy_ratio", "strategy_param": True},

    # ------------------------------------------------------------------
    # Funding Squeeze
    # ------------------------------------------------------------------
    {"key": "FS_ENABLED", "group": "Funding Squeeze", "kind": "bool",
     "label": "Abilitata", "strategy_param": False},
    {"key": "FS_SYMBOLS", "group": "Funding Squeeze", "kind": "text",
     "validated": "BTCUSDT,ETHUSDT", "label": "Simboli", "strategy_param": True},
    {"key": "FS_FUNDING_THRESHOLD", "group": "Funding Squeeze", "kind": "float",
     "min": 0.00005, "max": 0.0003, "step": 0.00005, "validated": "0.0001",
     "format": "%.5f", "label": "Soglia funding (per 8h)",
     "help": "0.0001 = 0.01%/8h = cap exchange BTC", "strategy_param": True},
    {"key": "FS_SL_ATR_MULT", "group": "Funding Squeeze", "kind": "float",
     "min": 1.5, "max": 3.0, "step": 0.1, "validated": "2.0",
     "label": "SL (x ATR 1h)", "strategy_param": True},
    {"key": "FS_TP_RR", "group": "Funding Squeeze", "kind": "float",
     "min": 0.0, "max": 3.0, "step": 0.5, "validated": "2.0",
     "label": "TP (R, 0 = solo time exit)", "strategy_param": True},
    {"key": "FS_MAX_HOLD_HOURS", "group": "Funding Squeeze", "kind": "int",
     "min": 12, "max": 48, "step": 4, "validated": "24",
     "label": "Time exit (ore)", "strategy_param": True},
    {"key": "FS_COOLDOWN_HOURS", "group": "Funding Squeeze", "kind": "int",
     "min": 8, "max": 24, "step": 8, "validated": "8",
     "label": "Cooldown (ore)", "strategy_param": True},
    {"key": "FS_SLOPE_DAYS", "group": "Funding Squeeze", "kind": "int",
     "min": 15, "max": 60, "step": 5, "validated": "30",
     "label": "Pendenza SMA200d (giorni)", "strategy_param": True},
    {"key": "FS_ENTRY_WINDOW_MIN", "group": "Funding Squeeze", "kind": "int",
     "min": 30, "max": 120, "step": 15, "validated": "60",
     "label": "Finestra post-settlement (min)", "strategy_param": True},

    # ------------------------------------------------------------------
    # Macro Core
    # ------------------------------------------------------------------
    {"key": "MC_ENABLED", "group": "Macro Core", "kind": "bool",
     "label": "Abilitata", "strategy_param": False},
    {"key": "MC_SYMBOLS", "group": "Macro Core", "kind": "text",
     "validated": "BTCUSDT", "label": "Simboli",
     "help": "ETH BOCCIATA; con N simboli il budget core si divide",
     "strategy_param": True},
    {"key": "MC_CHANDELIER_K", "group": "Macro Core", "kind": "float",
     "min": 4.5, "max": 6.0, "step": 0.1, "validated": "5.0",
     "label": "Chandelier k (x ATR20d)",
     "help": "plateau robusto validato: 4.5-6.0", "strategy_param": True},
    {"key": "MC_DISASTER_SL_PCT", "group": "Macro Core", "kind": "float",
     "min": 0.15, "max": 0.35, "step": 0.05, "validated": "0.25",
     "label": "Stop disastro (frazione)", "strategy_param": True},
    {"key": "MC_EXPOSURE_FRACTION", "group": "Macro Core", "kind": "float",
     "min": 0.25, "max": 1.0, "step": 0.05, "validated": "1.0",
     "label": "Frazione equity per il core", "strategy_param": False},
    {"key": "MC_VOL_TARGET", "group": "Macro Core", "kind": "float",
     "min": 0.0, "max": 0.5, "step": 0.05, "validated": "0.30",
     "label": "Vol-target annualizzata (0 = off)",
     "help": "C4: 30% adottato (maxDD 29.6% -> 21.5%)", "strategy_param": True},

    # ------------------------------------------------------------------
    # Strategie disattivate (solo toggle, con avvertenza)
    # ------------------------------------------------------------------
    {"key": "VB_ENABLED", "group": "Strategie disattivate", "kind": "bool",
     "label": "Volume Breakout", "verdict": "PF 0.42-0.74 — nessun edge",
     "strategy_param": True},
    {"key": "MR_ENABLED", "group": "Strategie disattivate", "kind": "bool",
     "label": "Mean Reversion", "verdict": "PF 0.28-0.53", "strategy_param": True},
    {"key": "LIQ_ENABLED", "group": "Strategie disattivate", "kind": "bool",
     "label": "Liq Squeeze", "verdict": "PF 0.06-0.30", "strategy_param": True},
    {"key": "IS_ENABLED", "group": "Strategie disattivate", "kind": "bool",
     "label": "Imbalance Scalp", "verdict": "fee-bound, PF 0.18-0.50",
     "strategy_param": True},
    {"key": "BRINGS_ENABLED", "group": "Strategie disattivate", "kind": "bool",
     "label": "NY Brings", "verdict": "PF 0.64, negativa ogni anno",
     "strategy_param": True},
    {"key": "WM_ENABLED", "group": "Strategie disattivate", "kind": "bool",
     "label": "W/M Formation", "verdict": "edge non strutturale (2024 neg, ETH neg)",
     "strategy_param": True},
    {"key": "STRATEGY_SMART_MONEY_ENABLED", "group": "Strategie disattivate",
     "kind": "bool", "label": "Smart Money",
     "verdict": "componenti gia' falsificati", "strategy_param": True},
    {"key": "STRATEGY_IRON_CONDOR_ENABLED", "group": "Strategie disattivate",
     "kind": "bool", "label": "Iron Condor",
     "verdict": "opzioni — fuori direzione progetto", "strategy_param": True},
]

GROUPS = ["Rischio & Operativo", "Trend Breakdown", "Funding Squeeze",
          "Macro Core", "Strategie disattivate"]

# Chiavi mostrate solo come "impostata si'/no"
SECRET_KEYS = ["DERIBIT_API_KEY", "DERIBIT_API_SECRET",
               "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]


def format_value(entry: Dict[str, Any], value: Any) -> str:
    """Valore widget -> stringa .env (bool lowercase, float senza notazione
    scientifica, resto as-is)."""
    if entry["kind"] == "bool":
        return "true" if value else "false"
    if entry["kind"] == "float":
        s = f"{value:.6f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return str(value).strip()
