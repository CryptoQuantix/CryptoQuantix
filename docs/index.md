# Coinmaker Bot Documentation

Welcome to the documentation for the Coinmaker Trading Bot.

## Table of Contents
1. **[Architecture Overview](01_overview.md)**
   - System Design
   - Core Components (`TradingBot`, `OrderManager`, etc.)
   - Workflow

2. **[Trading Strategies](02_strategies.md)**
   - **Smart Money**: Whale Tracking & Absorption.
   - **W/M Formation**: Pattern Reversals with Vector Candle confirmation.
   - **NY Brings**: Session-based reversal trading (15:00-16:00 CET).

3. **[Configuration](03_configuration.md)**
   - Environment Variables (`.env`)
   - Strategy Parameters

## Quick Start
1. Copy `.env.example` to `.env`.
2. Fill in API Keys and select active strategies.
3. Run with Docker:
   ```bash
   ./docker-start.sh
   ```
