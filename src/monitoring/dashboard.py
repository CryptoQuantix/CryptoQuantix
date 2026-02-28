"""
TradingDashboard — Streamlit-based live monitoring dashboard.

Panels:
  1. Equity curve + daily P&L
  2. Current regime (per symbol) + confidence gauge
  3. Orderflow: CVD chart, delta heatmap, imbalance indicator
  4. Open positions summary
  5. Strategy scores table
  6. Recent trades log
  7. System health (API status, FailureHandler, queue sizes)

Run with:
    streamlit run src/monitoring/dashboard.py -- --port 8501

Or programmatically:
    dashboard = TradingDashboard(bot_state)
    dashboard.run()
"""
import logging
import os
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Optional Streamlit dependency
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    HAS_STREAMLIT = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


class TradingDashboard:
    """
    Streamlit dashboard for live monitoring.

    Can be run as standalone script or embedded.
    If Streamlit is not available, falls back to periodic console logging.
    """

    def __init__(
        self,
        bot=None,
        refresh_interval_sec: float = 5.0,
        title: str = "CoinMaker Quant — Live Dashboard",
    ):
        self.bot = bot
        self.refresh_interval_sec = refresh_interval_sec
        self.title = title

    def run(self):
        """Launch the Streamlit dashboard."""
        if not HAS_STREAMLIT:
            logger.warning(
                "[Dashboard] Streamlit not installed — pip install streamlit>=1.30.0"
            )
            self._console_dashboard()
            return

        self._render_streamlit()

    def _render_streamlit(self):
        """Render full Streamlit dashboard."""
        st.set_page_config(
            page_title=self.title,
            page_icon="📊",
            layout="wide",
            initial_sidebar_state="expanded",
        )

        st.title(f"📊 {self.title}")
        st.caption(f"Last update: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # Auto-refresh
        if HAS_STREAMLIT:
            from streamlit_autorefresh import st_autorefresh  # type: ignore
            try:
                st_autorefresh(interval=int(self.refresh_interval_sec * 1000), key="autorefresh")
            except ImportError:
                st.info("Install streamlit-autorefresh for auto-refresh: pip install streamlit-autorefresh")

        # Layout: 3 columns at top
        col1, col2, col3 = st.columns(3)

        with col1:
            self._render_equity_panel()

        with col2:
            self._render_regime_panel()

        with col3:
            self._render_health_panel()

        # Middle row: orderflow + positions
        col4, col5 = st.columns([2, 1])
        with col4:
            self._render_orderflow_panel()
        with col5:
            self._render_positions_panel()

        # Bottom: strategy scores + trade log
        col6, col7 = st.columns([1, 2])
        with col6:
            self._render_scores_panel()
        with col7:
            self._render_trade_log()

    def _render_equity_panel(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("💰 Equity")
        data = self._get_equity_data()
        if data:
            equity = data.get("equity", 0)
            daily_pnl = data.get("daily_pnl", 0)
            pnl_pct = data.get("daily_pnl_pct", 0)
            st.metric(
                "Equity",
                f"${equity:,.2f}",
                delta=f"${daily_pnl:+,.2f} ({pnl_pct:+.2f}%) today",
            )
            if HAS_PLOTLY and HAS_PANDAS and data.get("equity_history"):
                df = pd.DataFrame(data["equity_history"])
                fig = px.line(df, x="timestamp", y="equity", title="Equity Curve")
                fig.update_layout(height=200, margin=dict(l=0, r=0, t=30, b=0))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No equity data")

    def _render_regime_panel(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("🔀 Market Regime")
        regimes = self._get_regimes()
        for symbol, regime_data in regimes.items():
            regime = regime_data.get("regime", "UNKNOWN")
            confidence = regime_data.get("confidence", 0)
            color = self._regime_color(regime)
            st.markdown(
                f"**{symbol}**: :{color}[{regime}] ({confidence:.0%} confidence)"
            )
            st.progress(confidence)

    def _render_health_panel(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("🏥 System Health")
        health = self._get_health()
        status = health.get("api_healthy", False)
        st.markdown(f"**API Status**: {'🟢 OK' if status else '🔴 DOWN'}")
        st.markdown(f"**Uptime**: {health.get('uptime', 'N/A')}")
        st.markdown(f"**Trades today**: {health.get('trades_today', 0)}")
        if health.get("kill_switch"):
            st.error("🛑 KILL SWITCH ACTIVE")

    def _render_orderflow_panel(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("📈 Orderflow")
        of_data = self._get_orderflow()
        if of_data and HAS_PLOTLY and HAS_PANDAS:
            cols = st.columns(3)
            with cols[0]:
                st.metric("CVD 1m", f"{of_data.get('cvd_1m', 0):+.4f}")
                st.metric("CVD 5m", f"{of_data.get('cvd_5m', 0):+.4f}")
            with cols[1]:
                imbalance = of_data.get("book_imbalance", 0.5)
                st.metric("Book Imbalance", f"{imbalance:.3f}")
                st.progress(imbalance)
            with cols[2]:
                st.metric("Vol Z-Score", f"{of_data.get('volume_zscore', 0):.2f}")
                st.metric("OI Change", f"{of_data.get('oi_change_pct', 0):+.2f}%")
        else:
            st.info("No orderflow data")

    def _render_positions_panel(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("📋 Open Positions")
        positions = self._get_positions()
        if positions:
            for pos in positions:
                pnl = pos.get("pnl", 0)
                pnl_color = "green" if pnl >= 0 else "red"
                st.markdown(
                    f"**{pos['instrument']}** {pos['direction']} "
                    f"x{pos['size']:.4f}  :{pnl_color}[${pnl:+,.2f}]"
                )
        else:
            st.info("No open positions")

    def _render_scores_panel(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("🎯 Strategy Scores")
        scores = self._get_scores()
        if scores and HAS_PANDAS:
            df = pd.DataFrame(scores)
            if not df.empty:
                df = df[["strategy", "score", "winrate_30d", "trades_30d", "active"]].copy()
                df.columns = ["Strategy", "Score", "WinRate", "Trades", "Active"]
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No scoring data")

    def _render_trade_log(self):
        if not HAS_STREAMLIT:
            return
        st.subheader("📜 Recent Trades")
        trades = self._get_recent_trades()
        if trades and HAS_PANDAS:
            df = pd.DataFrame(trades)
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No trades logged yet")

    # ------------------------------------------------------------------
    # Data fetchers (pull from bot state if available)
    # ------------------------------------------------------------------

    def _get_equity_data(self) -> Dict:
        if self.bot and hasattr(self.bot, "risk_manager"):
            try:
                summary = self.bot.risk_manager.get_risk_summary()
                return {
                    "equity": summary.get("equity", 0),
                    "daily_pnl": summary.get("daily_pnl", 0),
                    "daily_pnl_pct": summary.get("daily_pnl_pct", 0),
                }
            except Exception:
                pass
        return {}

    def _get_regimes(self) -> Dict:
        if self.bot and hasattr(self.bot, "regime_detector"):
            result = {}
            for sym in getattr(self.bot, "symbols", ["BTCUSDT"]):
                r = self.bot.regime_detector.get_last_regime(sym)
                if r:
                    result[sym] = {"regime": r.regime.value, "confidence": r.confidence}
            return result
        return {"BTCUSDT": {"regime": "UNKNOWN", "confidence": 0.0}}

    def _get_health(self) -> Dict:
        if self.bot and hasattr(self.bot, "failure_handler"):
            status = self.bot.failure_handler.get_status()
            return {
                "api_healthy": status.get("api_healthy", False),
                "uptime": "N/A",
                "trades_today": 0,
                "kill_switch": False,
            }
        return {"api_healthy": True, "uptime": "N/A", "trades_today": 0, "kill_switch": False}

    def _get_orderflow(self) -> Dict:
        if self.bot and hasattr(self.bot, "orderflow_engine"):
            for sym in getattr(self.bot, "symbols", ["BTCUSDT"]):
                snap = self.bot.orderflow_engine.get_snapshot(sym)
                if snap:
                    return {
                        "cvd_1m": snap.cvd_1m,
                        "cvd_5m": snap.cvd_5m,
                        "book_imbalance": snap.book_imbalance,
                        "volume_zscore": snap.volume_zscore,
                        "oi_change_pct": snap.oi_change_pct,
                    }
        return {}

    def _get_positions(self) -> List[Dict]:
        if self.bot and hasattr(self.bot, "position_monitor"):
            try:
                positions = self.bot.position_monitor.get_open_futures_positions()
                return [
                    {
                        "instrument": p.get("instrument_name", ""),
                        "direction": "LONG" if p.get("direction") == "buy" else "SHORT",
                        "size": abs(p.get("size", 0)),
                        "pnl": p.get("floating_profit_loss", 0),
                    }
                    for p in positions
                ]
            except Exception:
                pass
        return []

    def _get_scores(self) -> List[Dict]:
        if self.bot and hasattr(self.bot, "scoring_engine"):
            current_regime = "UNKNOWN"
            try:
                return self.bot.scoring_engine.get_summary_table(current_regime)
            except Exception:
                pass
        return []

    def _get_recent_trades(self) -> List[Dict]:
        if self.bot and hasattr(self.bot, "trade_logger"):
            try:
                return self.bot.trade_logger.get_recent_trades(n=20)
            except Exception:
                pass
        return []

    @staticmethod
    def _regime_color(regime: str) -> str:
        colors = {
            "TREND_UP": "green",
            "TREND_DOWN": "red",
            "RANGE": "blue",
            "COMPRESSION": "orange",
            "EXPANSION": "violet",
            "UNKNOWN": "gray",
        }
        return colors.get(regime, "gray")

    # ------------------------------------------------------------------
    # Fallback console dashboard
    # ------------------------------------------------------------------

    def _console_dashboard(self):
        """Print dashboard to console every N seconds."""
        import time
        logger.info("[Dashboard] Running console mode (Streamlit not available)")
        while True:
            try:
                self._print_console_snapshot()
                time.sleep(self.refresh_interval_sec)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"[Dashboard] Console error: {e}")

    def _print_console_snapshot(self):
        """Print a snapshot of current state to console."""
        print("\n" + "=" * 60)
        print(f"DASHBOARD — {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        print("=" * 60)
        eq = self._get_equity_data()
        if eq:
            print(f"Equity: ${eq.get('equity', 0):,.2f} | Daily P&L: ${eq.get('daily_pnl', 0):+,.2f}")
        positions = self._get_positions()
        print(f"Open positions: {len(positions)}")
        regimes = self._get_regimes()
        for sym, r in regimes.items():
            print(f"{sym}: {r['regime']} ({r['confidence']:.0%})")


# ------------------------------------------------------------------
# Standalone entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    # When run as: streamlit run src/monitoring/dashboard.py
    if HAS_STREAMLIT:
        dashboard = TradingDashboard()
        dashboard.run()
    else:
        print("Install streamlit: pip install streamlit>=1.30.0")
