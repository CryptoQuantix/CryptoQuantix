# CryptoQuantix

**Motore di trading quantitativo su futures/perpetual crypto** —
esecuzione su **Deribit**, dati tick-by-tick da **Binance Futures**. Tre
strategie validate su 4 anni di dati multi-ciclo, gating macro
automatico, risk management di portafoglio e dashboard operativa
completa.

<div class="grid cards" markdown>

-   :material-sitemap:{ .lg .middle } **Architettura**

    ---

    Bot asyncio, data layer iniettabile, engine di regime e scoring,
    dashboard a 6 pagine, invarianti di design.

    [:octicons-arrow-right-24: Esplora il sistema](01_architecture.md)

-   :material-strategy:{ .lg .middle } **Strategie attive**

    ---

    Trend Breakdown, Funding Squeeze, Macro Core: cosa fanno, i numeri
    della validazione e le otto strategie bocciate.

    [:octicons-arrow-right-24: Le strategie](02_strategies.md)

-   :material-tune:{ .lg .middle } **Configurazione**

    ---

    Il file `.env` a blocchi: operativo, strategie attive,
    strategie disattivate coi verdetti.

    [:octicons-arrow-right-24: Configura](03_configuration.md)

-   :material-shield-half-full:{ .lg .middle } **Risk & Sizing**

    ---

    Sizing 3-factor, cap di esposizione lorda, kill switch giornaliero,
    vol-targeting, ciclo di vita degli ordini.

    [:octicons-arrow-right-24: Il risk engine](05_risk_sizing.md)

</div>

## I numeri della validazione

!!! info "Metodologia"

    Backtest sul **codice di produzione reale** (non una
    reimplementazione), 4 anni multi-ciclo (giu 2022 → giu 2026: bear,
    bull, bear), costi 0.20% roundtrip, nessun lookahead, IS/OOS.

| | Strategia | Validazione (BTC, 4 anni) |
|---|---|---|
| :material-trending-down: | **Trend Breakdown** short | +22 bps/trade · PF 1.26 · 123 trade |
| :material-trending-up: | **Trend Breakdown** long | +68 bps/trade · PF 1.53 · 84 trade |
| :material-fire: | **Funding Squeeze** | +74 bps/trade · PF 2.65 · ETH +64 bps |
| :material-anchor: | **Macro Core** | +315%/4y vs +136% B&H · maxDD 24.7% |
| :material-chart-line: | **Portafoglio completo** | **+491%** · maxDD 21.5% · Calmar 2.61 · peggior anno 0.0% |

## Infrastruttura

<div class="grid cards" markdown>

-   :material-database:{ .lg .middle } **[Dati & Microstruttura](02_data_microstructure.md)**

    Binance WebSocket, order book L2, liquidazioni, data quality.

-   :material-waves:{ .lg .middle } **[Orderflow & CVD](03_orderflow_math.md)**

    Delta, CVD multi-timeframe, VWAP Z-score, Kyle's Lambda.

-   :material-test-tube:{ .lg .middle } **[Backtest & Monte Carlo](06_backtest_montecarlo.md)**

    Engine, metriche (Sharpe, Sortino, PF), bootstrap resampling.

-   :material-rocket-launch:{ .lg .middle } **[Esecuzione & Deploy](07_execution_ops.md)**

    API Deribit, ciclo ordini, alerting, Docker, checklist pre-live.

</div>

## Ricerca e validazione

La fonte di verità per tutti i numeri vive nel repository privato
(pipeline di validazione, report multi-ciclo, dataset 4 anni). La
documentazione pubblica linka i risultati; le specifiche operative
complete sono disponibili con licenza commerciale — vedi
[Strategie attive](02_strategies.md).

!!! warning "Licenza"

    **Source-available con doppia licenza**: libero per uso non
    commerciale (incluso il trading del proprio capitale personale) sotto
    PolyForm Noncommercial 1.0.0; **qualsiasi uso commerciale richiede
    una licenza a pagamento**.

    :material-email: **lantoniotrento@gmail.com**

!!! danger "Disclaimer"

    Il trading di futures crypto comporta rischi significativi di
    perdita. Questo software è fornito "as is", senza alcuna garanzia di
    profitto. Usalo a tuo rischio.
