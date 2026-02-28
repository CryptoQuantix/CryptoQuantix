# Orderflow Engine — Matematica e Implementazione

## 1. Introduzione all'Analisi dell'Orderflow

L'**orderflow** e lo studio del flusso netto degli ordini aggressivi nel mercato. A differenza dell'analisi tecnica classica (che guarda solo OHLCV), l'orderflow divide il volume in:
- **Volume buy** (ordini market BUY che consumano liquidita sul lato ask)
- **Volume sell** (ordini market SELL che consumano liquidita sul lato bid)

Questa distinzione rivela chi e aggressivo e in quale direzione — informazione che candlestick e indicatori classici non catturano.

---

## 2. Delta e Cumulative Volume Delta (CVD)

### 2.1 Delta per Candle

Il **Delta** di una candle e la differenza tra volume buy e sell aggressivi nell'intervallo:

```
Delta = Sum(buy_volume_i) - Sum(sell_volume_i)   per tutti i trade i nella candle
```

dove:
- `buy_volume_i = quantity_i` se `is_buyer_maker = False` (aggression BUY)
- `sell_volume_i = quantity_i` se `is_buyer_maker = True`  (aggression SELL)

**Interpretazione**:
- Delta > 0 → piu volume acquistato aggressivamente → pressione rialzista
- Delta < 0 → piu volume venduto aggressivamente → pressione ribassista
- Delta = 0 → equilibrio perfetto (raro)

**Delta percentuale** (normalizzato sul volume totale):
```
Delta% = Delta / (buy_volume + sell_volume) * 100
Delta% in [-100%, +100%]
```

Delta% > 60% → forte dominanza buy; Delta% < -60% → forte dominanza sell.

### 2.2 Cumulative Volume Delta (CVD)

Il **CVD** accumula il Delta nel tempo, creando una curva che mostra la tendenza netta dell'orderflow:

```
CVD(t) = Sum_{i=0}^{t} Delta_i
```

Il CVD e calcolato su piu timeframe (1m, 5m, 15m) tramite finestre temporali scorrevoli:

```python
# Pseudo-codice (implementazione in orderflow.py)
class Accumulator:
    def __init__(self, window_sec: int):
        self.window_sec = window_sec
        self.buffer = deque()  # (timestamp_ms, delta)
        self.cvd = 0.0

    def update(self, timestamp_ms: int, buy_vol: float, sell_vol: float):
        delta = buy_vol - sell_vol
        self.buffer.append((timestamp_ms, delta))
        self.cvd += delta
        # Rimuovi eventi fuori finestra
        cutoff = timestamp_ms - self.window_sec * 1000
        while self.buffer and self.buffer[0][0] < cutoff:
            _, old_delta = self.buffer.popleft()
            self.cvd -= old_delta
```

**Timeframe implementati**:
- `cvd_1m` : CVD ultimo minuto (segnale di momentum a brevissimo termine)
- `cvd_5m` : CVD ultimi 5 minuti (conferma di trend)
- `cvd_15m`: CVD ultimi 15 minuti (contesto strutturale)

**Divergenza CVD/Prezzo** — segnale importante:
- Prezzo sale, CVD scende → il rialzo non e supportato da flow → possibile inversione
- Prezzo scende, CVD sale → il ribasso non e supportato da flow → possibile rimbalzo

---

## 3. Volume Weighted Average Price (VWAP) e VWAP Z-Score

### 3.1 VWAP Intraday

Il VWAP e il prezzo medio ponderato per il volume nella sessione corrente:

```
VWAP = Sum(price_i * volume_i) / Sum(volume_i)
```

dove i e ogni singolo trade. Implementato con running sum:

```
VWAP(t) = (Sum_{i=0}^{t} P_i * Q_i) / (Sum_{i=0}^{t} Q_i)
         = (PQ_cumulative) / (V_cumulative)
```

Il VWAP e il **prezzo di equilibrio istituzionale**: grandi player (fondi, prop desk) spesso usano il VWAP come benchmark per i loro ordini (VWAP execution algorithms). Prezzo >> VWAP → mercato ha comprato caro rispetto alla media.

### 3.2 Micro-VWAP (rolling 5 minuti)

Il **Micro-VWAP** e un VWAP su finestra mobile recente, piu sensibile alle variazioni di breve:

```python
micro_vwap_window = deque(maxlen=300)  # ultimi 300 trade (~5 minuti per BTCUSDT)
for trade in micro_vwap_window:
    pq_sum += trade.price * trade.quantity
    vol_sum += trade.quantity
micro_vwap = pq_sum / vol_sum
```

