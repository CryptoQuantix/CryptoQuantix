Ok, adesso ho capito cosa ti serve, non è tanto “quella strategia lì”, ma **un framework serio** che:

Usiamo Derebit come broker e quindi implelemtaremo queste API

* funzioni con **10k** (non milioni)
* sia **API-friendly**
* permetta **interesse composto**
* se usa opzioni **non ti incastri con l’assegnazione**

Ti propongo una cosa molto concreta, e poi un’alternativa “classica”.

---

## 1. Dove farla: perché secondo me Deribit è perfetto per te

Per il requisito “**no assegnazione** e sempre liquido”, le opzioni classiche USA (SPY, QQQ ecc.) sono sempre American style e a consegna fisica, quindi il rischio assegnazione *non lo puoi eliminare al 100%*, solo ridurre.

Su **Deribit**, invece:

* le opzioni su BTC/ETH sono **European style** → possono essere esercitate **solo a scadenza**, mai prima ([Deribit Insights][1])
* sono **cash-settled** → a scadenza non ricevi mai BTC/ETH “fisici” come consegna del contratto, ma solo il **P&L in cash** (BTC/ETH/USDC a seconda del contratto) ([support.deribit.com][2])
* non esiste concetto di “assegnazione” che ti riempie il conto di azioni/ETF e ti blocca margine: è solo **regolazione di cassa**.

In più:

* hanno API molto ben documentate (REST + WebSocket) e un **testnet separato** per provare i bot([docs.deribit.com][3])
* sono fatti apposta per **trading algoritmico su futures + options**.

Tu sei in Italia, quindi in genere Deribit è accessibile (non è come gli USA dove c’è un po’ di casino regolamentare, ma ovviamente tocca sempre verificare lato tuo/consulente).

Quindi: se ti va bene usare **crypto come sottostante**, Deribit ti dà esattamente:

> “Opzioni, API, niente assegnazione, cash settlement, bot-friendly”.

---

## 2. Strategia proposta: short premium **a rischio definito** su BTC/ETH (Iron Condor 7–10 DTE)

Ti scrivo una strategia pensata proprio sul tuo brief, che puoi automatizzare a step, con 10k.

### 2.1. Idea di base

* Sottostanti: **BTC** e/o **ETH** (indice spot Deribit).
* Strumento: **opzioni European, cash-settled**.
* Struttura per trade: **iron condor a rischio definito**:

  * vendi una call OTM + compri una call più OTM
  * vendi una put OTM + compri una put più OTM
* Orizzonte: **7–10 giorni di scadenza** (non 0DTE, troppo casino di gamma).
* Obiettivo: incassare **theta** in regime di volatilità “normale/alta” con:

  * rischio per trade limitato
  * niente consegna del sottostante
  * esposizione controllata.

Con 10k puoi rischiare **0,5–1% a condor** (50–100$), massimo 3–4 condor aperti → rischio totale 2–3% se proprio tutto va male insieme.

### 2.2. Regole operative (versione concreta)

#### 1) Scelta del sottostante e scadenza

Ogni giorno (o ogni 2–3 giorni), alla stessa ora (es. 10:00 CET):

1. Prendi prezzo spot e vol implicita di:

   * BTC-PERPETUAL / ETH-PERPETUAL come riferimento.
2. Scegli una scadenza **tra 7 e 10 giorni** (es. il prossimo venerdì).

(Facciamo l’esempio su BTC per semplicità.)

#### 2) Costruzione dell’iron condor

Dal chain opzioni su quella scadenza:

1. Stima la delta delle opzioni:

   * **Short put**: delta intorno a **-0,10 / -0,15**
   * **Short call**: delta intorno a **+0,10 / +0,15**
2. Scegli i long leg a **3–5% più lontani** (in termini di strike) rispetto alle short:

   * questo definisce la **larghezza del condor** e quindi il max loss.

Esempio numerico (semplificato):

* BTC = 60.000$
* Scadenza fra 8 giorni
* Short put a 54.000 (circa −10%)
* Long put a 48.000 (~−20%)
* Short call a 66.000 (+10%)
* Long call a 72.000 (+20%)

Credito netto incassato = es. 0,010 BTC → diciamo 600$ equivalenti (numeri a caso).

**Max loss** ≈ distanza fra strike (6.000$) − credito * size (attenzione alle unità → su Deribit 1 contratto = 1 BTC/ETH, ma puoi usare size molto piccole)([docs.deribit.com][4])

Tu dimensioni la size in modo che:

* **Max loss per condor ≈ 100$** (1% del conto)
* Se il max loss teorico è 1.000$, usi size 0,10, ecc.

#### 3) Filtri di volatilità (per non vendere premi ridicoli)

Per evitare di vendere gamma proprio quando il premio è troppo basso:

* entra solo se l’IV (implied volatility) di BTC/ETH è:

  * sopra una soglia minima (es. > 50% annualizzata, numeri da tarare), oppure
  * sopra un certo percentile della sua storia recente (es. IV rank > 30–40%).

Se IV è troppo bassa → non vendi, perché sei short rischio tail per pochi spicci.

#### 4) Regole di uscita

