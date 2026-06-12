# Piano di deploy — Raspberry Pi + Docker + Cloudflare Tunnel

> **Data**: 2026-06-12 · **Esecuzione prevista**: 2026-06-13
> **Obiettivo**: sostituire il coinmaker attuale sul Raspberry con la
> versione nuova (bot async TB/FS/MC + dashboard 6 pagine + collector C8),
> dashboard raggiungibile da un sottodominio via Cloudflare Tunnel.
> **Vincolo non negoziabile**: i dati (journal, positioning C8, state,
> .env) devono sopravvivere a QUALSIASI incidente Docker.

---

## 0. Prerequisiti sul Raspberry (verificare PRIMA di iniziare)

```bash
uname -m            # DEVE dire aarch64 (OS 64-bit; armv7l 32-bit = NO: pandas/scipy ingestibili)
docker --version && docker compose version   # compose v2 (plugin)
git --version
sudo apt install -y sqlite3                  # per i backup consistenti dei .db
cloudflared --version                        # tunnel gia' attivo sul host (assunto)
free -h             # >= 4GB consigliati (bot ~0.5GB + dashboard ~0.5GB)
df -h               # >= 5GB liberi (immagine ~1.5GB + dati + backup)
```

## 1. Cosa è già pronto nel repo (preparato il 12/06)

| Artefatto | Cosa fa |
|---|---|
| `Dockerfile` | multi-arch (arm64 ok), un'immagine per tutti i servizi, CMD = bot async |
| `docker-compose.yml` | 3 servizi: **bot** (trading), **dashboard** (Streamlit :8501 solo su localhost), **collector** (C8 ridondante ogni 6h) + cloudflared opzionale commentato |
| `scripts/backup_data.sh` | backup host giornaliero con snapshot SQLite consistenti |
| `env_editor` patch | i backup del .env finiscono in `data/env_backups/` (env `ENV_BACKUP_DIR`, già settata nel compose) → persistenti |

### Decisioni di design da NON cambiare (e perché)

1. **Niente `env_file:` nel compose.** Il bot legge il FILE `.env` con
   `load_dotenv()` all'avvio. `env_file:` inietterebbe i valori
   nell'ambiente del container alla creazione e `load_dotenv` non
   sovrascrive le variabili esistenti → l'editor della dashboard
   diventerebbe inefficace. Col bind mount del file, il flusso
   *edit → richiesta riavvio → restart* funziona end-to-end.
2. **`restart: unless-stopped` È il supervisor del riavvio**: la dashboard
   scrive la flag, il management loop del bot esce pulito entro ~30s,
   Docker rilancia il container che rilegge il .env. Nessun cron/systemd extra.
3. **Bind mount, non named volumes**: `./data`, `./logs`, `./.env` vivono
   sul filesystem del Pi. `docker compose down -v`, ricreare i container,
   perfino disinstallare Docker NON li tocca.
4. **L'editor .env scrive in place (stesso inode)**: non sostituirlo mai
   con atomic-replace, romperebbe il bind mount di singolo file.

## 2. Persistenza — la mappa di cosa vive dove

| File/dir (host) | Contenuto | Persiste a |
|---|---|---|
| `./data/journal.db` | storico trade (fonte dashboard) | tutto tranne `rm` sul host |
| `./data/positioning_history.db` | **archivio C8 — INSOSTITUIBILE** (serie dal 12/05/2026, Binance non la ridà) | idem + backup §7 |
| `./data/signal_log.db` | segnali eseguiti/bloccati | idem |
| `./data/macro_core_state.json` | posizione core MC (vive mesi!) | idem |
| `./data/scoring_state.json` | scoring rolling strategie | idem |
| `./data/env_backups/` | backup .env dell'editor dashboard | idem |
| `./data/flags/` | kill switch manuale / restart request | idem |
| `./.env` | configurazione + CHIAVI | idem + backup §7 |
| `./logs/` | log bot, positions.log, audit dashboard | idem |
| immagine/container | solo CODICE | niente — ricostruibile da git |

**Test della tesi** (da fare a fine deploy, §8): `docker compose down`,
cancella i container, `docker compose up -d` → tutto riparte con gli
stessi dati.

## 3. Migrazione dal coinmaker attuale

> Il vecchio container gira con `main.py` (bot sync legacy). Da sostituire
> integralmente. **Punto delicato: lo stato.**

1. **Quando migrare**: idealmente con le tattiche FLAT (TB/FS tengono lo
   stato del trade in memoria: si perde comunque a ogni restart; gli SL/TP
   sul venue proteggono, ma il time-exit del trade in corso andrebbe perso).
   MacroCore invece persiste su file → va portato.
2. Sul Pi, nella dir del VECCHIO coinmaker:
   ```bash
   docker compose down            # o docker stop <vecchio container>
   tar czf ~/coinmaker_old_$(date +%Y%m%d).tar.gz data/ logs/ .env   # cintura di sicurezza
   ```
