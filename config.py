"""
Configuration module for the trading bot
Loads all settings from environment variables with defaults
"""

import os
from typing import List, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class StrategyConfig:
    """Base configuration for any strategy"""
    name: str
    enabled: bool = True


@dataclass
class IronCondorConfig(StrategyConfig):
    """Configuration for Iron Condor strategy"""
    initial_equity: float = 10000.0
    risk_per_condor: float = 0.01
    max_portfolio_risk: float = 0.03
    tp_ratio: float = 0.55
    sl_mult: float = 1.2
    close_before_expiry_hours: int = 24
    min_dte: int = 7
    max_dte: int = 10
    min_iv_percentile: float = 30.0
    short_delta_target: float = 0.12
    wing_width_percent: float = 0.05
    currencies: List[str] = None

    def __post_init__(self):
        if self.currencies is None:
            self.currencies = ["BTC", "ETH"]


@dataclass
class SmartMoneyConfig(StrategyConfig):
    """Configuration for Smart Money strategy"""
    time_window_start: int = 14  # 14:00
    time_window_end: int = 17    # 17:00
    whale_min_value: int = 500000  # $500k
    binance_symbol: str = "BTCUSDT"
    liquidity_lookback_periods: int = 20
    timeframe: str = "15m"
    symbol: str = "BTC/USDT"
    absorption_min_vol: float = 10.0
    absorption_delta_ratio: float = 0.15
    absorption_price_threshold: float = 0.01
    risk_per_trade_pct: float = 0.015
    risk_reward_ratio: float = 2.5
    leverage_max: int = 5


@dataclass
class WMFormationConfig(StrategyConfig):
    """Configuration for W/M Formation strategy"""
    deribit_symbol: str = "BTC-PERPETUAL"
    binance_symbol: str = "BTC/USDT"
    primary_timeframe: str = "1h"
    confirmation_timeframe_1: str = "15m"
    confirmation_timeframe_2: str = "5m"
    phase1_min_vector_candles: int = 2
    phase2_retracement_min: float = 0.15
    phase2_retracement_max: float = 0.85
    phase3_sweep_buffer: float = 0.003
    entry_mode: str = "reclaim"
    trend_filter_enabled: bool = True  # Re-enabled
    trend_filter_timeframe: str = "4h"
    ema_fast: int = 50
    ema_medium: int = 60
    ema_slow: int = 200
    ema_very_slow: int = 223
    stop_loss_buffer_pct: float = 0.005 # Increased from 0.002
    risk_per_trade_pct: float = 0.02
    take_profit_ratio: float = 2.0
    max_leverage: float = 5.0
    min_stop_loss_dist_pct: float = 0.002
    log_positions: bool = True
    position_log_file: str = "logs/wm_positions.txt"
    scan_interval_seconds: int = 60
    
    # RSI Settings
    rsi_period: int = 14
    rsi_oversold: int = 40
    rsi_overbought: int = 60

    @staticmethod
    def from_env():
        return WMFormationConfig(
            name="WM Formation",
            enabled=os.getenv("WM_ENABLED", "false").lower() == "true",
            deribit_symbol=os.getenv("WM_DERIBIT_SYMBOL", "BTC-PERPETUAL"),
            binance_symbol=os.getenv("WM_BINANCE_SYMBOL", "BTC/USDT"),
            primary_timeframe=os.getenv("WM_PRIMARY_TIMEFRAME", "15m"),
            confirmation_timeframe_1=os.getenv("WM_CONFIRMATION_TF1", "5m"),
            confirmation_timeframe_2=os.getenv("WM_CONFIRMATION_TF2", "1m"),
            phase1_min_vector_candles=int(os.getenv("WM_PHASE1_MIN_VECTORS", "2")),
            phase2_retracement_min=float(os.getenv("WM_RETRACEMENT_MIN", "0.15")),
            phase2_retracement_max=float(os.getenv("WM_RETRACEMENT_MAX", "0.85")),
            phase3_sweep_buffer=float(os.getenv("WM_SWEEP_BUFFER", "0.003")),
            entry_mode=os.getenv("WM_ENTRY_MODE", "reclaim"),
            trend_filter_enabled=os.getenv("WM_TREND_FILTER_ENABLED", "false").lower() == "true",
            trend_filter_timeframe=os.getenv("WM_TREND_FILTER_TF", "4h"),
            ema_fast=int(os.getenv("WM_EMA_FAST", "50")),
            ema_medium=int(os.getenv("WM_EMA_MEDIUM", "60")),
            ema_slow=int(os.getenv("WM_EMA_SLOW", "200")),
            ema_very_slow=int(os.getenv("WM_EMA_VERY_SLOW", "223")),
            stop_loss_buffer_pct=float(os.getenv("WM_STOP_LOSS_BUFFER_PCT", "0.005")),
            risk_per_trade_pct=float(os.getenv("WM_RISK_PER_TRADE_PCT", "0.02")),
            take_profit_ratio=float(os.getenv("WM_TAKE_PROFIT_RATIO", "2.0")),
            log_positions=os.getenv("WM_LOG_POSITIONS", "true").lower() == "true",
            position_log_file=os.getenv("WM_POSITION_LOG_FILE", "logs/wm_positions.txt"),
            scan_interval_seconds=int(os.getenv("WM_SCAN_INTERVAL", "60")),
            rsi_period=int(os.getenv("WM_RSI_PERIOD", "14")),
            rsi_oversold=int(os.getenv("WM_RSI_OVERSOLD", "40")),
            rsi_overbought=int(os.getenv("WM_RSI_OVERBOUGHT", "60")),
            max_leverage=float(os.getenv("WM_MAX_LEVERAGE", "5.0")),
            min_stop_loss_dist_pct=float(os.getenv("WM_MIN_SL_DIST", "0.002")),
        )

    def __post_init__(self):
        """Ensure compatibility with generic strategy logic"""
        self.timeframe = self.primary_timeframe