### 3.3 VWAP Z-Score

Il **VWAP Z-Score** misura quanto il prezzo corrente e lontano dal VWAP in termini di deviazione standard:

```
vwap_z = (P_current - VWAP) / std(P_i - VWAP_i  per ultimi N trade)
```

Valori tipici per BTCUSDT futures:
- |vwap_z| < 1.0 → prezzo vicino al VWAP (zona neutra)
- 1.0 < |vwap_z| < 2.0 → estensione moderata
- |vwap_z| > 2.0 → estensione significativa → potenziale mean reversion

La strategia **MeanReversion** usa `vwap_z > 2.0` come condizione di ingresso contro-trend.

---

## 4. Aggression Ratio e Absorption

### 4.1 Aggression Ratio

```
Aggression Ratio = buy_volume_N / (buy_volume_N + sell_volume_N)
```

calcolato sugli ultimi N secondi (default 300s = 5 minuti).

- AR > 0.6 → dominanza buy aggressiva → pressione rialzista sostenuta
- AR < 0.4 → dominanza sell aggressiva → pressione ribassista sostenuta
- AR ~0.5 → equilibrio → mercato in attesa

Differenza con OBI:
- OBI misura l'intenzione (ordini limite in book)
- AR misura l'azione (ordini eseguiti aggressivamente)

Spesso divergono: OBI alto + AR basso → wall di liquidita sul bid sta assorbendo sell. Scenario di accumulo.

### 4.2 Absorption (Segnale di Inversione)

L'**assorbimento** si verifica quando un lato del libro assorbe grandi quantita di ordini aggressivi senza che il prezzo si muova proporzionalmente. E un segnale che operatori size (spesso istituzionali) stanno comprando/vendendo contro il flow retail.

**Algoritmo di detection**:
```python
def _detect_absorption(self, candle) -> bool:
    """
    Assorbimento buy: delta fortemente negativo (molto sell) ma close >= open (prezzo non e sceso)
    → i compratori hanno assorbito tutto il sell senza cedere terreno
    """
    delta_pct = candle.delta / candle.volume if candle.volume > 0 else 0
    price_change = (candle.close - candle.open) / candle.open

    # Caso 1: forte sell flow ma prezzo tiene (bull absorption)
    if delta_pct < -0.3 and price_change >= -0.001:  # -30% delta, max -0.1% prezzo
        return True

    # Caso 2: forte buy flow ma prezzo non sale (bear absorption — top)
    if delta_pct > 0.3 and price_change <= 0.001:
        return True

    return False
```

L'assorbimento e uno dei segnali piu affidabili in microstrutttura perche indica la presenza di un "muro invisibile" nel book che non appare nel L2 ma si manifesta nel flow.

---

## 5. Kyle's Lambda — Price Impact

### 5.1 Teoria

**Kyle's Lambda** (da Albert Kyle, 1985, "Continuous Auctions and Insider Trading", *Econometrica*) e la misura dell'**impatto del prezzo per unita di volume netto**:

```
Delta_P = lambda * Q_net + epsilon
```