3. Decidere cosa portare nel nuovo deployment:
   - `data/macro_core_state.json` — **SÌ se MC è in posizione** (altrimenti il bot non sa di avere il core aperto)
   - `data/journal.db`, `data/signal_log.db` — sì se vuoi continuità dello storico
   - `data/scoring_state.json` — sì (memoria performance rolling)
   - `data/positioning_history.db` — **PORTALO se l'hai copiato dal PC** (vedi §4.3): è l'archivio C8 col backfill del 12/06
   - `.env` — NO: usa quello nuovo (riordinato, con i parametri validati)

## 4. Deploy passo-passo

### 4.1 Codice
```bash
cd ~ && git clone <URL_REPO> coinmaker-quant && cd coinmaker-quant
# (o git pull se gia' clonato)
```

### 4.2 Configurazione
```bash
# Trasferisci il .env dal PC (gitignored, non viaggia con git) — via scp:
#   scp .env pi@raspberry:~/coinmaker-quant/.env
nano .env    # verifica: DERIBIT_ENV (test finche' non validi il deploy!),
             # chiavi presenti, TB/FS/MC_ENABLED, POSITIONING_ENABLED=true
chmod 600 .env
```

### 4.3 Dati iniziali
```bash
mkdir -p data logs
# ARCHIVIO C8 dal PC (contiene il backfill 31gg del 12/06 — da non perdere):
#   scp data/positioning_history.db pi@raspberry:~/coinmaker-quant/data/
# Stato/journal dal vecchio deployment (vedi §3.3):
#   cp ~/vecchio-coinmaker/data/macro_core_state.json data/  (se MC in posizione)
```

### 4.4 Build e avvio
```bash
docker compose build          # prima build su Pi4: 10-20 min
docker compose up -d
docker compose ps             # 3 servizi: bot, dashboard, collector → healthy
docker compose logs -f bot    # bootstrap: auth Deribit OK, task avviati, scan iniziale
docker compose logs collector # [OK] copertura archivio C8
curl -s http://127.0.0.1:8501/_stcore/health   # → ok
```

### 4.5 Verifiche funzionali (prima di esporre online)
```bash
# Dashboard via SSH port-forward dal PC:
#   ssh -L 8501:127.0.0.1:8501 pi@raspberry   → http://localhost:8501
```
- [ ] "Trade in corso": equity visibile, riconciliazione OK
- [ ] "Rischio & Esposizione": numeri sensati, matrice macro popolata
- [ ] "Contesto Mercato": pannello C8 con staleness < 12h
- [ ] "Impostazioni": modifica banale (es. LOG_LEVEL) → backup in
      `data/env_backups/` → richiesta riavvio → `docker compose ps` mostra
      il bot riavviato → log con nuovo livello → ripristina il valore

## 5. Cloudflare Tunnel — sottodominio per la dashboard

### Opzione A (consigliata): cloudflared già attivo sul host
```bash
# 1. Aggiungi l'ingress nel config del tunnel esistente
#    (di solito /etc/cloudflared/config.yml), PRIMA della regola catch-all:
nano /etc/cloudflared/config.yml
```
```yaml
ingress:
  - hostname: coinmaker.TUODOMINIO.com
    service: http://localhost:8501
  # ... eventuali altri hostname esistenti ...
  - service: http_status:404
```
```bash
# 2. Rotta DNS per il sottodominio sul tunnel esistente:
cloudflared tunnel route dns <NOME_TUNNEL> coinmaker.TUODOMINIO.com
# 3. Riavvia il servizio:
sudo systemctl restart cloudflared
```

### Opzione B: cloudflared come servizio compose
Decommentare il blocco `cloudflared` nel docker-compose.yml, creare
`.env.cloudflared` con `TUNNEL_TOKEN=...` (dashboard Zero Trust → Tunnels),
e nel tunnel remoto configurare il public hostname
`coinmaker.TUODOMINIO.com → http://dashboard:8501` (nome del servizio
compose, stessa network).

## 6. ⚠️ SICUREZZA — OBBLIGATORIO PRIMA DI ANDARE ONLINE

**La dashboard NON ha autenticazione propria e può: chiudere posizioni,
attivare il kill switch, modificare il .env, riavviare il bot.** Un
sottodominio pubblico senza protezione = chiunque può operare sul conto.

**Cloudflare Access (Zero Trust, gratuito fino a 50 utenti):**
1. Dashboard Cloudflare → Zero Trust → Access → Applications → **Add an
   application** → Self-hosted
2. Application domain: `coinmaker.TUODOMINIO.com`
3. Policy: *Allow* → Include → **Emails** → la tua email (lantoniotrento@gmail.com)
4. Session duration: 24h. Login via OTP email (o Google SSO se configurato).