@dataclass
class BringsStrategyConfig(StrategyConfig):
    """Configuration for NY Brings Strategy"""
    deribit_symbol: str = "BTC-PERPETUAL"
    binance_symbol: str = "BTC/USDT"
    timeframe: str = "5m"
    risk_per_trade_pct: float = 0.01
    stop_loss_buffer: float = 0.002
    take_profit_ratio: float = 1.5
    timezone: str = "Europe/Rome"

    @staticmethod
    def from_env():
        return BringsStrategyConfig(
            name="NY Brings",
            enabled=os.getenv("BRINGS_ENABLED", "false").lower() == "true",
            deribit_symbol=os.getenv("BRINGS_DERIBIT_SYMBOL", "BTC-PERPETUAL"),
            binance_symbol=os.getenv("BRINGS_BINANCE_SYMBOL", "BTC/USDT"),
            timeframe=os.getenv("BRINGS_TIMEFRAME", "5m"),
            risk_per_trade_pct=float(os.getenv("BRINGS_RISK_PER_TRADE_PCT", "0.01")),
            stop_loss_buffer=float(os.getenv("BRINGS_STOP_LOSS_BUFFER", "0.002")),
            take_profit_ratio=float(os.getenv("BRINGS_TAKE_PROFIT_RATIO", "1.5")),
            timezone=os.getenv("BRINGS_TIMEZONE", "Europe/Rome"),
        )


# ============================================================
# NEW VOLUMETRIC STRATEGY CONFIGS
# ============================================================

