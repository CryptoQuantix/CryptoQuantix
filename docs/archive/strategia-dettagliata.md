Perfetto, ti preparo un “mini-manuale” della strategia, così puoi anche riciclarlo altrove.

---

# Strategia “Short Iron Condor Crypto 7–10 DTE”

*(versione API-friendly, rischio definito, capitale ~10.000$)*

---

## 1. Obiettivo della strategia

**Scopo:**
Usare una strategia sistematica di vendita di opzioni (“short premium”) con **rischio massimo definito** per:

* far crescere un capitale iniziale intorno a **10.000$**
* con logica di **interesse composto** (dimensione delle posizioni in % dell’equity)
* mantenendo **alta liquidità** (nessuna assegnazione di sottostante)
* in modo **API-friendly**, adatto a essere implementato con un bot.

L’idea di fondo è vendere **tempo** (theta) su sottostanti liquidi (BTC/ETH) con strutture a rischio limitato (iron condor), su scadenze brevi (7–10 giorni), con regole di entrata/uscita rigide e gestione del rischio molto conservativa.

---

## 2. Contesto operativo

### 2.1. Sottostanti

* **Bitcoin (BTC)**
* **Ethereum (ETH)**

Sono asset molto liquidi, con opzioni negoziabili su exchange tipo Deribit, che:

* hanno **opzioni European** → esercitabili solo a scadenza
* e **regolazione cash-settled** → a scadenza incassi/paghi solo il P&L in cash, senza ricevere l’asset fisico.

Questo riduce tantissimo i problemi di “assegnazione” tipici delle opzioni su azioni/ETF.

> Nota: puoi in teoria replicare la strategia anche su ETF tipo SPY/QQQ con broker opzioni classico, ma lì le opzioni sono di solito American + physical delivery, quindi il rischio assegnazione non è mai zero. Qui la formuliamo pensata per opzioni cash-settled European style (es. Deribit su BTC/ETH).

---

### 2.2. Filosofia della strategia

La strategia è una forma di:

* **short volatility / short theta** → incassi premi di opzioni
* ma con:

  * **rischio massimo limitato per trade**
  * regole di **stop loss** definite
  * **chiusura anticipata** al raggiungimento di un certo profit
  * niente posizioni a ridosso della scadenza.

Non è una strategia “tutto o niente” tipo short straddle naked 0DTE: qui l’idea è **sacrificare un po’ di rendimento potenziale per avere un profilo di rischio molto più controllabile**.

---

## 3. Struttura base: Short Iron Condor 7–10 DTE

### 3.1. Cos’è un Iron Condor (versione sintetica)

Un **iron condor** è composto da 4 opzioni sulla stessa scadenza:

1. **Short Call OTM** (venduta fuori dal denaro sopra il prezzo attuale)
2. **Long Call OTM** (comprata ancora più sopra)
3. **Short Put OTM** (venduta fuori dal denaro sotto il prezzo attuale)
4. **Long Put OTM** (comprata ancora più sotto)

Graficamente è una specie di “piattaforma” con:

* massimo profitto se il prezzo resta in un certo range centrale
* perdita massima limitata sopra un certo livello e sotto un certo livello.

### 3.2. Perché usarla

* **Rischio definito**:
  la perdita massima per condor è **nota a priori**, data dalla distanza fra strike della stessa ala − premio incassato.
* **Nessuna assegnazione fisica** (se usi opzioni European cash-settled):
  a scadenza ricevi/paghi solo un saldo in cash, niente asset consegnato.
* **Richiede meno margine** rispetto a naked short, perché il broker/exchange conosce il max loss.

---

## 4. Parametri chiave della strategia

### 4.1. Capitale e rischio

Esempio base:

* **Capitale iniziale**: 10.000$
* **Rischio massimo per condor** (max loss): **1% dell’equity** = 100$
* **Rischio massimo totale aperto**: 2–3% dell’equity (200–300$)
  ⇒ 2–3 condor aperti contemporaneamente, oppure 1 per BTC e 1 per ETH.

Questa parte è fondamentale: **l’unità di rischio è % del capitale**, non numero di contratti.

---

### 4.2. Scadenza

Per ogni nuovo setup:

* scegli una scadenza fra **7 e 10 giorni** (es. sempre il venerdì successivo)

Motivi:

* 0DTE e 1DTE hanno gamma troppo aggressiva e sono difficili da gestire in modo sistematico.
* 7–10 DTE ti dà:

  * buon **decadimento del tempo** nelle ultime due settimane
  * ma ancora margine per gestire eventuali movimenti senza essere “spazzato via” in un giorno.

---

### 4.3. Scelta degli strike (short leg basata su delta)

Per selezionare gli strike:

