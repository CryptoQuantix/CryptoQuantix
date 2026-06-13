# Le strategie attive — panoramica

!!! abstract "Validazione"

    CryptoQuantix esegue **tre strategie quantitative validate** su 4
    anni di dati multi-ciclo (giu 2022 → giu 2026: bear, bull e di nuovo
    bear), con backtest eseguiti sul **codice di produzione reale** — non
    su una reimplementazione — a costi realistici (0.20% roundtrip) e
    senza lookahead.

!!! warning "🔒 Specifiche riservate"

    **Le specifiche operative complete** (regole esatte di
    ingresso/uscita e parametri validati) **sono riservate** e
    disponibili nell'ambito di un accordo di licenza commerciale — vedi
    [licenza](#licenza-e-accesso).

Tutte le strategie implementano l'interfaccia plugin `BaseStrategy`
(`scan` / `execute_entry` / `manage_positions`) e ricevono un provider
dati **iniettabile**: lo stesso identico codice gira live e in backtest,
eliminando per costruzione la classe di bug "il backtest fa una cosa, il
live un'altra".

---

## Le tre strategie

| Strategia | Categoria | Validazione (BTC, 4 anni) |
|---|---|---|
| **Trend Breakdown** | Tattica bidirezionale macro-gated: breakdown in fase bear, breakout in fase bull | short +22 bps/trade PF 1.26 · long +68 bps PF 1.53 |
| **Funding Squeeze** | Specialista contrarian della capitolazione deep-bear (crowding del funding) | +74 bps/trade PF 2.65 · ETH +64 bps PF 1.82 |
| **Macro Core** | Posizione core di regime con uscita disciplinata e vol-targeting | +315%/4y vs +136% buy&hold, maxDD 24.7% |

Istanze live: 5 (Trend Breakdown e Funding Squeeze su BTC+ETH, Macro Core
su BTC). Ogni lato di ogni strategia è attivo SOLO sul mercato e nella
fase macro in cui ha superato la validazione.

**Portafoglio** (equity simulation 4 anni, tutte le istanze insieme):
+491% con maxDD 21.5%, Calmar 2.61, peggior anno 0.0% — dopo l'adozione
del vol-targeting sul core (testati e bocciati coi dati: Kelly frazionario
e de-risking sul drawdown).

## Il gating automatico a 3 livelli

Il sistema decide da solo cosa può tradare, quando:

| Livello | Orizzonte | Meccanismo |
|---|---|---|
| Macro | giorni-mesi | filtro di fase sul trend primario: ogni lato è strutturalmente spento nella fase avversa |
| Regime | ore | classificazione TREND/RANGE/COMPRESSION/EXPANSION con regole per strategia |
| Performance | rolling | una strategia che sotto-performa live viene disattivata automaticamente |

Guardrail live: profit factor rolling sotto soglia dopo un campione
minimo di trade → disattivazione e rivalidazione; drawdown oltre 1.5× il
massimo di backtest → disattivazione immediata.

## Il processo di validazione (perché fidarsi dei numeri)

Ogni strategia, prima del deploy, supera una pipeline rigida:

1. **Backtest sul codice reale** — il provider dati è iniettabile, il
   codice di strategia è identico tra live e simulazione
2. **4 anni multi-ciclo** — l'edge deve sopravvivere a bear, bull e
   transizioni, non a una singola fase fortunata
3. **Costi realistici** (fee + slippage) e **nessun lookahead**
4. **In-sample / out-of-sample** temporale
5. **Robustezza ai parametri vicini** — niente edge che vive solo su una
   combinazione magica
6. **Profit factor minimo** sul campione completo

## Le strategie bocciate (trasparenza)

La stessa pipeline ha **bocciato coi dati** otto strategie storiche —
restano nel codice, disattivate, col verdetto documentato:

| Strategia | Verdetto 4 anni |
|---|---|
| Volume Breakout | PF 0.42-0.74 — nessun edge, negativa in ogni fase e anno |
| Mean Reversion (VWAP fade) | PF 0.28-0.53 |
| Liquidation Squeeze | quando la cascata è visibile, il movimento è finito |
| Imbalance Scalp | fee-bound su 29k+ trade — edge lordo zero |
| NY Brings | negativa ogni anno (718 trade) |
| W/M Formation | edge non strutturale (non replica cross-asset) |
| Smart Money | componenti già falsificati |
| Iron Condor | opzioni — fuori direzione progetto |

Un sistema che pubblica anche ciò che NON funziona è un sistema di cui
puoi verificare il metodo.

## Licenza e accesso

Il codice è **source-available** con doppia licenza: libero per uso non
commerciale (incluso il trading del proprio capitale personale), mentre
**qualsiasi uso commerciale richiede una licenza a pagamento** — che
include l'accesso alle specifiche operative complete delle strategie e ai
report di validazione integrali.

Contatto: **lantoniotrento@gmail.com**