@dataclass
class VolumeBreakoutConfig(StrategyConfig):
    """Configuration for Volume Breakout strategy"""
    symbol: str = "BTCUSDT"          # Binance symbol (data source)
    instrument: str = "BTC-PERPETUAL"  # Deribit execution instrument
    volume_zscore_threshold: float = 2.5
    imbalance_threshold: float = 0.50
    breakout_lookback: int = 20
    rr_ratio: float = 2.5
    sl_atr_multiplier: float = 1.5

    @staticmethod
    def from_env():
        return VolumeBreakoutConfig(
            name="Volume Breakout",
            enabled=os.getenv("VB_ENABLED", "true").lower() == "true",
            symbol=os.getenv("VB_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("VB_INSTRUMENT", "BTC-PERPETUAL"),
            volume_zscore_threshold=float(os.getenv("VB_VOL_ZSCORE_THRESHOLD", "2.5")),
            imbalance_threshold=float(os.getenv("VB_IMBALANCE_THRESHOLD", "0.50")),
            breakout_lookback=int(os.getenv("VB_BREAKOUT_LOOKBACK", "20")),
            rr_ratio=float(os.getenv("VB_RR_RATIO", "2.5")),
            sl_atr_multiplier=float(os.getenv("VB_SL_ATR_MULT", "1.5")),
        )


@dataclass
class MeanReversionConfig(StrategyConfig):
    """Configuration for Mean Reversion strategy"""
    symbol: str = "BTCUSDT"
    instrument: str = "BTC-PERPETUAL"
    vwap_z_threshold: float = 2.0
    max_volume_zscore: float = 1.5
    rr_ratio: float = 1.5
    sl_atr_multiplier: float = 1.2

    @staticmethod
    def from_env():
        return MeanReversionConfig(
            name="Mean Reversion",
            enabled=os.getenv("MR_ENABLED", "true").lower() == "true",
            symbol=os.getenv("MR_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("MR_INSTRUMENT", "BTC-PERPETUAL"),
            vwap_z_threshold=float(os.getenv("MR_VWAP_Z_THRESHOLD", "2.0")),
            max_volume_zscore=float(os.getenv("MR_MAX_VOL_ZSCORE", "1.5")),
            rr_ratio=float(os.getenv("MR_RR_RATIO", "1.5")),
            sl_atr_multiplier=float(os.getenv("MR_SL_ATR_MULT", "1.2")),
        )


@dataclass
class LiqSqueezeConfig(StrategyConfig):
    """Configuration for Liquidation Squeeze strategy"""
    symbol: str = "BTCUSDT"
    instrument: str = "BTC-PERPETUAL"
    liq_volume_threshold: float = 50.0
    delta_threshold: float = 0.3
    rr_ratio: float = 1.5
    sl_atr_multiplier: float = 0.8

    @staticmethod
    def from_env():
        return LiqSqueezeConfig(
            name="Liquidation Squeeze",
            enabled=os.getenv("LIQ_ENABLED", "true").lower() == "true",
            symbol=os.getenv("LIQ_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("LIQ_INSTRUMENT", "BTC-PERPETUAL"),
            liq_volume_threshold=float(os.getenv("LIQ_VOLUME_THRESHOLD", "50.0")),
            delta_threshold=float(os.getenv("LIQ_DELTA_THRESHOLD", "0.3")),
            rr_ratio=float(os.getenv("LIQ_RR_RATIO", "1.5")),
            sl_atr_multiplier=float(os.getenv("LIQ_SL_ATR_MULT", "0.8")),
        )


@dataclass
class ImbalanceScalpConfig(StrategyConfig):
    """Configuration for Imbalance Scalp strategy"""
    symbol: str = "BTCUSDT"
    instrument: str = "BTC-PERPETUAL"
    imbalance_threshold_long: float = 0.65
    imbalance_threshold_short: float = 0.35
    aggression_threshold: float = 0.60
    tp_pct: float = 0.005
    sl_pct: float = 0.003
    max_volume_zscore: float = 1.8

    @staticmethod
    def from_env():
        return ImbalanceScalpConfig(
            name="Imbalance Scalp",
            enabled=os.getenv("IS_ENABLED", "true").lower() == "true",
            symbol=os.getenv("IS_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("IS_INSTRUMENT", "BTC-PERPETUAL"),
            imbalance_threshold_long=float(os.getenv("IS_IMB_THRESHOLD_LONG", "0.65")),
            imbalance_threshold_short=float(os.getenv("IS_IMB_THRESHOLD_SHORT", "0.35")),
            aggression_threshold=float(os.getenv("IS_AGGR_THRESHOLD", "0.60")),
            tp_pct=float(os.getenv("IS_TP_PCT", "0.005")),
            sl_pct=float(os.getenv("IS_SL_PCT", "0.003")),
            max_volume_zscore=float(os.getenv("IS_MAX_VOL_ZSCORE", "1.8")),
        )


@dataclass
class TrendBreakdownConfig(StrategyConfig):
    """Configuration for Trend Breakdown strategy (two-sided, macro-gated).

    Validated on 4y BTCUSDT 1m (Jun 2022 - Jun 2026, bear+bull+bear):
    SHORT (48h-low break, macro bear): +14.5bps/trade PF 1.15 (183 trades);
      on 2025-26 bear alone +50bps PF 1.8 (IS/OOS confirmed).
    LONG (7d-high break, macro bull, no TP / hold 7d): +71bps/trade PF 1.56
      (83 trades) — letting winners run doubles the edge vs TP 3R/48h."""
    symbol: str = "BTCUSDT"
    instrument: str = "BTC-PERPETUAL"
    lookback_h: int = 48          # Donchian LOW lookback for shorts (1h bars)
    lookback_long_h: int = 168    # Donchian HIGH lookback for longs (7 days)
    sma_h: int = 48               # trend filter SMA period (1h bars)
    atr_period: int = 14
    sl_atr_mult: float = 2.0
    rr_ratio: float = 2.0         # TP for shorts
    rr_long: float = 0.0          # 0 = no TP for longs (let winners run)
    max_hold_hours: int = 24      # time exit for shorts
    max_hold_long_hours: int = 168  # time exit for longs (7 days)
    flow_confirm: float = 0.50    # taker buy_ratio gate (<x short, >1-x long)
    enable_long: bool = True      # macro-gated: inactive until macro bull
    macro_sma_days: int = 200     # daily SMA gate: bear=shorts, bull=longs

    @staticmethod
    def from_env():
        return TrendBreakdownConfig(
            name="Trend Breakdown",
            enabled=os.getenv("TB_ENABLED", "true").lower() == "true",
            symbol=os.getenv("TB_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("TB_INSTRUMENT", "BTC-PERPETUAL"),
            lookback_h=int(os.getenv("TB_LOOKBACK_H", "48")),
            lookback_long_h=int(os.getenv("TB_LOOKBACK_LONG_H", "168")),
            sma_h=int(os.getenv("TB_SMA_H", "48")),
            atr_period=int(os.getenv("TB_ATR_PERIOD", "14")),
            sl_atr_mult=float(os.getenv("TB_SL_ATR_MULT", "2.0")),
            rr_ratio=float(os.getenv("TB_RR_RATIO", "2.0")),
            rr_long=float(os.getenv("TB_RR_LONG", "0")),
            max_hold_hours=int(os.getenv("TB_MAX_HOLD_HOURS", "24")),
            max_hold_long_hours=int(os.getenv("TB_MAX_HOLD_LONG_HOURS", "168")),
            flow_confirm=float(os.getenv("TB_FLOW_CONFIRM", "0.50")),
            enable_long=os.getenv("TB_ENABLE_LONG", "true").lower() == "true",
            macro_sma_days=int(os.getenv("TB_MACRO_SMA_DAYS", "200")),
        )


@dataclass
class FundingSqueezeConfig(StrategyConfig):
    """Configuration for Funding Squeeze strategy (deep-bear capitulation short).

    4y multi-cycle validation (Jun 2022 - Jun 2026): funding at cap (0.01%/8h)
    + daily close < SMA200d with SMA200d declining -> +74bps/trade PF 3.05
    WR 60% (low frequency by design; bleed in bull/transitions eliminated)."""
    symbol: str = "BTCUSDT"
    instrument: str = "BTC-PERPETUAL"
    funding_threshold: float = 0.0001    # 0.01% per 8h = exchange cap
    sma_h: int = 48
    atr_period: int = 14
    sl_atr_mult: float = 2.0
    tp_rr: float = 2.0                   # TP at 2R (0 = time exit only)
    max_hold_hours: int = 24
    cooldown_hours: int = 8              # one trade per funding window
    macro_sma_days: int = 200            # daily SMA200 bear gate
    slope_days: int = 30                 # SMA200d must be lower than N days ago
    entry_window_min: int = 60           # enter only just after funding settles

    @staticmethod
    def from_env():
        return FundingSqueezeConfig(
            name="Funding Squeeze",
            enabled=os.getenv("FS_ENABLED", "true").lower() == "true",
            symbol=os.getenv("FS_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("FS_INSTRUMENT", "BTC-PERPETUAL"),
            funding_threshold=float(os.getenv("FS_FUNDING_THRESHOLD", "0.0001")),
            sma_h=int(os.getenv("FS_SMA_H", "48")),
            atr_period=int(os.getenv("FS_ATR_PERIOD", "14")),
            sl_atr_mult=float(os.getenv("FS_SL_ATR_MULT", "2.0")),
            tp_rr=float(os.getenv("FS_TP_RR", "2.0")),
            max_hold_hours=int(os.getenv("FS_MAX_HOLD_HOURS", "24")),
            cooldown_hours=int(os.getenv("FS_COOLDOWN_HOURS", "8")),
            macro_sma_days=int(os.getenv("FS_MACRO_SMA_DAYS", "200")),
            slope_days=int(os.getenv("FS_SLOPE_DAYS", "30")),
            entry_window_min=int(os.getenv("FS_ENTRY_WINDOW_MIN", "60")),
        )


@dataclass
class MacroCoreConfig(StrategyConfig):
    """Configuration for Macro Core strategy (regime-following long core).

    4y validation (Jun 2022 - Jun 2026, daily, costs 0.10%/side):
    entry daily close > SMA200d, exit chandelier 5xATR20d from max close:
    +315% vs +136% buy&hold, maxDD 24.8%, 9 trades, 2025 -1%.
    Robust plateau k in [4.5, 6]."""
    symbol: str = "BTCUSDT"
    instrument: str = "BTC-PERPETUAL"
    sma_days: int = 200            # macro trend filter (daily SMA)
    atr_days: int = 20             # daily ATR period for the chandelier
    chandelier_k: float = 5.0      # exit: close < max_close - k * ATR20d
    disaster_sl_pct: float = 0.25  # venue stop at entry*(1-25%) (crash guard)
    exposure_fraction: float = 1.0 # core size = equity * fraction
    # C4 equity sim: vol-target 30% cuts portfolio maxDD 29.6% -> 21.5% and
    # worst year to 0% while keeping the best Calmar. 0 disables.
    vol_target: float = 0.30       # annualized target vol (0 = fixed expo)
    vol_lookback_days: int = 30    # realized vol window (daily closes)
    expo_step: float = 0.25        # exposure quantization (limits churn)
    state_path: str = "data/macro_core_state.json"
    persist_state: bool = True

    @staticmethod
    def from_env():
        return MacroCoreConfig(
            name="Macro Core",
            enabled=os.getenv("MC_ENABLED", "true").lower() == "true",
            symbol=os.getenv("MC_SYMBOL", "BTCUSDT"),
            instrument=os.getenv("MC_INSTRUMENT", "BTC-PERPETUAL"),
            sma_days=int(os.getenv("MC_SMA_DAYS", "200")),
            atr_days=int(os.getenv("MC_ATR_DAYS", "20")),
            chandelier_k=float(os.getenv("MC_CHANDELIER_K", "5.0")),
            disaster_sl_pct=float(os.getenv("MC_DISASTER_SL_PCT", "0.25")),
            exposure_fraction=float(os.getenv("MC_EXPOSURE_FRACTION", "1.0")),
            vol_target=float(os.getenv("MC_VOL_TARGET", "0.30")),
            vol_lookback_days=int(os.getenv("MC_VOL_LOOKBACK_DAYS", "30")),
            expo_step=float(os.getenv("MC_EXPO_STEP", "0.25")),
            state_path=os.getenv("MC_STATE_PATH", "data/macro_core_state.json"),
        )


class Config:
    """Global configuration class"""

    # Deribit API
    DERIBIT_API_KEY = os.getenv("DERIBIT_API_KEY", "")
    DERIBIT_API_SECRET = os.getenv("DERIBIT_API_SECRET", "")
    DERIBIT_ENV = os.getenv("DERIBIT_ENV", "test")

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = "logs/trading_bot.log"

    # Schedule
    DAILY_SCAN_TIME = os.getenv("DAILY_SCAN_TIME", "10:00")
    MONITORING_INTERVAL_MINUTES = int(os.getenv("MONITORING_INTERVAL_MINUTES", 5))

    # Strategies
    STRATEGIES: List[StrategyConfig] = []

    @classmethod
    def load_strategies(cls):
        """Load enabled strategies"""
        cls.STRATEGIES = []

        # --- Legacy strategies (disabled by default) ---
        # Iron Condor — opzioni, non usa orderflow; abilitare con STRATEGY_IRON_CONDOR_ENABLED=true
        if os.getenv("STRATEGY_IRON_CONDOR_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(IronCondorConfig(
                name="Iron Condor",
                initial_equity=float(os.getenv("INITIAL_EQUITY", 10000)),
                risk_per_condor=float(os.getenv("RISK_PER_CONDOR", 0.01)),
                max_portfolio_risk=float(os.getenv("MAX_PORTFOLIO_RISK", 0.03)),
                tp_ratio=float(os.getenv("TP_RATIO", 0.55)),
                sl_mult=float(os.getenv("SL_MULT", 1.2)),
                close_before_expiry_hours=int(os.getenv("CLOSE_BEFORE_EXPIRY_HOURS", 24)),
                min_dte=int(os.getenv("MIN_DTE", 7)),
                max_dte=int(os.getenv("MAX_DTE", 10)),
                min_iv_percentile=float(os.getenv("MIN_IV_PERCENTILE", 30)),
                short_delta_target=float(os.getenv("SHORT_DELTA_TARGET", 0.12)),
                wing_width_percent=float(os.getenv("WING_WIDTH_PERCENT", 0.05))
            ))

        # Smart Money — segnali classici, non usa orderflow; abilitare con STRATEGY_SMART_MONEY_ENABLED=true
        if os.getenv("STRATEGY_SMART_MONEY_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(SmartMoneyConfig(
                name="Smart Money",
                time_window_start=int(os.getenv("SM_TIME_WINDOW_START", 14)),
                time_window_end=int(os.getenv("SM_TIME_WINDOW_END", 17)),
                whale_min_value=int(os.getenv("SM_WHALE_MIN_VALUE", 500000)),
                binance_symbol=os.getenv("SM_BINANCE_SYMBOL", "BTCUSDT"),
                absorption_min_vol=float(os.getenv("SM_ABSORPTION_MIN_VOL", 10.0)),
                absorption_delta_ratio=float(os.getenv("SM_ABSORPTION_DELTA_RATIO", 0.15)),
                absorption_price_threshold=float(os.getenv("SM_ABSORPTION_PRICE_THRESHOLD", 0.01)),
                risk_reward_ratio=float(os.getenv("RISK_REWARD_RATIO", 2.5)),
                leverage_max=int(os.getenv("LEVERAGE_MAX", 5))
            ))

        # W/M Formation — abilitare con WM_ENABLED=true
        if os.getenv("WM_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(WMFormationConfig.from_env())

        # NY Brings — abilitare con BRINGS_ENABLED=true
        if os.getenv("BRINGS_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(BringsStrategyConfig.from_env())

        # --- Strategie volumetriche intraday: DISABILITATE di default ---
        # Validazione multi-ciclo 4y (giu 2022 - giu 2026, proxy OHLCV +
        # real backtest 60d): edge lordo ~0, perdita media ~= costi (20bps)
        # in OGNI fase (bull e bear) e OGNI anno. Nessun set di parametri
        # testato e' profittevole. Riabilitare solo per esperimenti
        # (VB_ENABLED=true ecc.) — vedi data/research/multicycle_report.txt
        if os.getenv("VB_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(VolumeBreakoutConfig.from_env())

        if os.getenv("MR_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(MeanReversionConfig.from_env())

        if os.getenv("LIQ_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(LiqSqueezeConfig.from_env())

        if os.getenv("IS_ENABLED", "false").lower() == "true":
            cls.STRATEGIES.append(ImbalanceScalpConfig.from_env())

        # --- Strategie quantitative validate (Sep 2025 - Jun 2026) ---
        if os.getenv("TB_ENABLED", "true").lower() == "true":
            cls.STRATEGIES.append(TrendBreakdownConfig.from_env())

        if os.getenv("FS_ENABLED", "true").lower() == "true":
            cls.STRATEGIES.append(FundingSqueezeConfig.from_env())

        if os.getenv("MC_ENABLED", "true").lower() == "true":
            cls.STRATEGIES.append(MacroCoreConfig.from_env())

    @classmethod
    def validate(cls) -> bool:
        """Validate configuration"""
        errors = []

        if not cls.DERIBIT_API_KEY:
            errors.append("DERIBIT_API_KEY is required")
        if not cls.DERIBIT_API_SECRET:
            errors.append("DERIBIT_API_SECRET is required")
        if cls.DERIBIT_ENV not in ["test", "prod"]:
            errors.append("DERIBIT_ENV must be 'test' or 'prod'")

        # Validate strategies
        cls.load_strategies()
        if not cls.STRATEGIES:
            errors.append("No strategies enabled")

        for strategy in cls.STRATEGIES:
            if isinstance(strategy, IronCondorConfig):
                if strategy.initial_equity <= 0:
                    errors.append("Iron Condor: INITIAL_EQUITY must be positive")

        if errors:
            for error in errors:
                print(f"❌ Configuration error: {error}")
            return False

        return True

    @classmethod
    def display(cls):
        """Display current configuration"""
        print("=" * 60)
        print("CONFIGURATION")
        print("=" * 60)
        print(f"Environment: {cls.DERIBIT_ENV}")
        print(f"Active Strategies: {len(cls.STRATEGIES)}")
        
        for strategy in cls.STRATEGIES:
            print(f"\n[{strategy.name}]")
            if isinstance(strategy, IronCondorConfig):
                print(f"  Risk per Condor: {strategy.risk_per_condor:.1%}")
                print(f"  Max Portfolio Risk: {strategy.max_portfolio_risk:.1%}")
            elif isinstance(strategy, SmartMoneyConfig):
                print(f"  Time Window: {strategy.time_window_start}:00 - {strategy.time_window_end}:00")
                print(f"  Whale Min Value: ${strategy.whale_min_value:,.0f}")
                print(f"  Binance Symbol: {strategy.binance_symbol}")
            elif isinstance(strategy, WMFormationConfig):
                print(f"  Primary Timeframe: {strategy.primary_timeframe}")
                print(f"  Deribit Symbol: {strategy.deribit_symbol}")
            elif isinstance(strategy, BringsStrategyConfig):
                print(f"  Timeframe: {strategy.timeframe}")
                print(f"  Deribit Symbol: {strategy.deribit_symbol}")
            elif isinstance(strategy, VolumeBreakoutConfig):
                print(f"  Symbol: {strategy.symbol} | Instrument: {strategy.instrument}")
                print(f"  Vol Z threshold: {strategy.volume_zscore_threshold} | Lookback: {strategy.breakout_lookback}")
                print(f"  R/R: {strategy.rr_ratio} | SL ATR mult: {strategy.sl_atr_multiplier}")
            elif isinstance(strategy, MeanReversionConfig):
                print(f"  Symbol: {strategy.symbol} | Instrument: {strategy.instrument}")
                print(f"  VWAP Z threshold: {strategy.vwap_z_threshold} | R/R: {strategy.rr_ratio}")
            elif isinstance(strategy, LiqSqueezeConfig):
                print(f"  Symbol: {strategy.symbol} | Instrument: {strategy.instrument}")
                print(f"  Liq volume threshold: {strategy.liq_volume_threshold} BTC | R/R: {strategy.rr_ratio}")
            elif isinstance(strategy, ImbalanceScalpConfig):
                print(f"  Symbol: {strategy.symbol} | Instrument: {strategy.instrument}")
                print(f"  Imbalance long: {strategy.imbalance_threshold_long} | short: {strategy.imbalance_threshold_short}")
                print(f"  TP: {strategy.tp_pct:.1%} | SL: {strategy.sl_pct:.1%}")
        print("=" * 60)

if __name__ == "__main__":
    if Config.validate():
        Config.display()