dove:
- `Delta_P` = variazione di prezzo
- `Q_net` = volume netto (buy - sell) nel periodo
- `lambda` = price impact coefficient (Kyle's Lambda)
- `epsilon` = componente casuale

Lambda elevato → mercato illiquido → ogni unita di volume aggiuntiva muove molto il prezzo.
Lambda basso → mercato liquido → grande volume necessario per spostare il prezzo.

### 5.2 Stima con OLS su Finestra Scorrevole

Stimiamo Lambda tramite OLS (Ordinary Least Squares) su una finestra di N candle:

```
Lambda_hat = Cov(Delta_P, Q_net) / Var(Q_net)
```

che e il coefficiente di regressione di Delta_P su Q_net (regressione passante per l'origine).

**Implementazione** (`src/engine/orderflow.py`):
```python
def _compute_kyle_lambda(self, symbol: str) -> float:
    """
    Stima Kyle's Lambda su rolling window di candle 1m.
    Lambda = Cov(dP, Q_net) / Var(Q_net)
    """
    history = self._kyle_buffer.get(symbol, deque(maxlen=100))
    if len(history) < 20:
        return 0.0

    dp   = np.array([h["price_change"] for h in history])   # Delta P
    qnet = np.array([h["net_volume"] for h in history])      # Q_net = buy_vol - sell_vol

    var_q = np.var(qnet)
    if var_q < 1e-10:  # degenere: nessuna variazione di volume
        return 0.0

    cov_dpq = np.cov(dp, qnet)[0, 1]
    return cov_dpq / var_q  # stima OLS
```

**Buffer aggiornato** ogni candle finalizzata:
```python
self._kyle_buffer[symbol].append({
    "price_change": close - open,       # Delta P in USD
    "net_volume":   buy_vol - sell_vol  # Q_net in BTC
})
```

### 5.3 Interpretazione Operativa

| Kyle's Lambda | Interpretazione | Azione |
|---------------|----------------|--------|
| < 0.001 | Liquidita eccellente, basso impatto | Position size normale |
| 0.001 - 0.005 | Liquidita normale | Position size normale |
| 0.005 - 0.01 | Liquidita ridotta | Ridurre size |
| > 0.01 | Mercato illiquido | Evitare market order, usare limit |

Lambda negativo: raro, indica mean reversion del prezzo rispetto al flow (tipico in mercati molto liquidi con market maker aggressivi).

**Formula inversa** — stima dello slippage atteso per un ordine di quantita Q:
```
Expected_slippage = Lambda * Q  (in USD per BTC)
```

Esempio: Lambda = 0.003, ordine da 5 BTC → slippage atteso = 0.003 * 5 = 0.015 USD/BTC = $0.015 su un prezzo di $64500 ≈ 0.023 bps (trascurabile per BTCUSDT perpetual).

---

## 6. Volume Z-Score

Il **Volume Z-Score** misura quanto il volume di una candle e anomalo rispetto alla storia recente:

```
volume_z = (V_current - mean(V_{t-N:t})) / std(V_{t-N:t})
```

calcolato su una rolling window di N candle (default 50).

Utilizzi:
- `volume_z > 2` → spike di volume → potenziale breakout genuino
- `volume_z < -1` → volume basso → segnali poco affidabili (liquidita ridotta)
- La strategia VolumeBreakout richiede `volume_z > 2.0` per filtrare falsi breakout

---

## 7. MarketSnapshot — Output Unificato

L'`OrderflowEngine` produce un `MarketSnapshot` ogni volta che viene richiesto, che aggrega tutte le metriche calcolate:

```python
@dataclass
class MarketSnapshot:
    symbol: str
    timestamp_ms: int
    price: float                   # ultimo prezzo

    # CVD multi-timeframe
    cvd_1m: float                  # CVD ultimo minuto
    cvd_5m: float                  # CVD ultimi 5 minuti
    cvd_15m: float                 # CVD ultimi 15 minuti

    # Order book
    book_imbalance: float          # OBI top 10 [0,1]

    # Flow metrics
    aggression_ratio: float        # AR 5 minuti [0,1]
    volume_zscore: float           # Z-score volume (rolling 50 candle)
    vwap_z: float                  # VWAP Z-score
    micro_vwap: float              # Micro-VWAP 5 minuti

    # Open Interest
    oi_change_pct: float           # variazione OI% rispetto snapshot precedente

    # Microstructure
    kyle_lambda: float             # price impact coefficient
    is_absorption: bool            # segnale di assorbimento
    is_liq_vacuum: bool            # vacuum di liquidita nel book
    is_volume_spike: bool          # volume_zscore > 2.5

    # Liquidazioni aggregate 10 minuti
    liq_buy_volume_10m: float      # volume liquidazioni short (short squeeze)
    liq_sell_volume_10m: float     # volume liquidazioni long (long dump)
```

Il snapshot e il contratto di interfaccia tra il layer di dati e le strategie. Ogni strategia legge solo i campi di cui ha bisogno.

---

## 8. Complessita Computazionale

| Operazione | Complessita | Note |
|------------|-------------|------|
| `update_from_trade()` | O(1) | Solo append su deque |
| `update_from_book()` | O(1) | Copia snapshot |
| `_finalize_candle()` | O(K) | K = candle history size (50) per Z-score |
| `_compute_kyle_lambda()` | O(N) | N = buffer size (100), eseguito ogni candle |
| `get_snapshot()` | O(1) | Ritorna ultima snapshot cached |
| `get_candle_history()` | O(N) | N = numero candle richieste |
| `flush_snapshot()` | O(K) | Forza finalizzazione candle incompleta |

Il bottleneck non e il calcolo (tutto O(N) con N piccolo) ma il parsing del JSON dal WebSocket. Per volumi estremi (>10k msg/s) si potrebbe usare msgpack o protocol buffers.