Check finale: aprire il sottodominio in **incognito** → DEVE chiedere il
login Access prima di mostrare qualunque cosa. Senza questo passaggio il
deploy NON va considerato completo.

Difese aggiuntive già in essere: porta 8501 bindata su 127.0.0.1 (non
raggiungibile dalla LAN), secrets mai mostrati dalla UI, azioni con
conferma doppia + audit log (`logs/dashboard_actions.log`).

## 7. Backup automatico (il "se cancello Docker non perdo niente")

```bash
chmod +x scripts/backup_data.sh
./scripts/backup_data.sh                  # test manuale: crea ~/backups/coinmaker/coinmaker_data_<ts>.tar.gz
crontab -e
# aggiungi:
15 3 * * * /home/pi/coinmaker-quant/scripts/backup_data.sh >> /home/pi/backups/coinmaker/backup.log 2>&1
```
- Snapshot **consistenti** dei .db via `sqlite3 .backup` (sicuro anche a bot acceso)
- Retention 14 giorni, dentro l'archivio: tutti i .db, state JSON,
  env_backups, flags e il .env
- **Fortemente consigliato l'offsite**: il backup sulla stessa SD del Pi
  non protegge dalla morte della SD (causa #1 di morte dei Raspberry).
  Decommentare la riga `rclone` nello script dopo `rclone config`
  (Drive/Dropbox/S3), oppure montare una USB e puntare
  `COINMAKER_BACKUP_DIR` lì.
- Il check trimestrale C8 (set 2026) include la verifica che questi
  backup esistano e siano ripristinabili.

## 8. Collaudo finale del piano di disastro (10 minuti, da fare davvero)

```bash
docker compose down            # spegne e RIMUOVE i container
docker compose up -d           # ricrea da zero
```
- [ ] bot riparte e si autentica; MC state ancora presente
- [ ] dashboard: storico trade intatto, pannello C8 con la stessa copertura
- [ ] `python scripts/collect_positioning.py --status` dentro il container
      (`docker compose exec collector python scripts/collect_positioning.py --status`)
      → giorni coperti invariati
- [ ] estrai un backup di prova: `tar tzf ~/backups/coinmaker/coinmaker_data_*.tar.gz | head`

## 9. Operatività quotidiana (cheat sheet)

```bash
docker compose ps                         # stato servizi + health
docker compose logs -f bot                # log live del bot
docker compose logs --tail 50 collector   # ultima passata C8
docker compose restart bot                # riavvio manuale bot
docker compose exec bot python scripts/collect_positioning.py --status
# Aggiornamento codice:
git pull && docker compose build && docker compose up -d
# (i dati non si toccano: sono bind mount)
```
- Riavvio "morbido" del bot: dashboard → Impostazioni → Richiedi riavvio
- Kill switch manuale: dashboard → Azioni (o `touch data/flags/kill_switch_manual.flag` — meglio dalla UI che scrive anche l'audit)

## 10. Troubleshooting Pi

| Problema | Causa probabile | Fix |
|---|---|---|
| build lentissima / pip compila | wheel aarch64 mancante per una lib | aspettare (gcc c'è); su armv7l invece NON partire proprio: serve OS 64-bit |
| OOM / container killed | Pi con poca RAM | alzare swap (`dphys-swapfile`), o togliere i `limits` dal compose |
| `database is locked` sporadico nei log collector | bot e collector scrivono insieme | innocuo: INSERT OR REPLACE idempotente, la passata dopo recupera |
| orario sbagliato nei log / kill switch resetta a ore strane | TZ host | l'immagine ha TZ=Europe/Rome; verificare anche `timedatectl` sul host |
| dashboard lenta da remoto | Streamlit via tunnel | normale al primo load; cache delle pagine fa il resto |
| `cloudflared` non instrada | regola ingress dopo il catch-all | l'hostname deve stare PRIMA di `http_status:404` |

---

## Checklist stampabile per domani

1. ⬜ Prerequisiti Pi verificati (§0, in particolare `aarch64`)
2. ⬜ Vecchio coinmaker fermato + tar di sicurezza (§3)
3. ⬜ Clone repo + `.env` via scp + `chmod 600` (§4.1-4.2)
4. ⬜ `positioning_history.db` copiato dal PC (§4.3) ← **archivio C8!**
5. ⬜ State da migrare copiati (MC state se in posizione) (§3.3)
6. ⬜ Build + up + 3 servizi healthy (§4.4)
7. ⬜ Verifiche funzionali via SSH tunnel (§4.5)
8. ⬜ Ingress cloudflared + rotta DNS sottodominio (§5)
9. ⬜ **Cloudflare Access attivo e testato in incognito (§6)** ← prima di tutto il resto online
10. ⬜ Backup: script testato + cron + offsite (§7)
11. ⬜ Collaudo disastro: down/up senza perdite (§8)
12. ⬜ `DERIBIT_ENV`: decidere test/prod e annotare la decisione