1. Prendi il prezzo spot del sottostante, es. BTC = 60.000$.
2. Dal chain delle opzioni per quella scadenza, scegli:

   * **Short Put** con delta circa **−0,10 / −0,15**
   * **Short Call** con delta circa **+0,10 / +0,15**

Questo, in pratica, corrisponde a strike circa 10–15% lontani dal prezzo, ma dipende da volatilità e tempo a scadenza.

3. Per le **Long Put / Long Call** (ali esterne):

   * mettile **3–5% più lontane** rispetto alle short (o scelta equivalente in termini di strike/distanza).

In questo modo:

* Le short vendono un premio non ridicolo (non troppo lontane)
* Le long limitano la perdita massima in modo netto.

---

### 4.4. Filtri di volatilità (quando NON vendere)

Short premium + bassa volatilità = prendersi il rischio di coda per pochi spicci.

Per evitare di vendere premi miseri:

* Definisci una soglia di **IV assoluta** o **IV rank**:

  * entra solo se l’**IV** (implied volatility) del sottostante è:

    * sopra una certa percentuale (es. > 50% annualizzata) **oppure**
    * sopra un certo percentile della sua storia recente (es. IV rank > 30–40%).
* Se l’IV è troppo bassa → il bot **non apre nuovi condor**.

Parametri esatti li puoi tarare con backtest, ma la logica è:

> *non vendere opzioni quando il mercato è troppo “tranquillo”*.

---

## 5. Regole operative: passo per passo

### 5.1. Routine giornaliera (setup nuovi condor)

Ogni giorno, a un orario fisso (es. 10:00 CET):

1. **Aggiorna equity**:

   * leggi il saldo complessivo del conto (in USD o equivalente)
   * calcola 1% di equity = rischio max per condor.

2. **Per ogni sottostante (BTC, ETH):**

   * misura IV / IV Rank
   * se IV < soglia → **salta** quel sottostante oggi
   * se IV ≥ soglia → puoi considerare di aprire un condor (se il rischio totale aperto lo consente).

3. **Seleziona scadenza**:

   * prendi la scadenza più vicina fra 7 e 10 giorni.

4. **Costruisci il condor**:

   * scegli gli strike come da §4.3 (short con delta ~0,10–0,15, long 3–5% più lontane).
   * calcola:

     * credito netto per contratto
     * max loss per contratto
   * dimensiona la **size** in modo che:

     * max loss totale per condor ≈ 1% equity.

5. **Invia gli ordini**:

   * Idealmente come **ordine combinato multi-leg** (se l’API lo supporta)
   * In alternativa, 4 ordini singoli con logica “tutti o niente” (se uno non viene eseguito, cancelli gli altri).

---

### 5.2. Gestione in posizione

Una volta aperto il condor, il bot deve:

1. **Monitorare P&L in tempo reale** (o a intervalli regolari, es. ogni minuto / ogni 5 minuti).
2. Applicare regole di uscita:

#### a) Take Profit (TP)

* Obiettivo: chiudere **prima** di spremere il 100% del premio, per ridurre il rischio di “evento di coda”.
* Regola tipica:

  * Se il **profitto latente** del condor ≥ **50–60% del credito incassato**, chiudi l’intera struttura.

    * Esempio: credito iniziale 200$, TP a +100–120$.

#### b) Stop Loss (SL)

* Obiettivo: tagliare le situazioni che stanno degenerando, prima di arrivare al max loss teorico.
* Regola tipica:

  * Se la **perdita latente** sul condor ≤ −**1–1,5x il credito incassato**, chiudi l’intera struttura.

    * Esempio: credito 200$, SL a −200 / −300$.

#### c) Scadenza

* Regola ferrea:

  * chiudi ogni condor **almeno 24 ore prima della scadenza**, indipendentemente da profit/loss (a meno che non sia già chiuso per TP/SL).
* Motivo:

  * le ultime 24 ore hanno gamma molto violenta, e non vuoi essere esposto al settlement.

---

### 5.3. Gestione portafoglio

A livello di portafoglio complessivo:

* **Massimo rischio aggregato aperto**: 2–3% dell’equity.
* Se hai già raggiunto questa soglia:

  * il bot non apre nuovi condor finché non chiude qualcuno di quelli esistenti (o finché l’equity non cambia).

---

## 6. Compounding: come far crescere il capitale

Il compounding è semplice e automatico se:

1. Tutti i calcoli di size sono **in % dell’equity corrente**:

   * max loss per condor = 1% * equity
   * max rischio portafoglio = 3% * equity

2. Aggiorni l’equity base **prima di ogni nuova apertura**:

   * se il conto passa da 10.000$ a 11.000$, allora:

     * 1% → 110$ (size aumenta leggermente)
   * se il conto scende a 9.000$:

     * 1% → 90$ (size si riduce → ti “autoprotegge”).