Qui sta la protezione vera (e la parte da automatizzare via API):

* **Take profit**:

  * chiudi l’intero condor quando hai incassato **50–60% del credito**.
  * Es: credito 600$, TP a 300–360$ di profitto.
* **Stop loss**:

  * chiudi se la perdita corrente raggiunge **1–1,5x il credito**.
  * Es: credito 600$, SL a −600 / −900$.
* **Scadenza**:

  * chiudi **obbligatoriamente 24 ore prima della scadenza**.
  * Anche se sei in pari o con piccolo loss, chiudi: eviti nervosismo a ridosso del settlement.

Non avendo assegnazione fisica:

* se ti dimenticassi di chiudere, a scadenza Deribit ti regola in cash, ma io metterei nel bot una regola dura: **niente posizioni in scadenza**.

#### 5) Gestione portafoglio / compounding

* Rischio per singolo condor = 1% equity (max loss)
* Rischio totale aperto ≤ 3% equity.
* Ogni settimana ricalcoli la size usando **equity aggiornata**:

  * se il conto cresce, la size aumenta (interesse composto)
  * se il conto scende, la size si riduce (protezione).

---

## 3. Come si incastra con le tue richieste

Riguardiamo il tuo brief, check-list:

1. **Capitale 10.000$, risultati “rapidi” e compounding**

   * Con 10k rischi 50–100$ a condor, 2–3 condor/sett → ritorni attesi (SE hai edge) si vedono in settimane, non anni.
   * Il compounding lo fai aggiornando la size in % equity.

2. **API-friendly**

   * Deribit è uno dei posti più API-centric del mercato (JSON-RPC over HTTP/WebSocket, testnet, esempi, SDK vari).([docs.deribit.com][3])
   * Il flusso bot è lineare:

     * fetch strumenti (`get_instruments`)([deribitexchange.gitbooks.io][5])
     * fetch book/mark price
     * calcolo strike
     * invio ordine multi-leg (o 4 ordini singoli con tag chain)
     * monitoraggio P&L / prezzo mid
     * chiusura condor a TP/SL o X giorni prima della scadenza.

3. **No assegnazione che blocca margine**

   * Opzioni european + cash-settled → nessuna consegna fisica di BTC/ETH; solo P&L in cash a scadenza.([Deribit Insights][1])
   * Tu chiudi prima, quindi ancora meno rischio di qualsiasi effetto strano a scadenza.

4. **Non IBKR, margini “umani”**

   * Con condor / vertical il **rischio è definito** → margine = max loss, non margine “assurdo” stile naked.
   * In più stai nel mondo crypto, dove i requisiti minimi in termini assoluti sono più flessibili (puoi usare size molto piccole).

5. **Liquidità per far crescere il capitale**

   * Nessuna assegnazione di azioni che ti “incolla” il margine.
   * Quando chiudi un condor, il margine si libera subito e puoi riciclarlo nella tornata successiva.

Ovviamente, NON è una “strategia vincente garantita per definizione”: short premium ha **tail risk**. Ma:

* usi **strutture a rischio definito**
* limiti il rischio per trade / per portafoglio
* chiudi prima della scadenza
* lavori in percentuale sul capitale, quindi è scalabile.

---

## 4. Alternativa non-crypto (se preferisci equity/ETF)

Se proprio non vuoi usare BTC/ETH:

* Broker tipo **Tradier** o **tastytrade** hanno API complete per opzioni su azioni/ETF USA.([Tradier API][6])
* Puoi fare una **strategia identica** su SPY / QQQ / IWM con iron condor a rischio definito, stesse regole 7–10 DTE, TP 50–60%, SL 1–1.5x credito, chiusura 1–2 giorni prima della scadenza.

Lì però:

* le opzioni sono quasi sempre **American + physical delivery**, quindi **il rischio assegnazione non è mai zero** (anche se lo riduci praticamente a niente chiudendo prima e stando OTM).

---

## 5. Prossimo step utile

Se questa idea su Deribit ti torna, nel prossimo messaggio posso:

* scriverti uno **schema preciso di API-flow** (login, fetch chain, costruzione condor, invio ordini, gestione TP/SL),
* oppure una **bozza di pseudo-codice / Python** che puoi adattare al tuo setup (tipo `deribit_client.py` + `strategy_iron_condor.py`).

Così passiamo da “strategia sulla carta” a qualcosa che puoi davvero attaccare al tuo stack.

[1]: https://insights.deribit.com/education/what-is-an-options-contract/?utm_source=chatgpt.com "What is an Options Contract"
[2]: https://support.deribit.com/hc/en-us/articles/29734325712413-Settlement?utm_source=chatgpt.com "Settlement"
[3]: https://docs.deribit.com/?utm_source=chatgpt.com "Deribit API"
[4]: https://docs.deribit.com/test/?utm_source=chatgpt.com "Naming"
[5]: https://deribitexchange.gitbooks.io/deribit-api/rpc-endpoints.html?utm_source=chatgpt.com "Endpoints · Deribit API"
[6]: https://docs.tradier.com/docs/getting-started?utm_source=chatgpt.com "Tradier Brokerage API"