Questo è il modo sano di far lavorare l’interesse composto su un sistema a rischio definito.

---

## 7. Esempio numerico semplificato

Supponiamo:

* Equity: 10.000$
* Rischio max per condor = 1% = 100$
* BTC spot = 60.000$
* Scadenza: 8 giorni da oggi
* IV sufficiente → ok, entriamo.

### 7.1. Selezione strike (esempio inventato)

Dal chain:

* Short Put: strike 54.000 (delta ~ −0,12)
* Long Put: strike 48.000
* Short Call: strike 66.000 (delta ~ +0,12)
* Long Call: strike 72.000

Credito netto per **1 “unità” di condor** (size base) = 0,002 BTC (esempio)
Valore monetario = 0,002 * 60.000$ = 120$

Max loss per unità:

* ala put: (54.000 − 48.000) = 6.000$
* ala call: (72.000 − 66.000) = 6.000$
* max loss per 1 BTC = 6.000 − 120 = 5.880$ → ma tu non stai tradando 1 BTC di size, ma una frazione.

Per avere **max loss ~100$**:

* Size unit = 100 / 5.880 ≈ 0,017
* Quindi: apri 0,017 contratti per gamba (se l’exchange supporta frazioni, cosa che nel mondo crypto di solito sì).

### 7.2. Regole di uscita sull’esempio

* TP: 50–60% del credito → 60–72$ di profitto
* SL: 1–1,5x credito → −120 / −180$ di perdita massima tollerata
  (nel mondo reale, la mandi max a −120$ per stare nel risk budget 1–1,2% dell’equity).

---

## 8. Implementazione API (outline concettuale)

Qui ti do solo un flusso logico generico, non specifico a una libreria:

1. **Config iniziale**

   * `risk_per_condor = 0.01`
   * `max_portfolio_risk = 0.03`
   * `tp_ratio = 0.55` (55% del credito)
   * `sl_mult = 1.2` (1,2 × credito)
   * `min_dte = 7`, `max_dte = 10`
   * soglia IV / IV Rank.

2. **Funzione `scan_and_open_positions()`**

   * leggi equity
   * calcola `max_condor_risk_value = equity * risk_per_condor`
   * leggi rischio corrente già aperto
   * se rischio_corrente ≥ equity * max_portfolio_risk → **return**, non aprire.
   * per ogni sottostante (BTC, ETH):

     * calcola IV / IV Rank
     * se < soglia → continua
     * trova scadenza 7–10 DTE
     * recupera chain opzioni, trova strike short con delta target, long come da regole
     * calcola credito e max loss per size 1
     * calcola `size = max_condor_risk_value / max_loss_per_unit`
     * invia ordine multi-leg per aprire condor con quella size.

3. **Funzione `manage_open_positions()`**

   * per ogni condor aperto:

     * calcola P&L corrente (mark-to-market)
     * calcola credito iniziale (salvato al momento dell’apertura)
     * se `P&L >= tp_ratio * credit` → chiudi
     * se `P&L <= -sl_mult * credit` → chiudi
     * controlla giorni a scadenza:

       * se DTE ≤ 1 → chiudi subito.

4. Loop operativo:

   * ogni X minuti:

     * `manage_open_positions()`
   * una volta al giorno (es. 10:00):

     * `scan_and_open_positions()`

---

## 9. Rischi e limiti

È importante essere chiari:

* È una strategia **short volatilità** → soffre in:

  * movimenti esplosivi (crolli o pump).
* Anche con max loss definito, puoi avere:

  * più condor tutti in loss nella stessa fase di mercato,
  * drawdown a livello di portafoglio.
* Non è “soldi facili”:
  la robustezza si gioca su:

  * parametri scelti (distanza strike, DTE, filtri IV)
  * disciplina di TP/SL
  * dimensionamento (risk per trade/portafoglio).

Prima di usarla con soldi reali, ha senso:

* fare **backtest** su dati storici di BTC/ETH (anche solo simulazione “mid price” + costi)
* poi una fase di **paper trading / live con size microscopica**.

---

## 10. Possibili varianti/evoluzioni

Quando la base funziona, puoi pensare a:

* usare parametri diversi per BTC e ETH (ETH spesso con IV diversa)
* aggiungere un filtro direzionale (es. niente condor ribassisti in regime di forte trend up, preferendo farli più sbilanciati)
* usare condor “sbilanciati” (più vicini da un lato, più lontani dall’altro)
* combinare questa strategia con logiche di **hedging dinamico** via futures (più complesso, ma possibile).

---

Se vuoi, nel prossimo passo posso:

* trasformare questo documento in un **README.md “pronto GitHub”**
* oppure buttarti giù un **scheletro di bot in Python** (con funzioni e struttura) che implementa le regole base, così hai qualcosa di concreto da hackerare.
