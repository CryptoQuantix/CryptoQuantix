# 🐳 Guida Docker Completa - Coinmaker Trading Bot

Guida all'utilizzo di Docker per eseguire il bot in modo isolato e facilmente gestibile.

---

## 📋 Prerequisiti

### Installazione Docker

**Windows:**
1. Scarica [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. Installa e riavvia il computer
3. Avvia Docker Desktop
4. Verifica: `docker --version` e `docker-compose --version`

**Linux:**
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker

# Aggiungi utente al gruppo docker (per non usare sudo)
sudo usermod -aG docker $USER
# Logout e login per applicare
```

**Mac:**
1. Scarica [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)
2. Installa e avvia Docker Desktop
3. Verifica: `docker --version` e `docker-compose --version`

---

## 🏗️ Struttura Docker del Progetto

### File Docker

```
coinmaker/
├── Dockerfile                 # Definizione dell'immagine
├── docker-compose.yml         # Orchestrazione container
├── .dockerignore             # File da escludere dal build
│
├── docker-start.sh/.bat      # Avvia bot
├── docker-stop.sh/.bat       # Ferma bot
├── docker-restart.sh/.bat    # Riavvia bot
├── docker-logs.sh/.bat       # Visualizza logs
└── docker-shell.sh/.bat      # Apri shell nel container
```

### Dockerfile - Spiegazione

```dockerfile
# Multi-stage build per ottimizzare dimensioni
FROM python:3.11-slim as builder
# Stage 1: Compila dipendenze

FROM python:3.11-slim
# Stage 2: Runtime minimale

# Crea utente non-root (sicurezza)
RUN useradd -m -u 1000 -s /bin/bash botuser

# Monta volumi per persistenza dati
VOLUME ["/app/logs", "/app/data"]
```

**Vantaggi:**
- ✅ Immagine leggera (~200MB vs ~1GB)
- ✅ Build veloce con cache layers
- ✅ Sicurezza: utente non-root
- ✅ Isolamento completo

### docker-compose.yml - Spiegazione

```yaml
services:
  coinmaker-bot:
    build: .                    # Usa Dockerfile locale
    restart: unless-stopped     # Riavvio automatico
    env_file: .env             # Carica variabili ambiente
    volumes:
      - ./logs:/app/logs       # Persiste logs
      - ./data:/app/data       # Persiste dati
    deploy:
      resources:
        limits:
          cpus: '1.0'          # Max 1 CPU
          memory: 512M         # Max 512MB RAM
```

**Vantaggi:**
- ✅ Configurazione dichiarativa
- ✅ Gestione semplificata
- ✅ Limiti di risorse
- ✅ Persistenza dati

---

## 🚀 Build dell'Immagine Docker

### 1. Build Iniziale

**Windows:**
```bash
docker-compose build
```

**Linux/Mac:**
```bash
docker-compose build
```

**Output:**
```
Building coinmaker-bot
Step 1/15 : FROM python:3.11-slim as builder
 ---> abc123def456
Step 2/15 : WORKDIR /app
 ---> Using cache
...
Successfully built xyz789abc123
Successfully tagged coinmaker_coinmaker-bot:latest
```

### 2. Build con Opzioni

**Build senza cache (rebuild completo):**
```bash
docker-compose build --no-cache
```

**Build in modalità verbose:**
```bash
docker-compose build --progress=plain
```

**Build solo dell'immagine (senza Docker Compose):**
```bash
docker build -t coinmaker-bot:latest .
```

### 3. Verificare l'Immagine

**Lista immagini:**
```bash
docker images | grep coinmaker
```

Output:
```
coinmaker_coinmaker-bot   latest   xyz789abc123   2 minutes ago   201MB
```

**Ispezionare l'immagine:**
```bash
docker image inspect coinmaker_coinmaker-bot:latest
```

---

## ▶️ Esecuzione del Bot

### Modalità 1: Demone (Background)

Il bot gira in background, continua anche dopo chiusura terminale.

**Windows:**
```bash
docker-start.bat
```

**Linux/Mac:**
```bash
./docker-start.sh
```

**Oppure manualmente:**
```bash
docker-compose up -d
```

**Verifica stato:**
```bash
docker-compose ps
```

Output:
```
Name                    Command               State    Ports
----------------------------------------------------------------
coinmaker-bot   python -m src.trading_bot    Up
```

**Quando usare:**
- ✅ Produzione / Trading reale
- ✅ Server / VPS
- ✅ Bot che deve girare 24/7
- ✅ Non vuoi tenere terminale aperto

---

### Modalità 2: Interactive (Foreground)

Il bot gira in foreground, vedi logs in tempo reale.

**Avvio interactive:**
```bash
docker-compose up
```

**Output live:**
```
coinmaker-bot | 2024-11-26 10:00:00 - INFO - Starting Trading Bot
coinmaker-bot | 2024-11-26 10:00:01 - INFO - Authenticated successfully
coinmaker-bot | 2024-11-26 10:00:02 - INFO - Scanning for positions...
```

**Fermare:** `Ctrl+C`

**Quando usare:**
- ✅ Testing / Debug
- ✅ Prima esecuzione
- ✅ Vuoi vedere output in tempo reale
- ✅ Sviluppo

---

### Modalità 3: One-Shot (Esegui e Esci)

Esegui un comando singolo e esci.

**Esempio: Test connessione**
```bash
docker-compose run --rm coinmaker-bot python test_connection.py
```

**Esempio: Check opportunità**
```bash
docker-compose run --rm coinmaker-bot python scripts/check_opportunities.py
```

**Esempio: View posizioni**
```bash
docker-compose run --rm coinmaker-bot python scripts/view_positions.py
```

**Flag `--rm`:** Rimuove container dopo l'esecuzione

**Quando usare:**
- ✅ Script utility
- ✅ Test rapidi
- ✅ Comandi manuali

---

## 📊 Gestione e Monitoraggio

### Visualizzare Logs

**Logs in tempo reale (follow):**

**Windows:**
```bash
docker-logs.bat
```

**Linux/Mac:**
```bash
./docker-logs.sh
```

**Oppure:**
```bash
docker-compose logs -f
```

**Solo ultimi N log:**
```bash
docker-compose logs --tail=100
```

**Logs senza follow (snapshot):**
```bash
docker-compose logs
```

**Logs da timestamp specifico:**
```bash
docker-compose logs --since 2024-11-26T10:00:00
```

**Logs ultimi 30 minuti:**
```bash
docker-compose logs --since 30m
```

---

### Stato del Container

**Verifica se è running:**
```bash
docker-compose ps
```

**Dettagli completi:**
```bash
docker ps -a | grep coinmaker
```

**Statistiche risorse (CPU, RAM, I/O):**
```bash
docker stats coinmaker-bot
```

Output:
```
CONTAINER     CPU %   MEM USAGE / LIMIT   MEM %   NET I/O       BLOCK I/O
coinmaker-bot 0.5%    124MiB / 512MiB    24.2%   1.2kB / 856B  0B / 0B
```

**Inspect completo:**
```bash
docker inspect coinmaker-bot
```

---

### Controllo del Container

**Fermare il bot:**

**Windows:**
```bash
docker-stop.bat
```

**Linux/Mac:**
```bash
./docker-stop.sh
```

**Oppure:**
```bash
docker-compose stop
```

**Riavviare il bot:**

**Windows:**
```bash
docker-restart.bat
```

**Linux/Mac:**
```bash
./docker-restart.sh
```

**Oppure:**
```bash
docker-compose restart
```

**Pause/Unpause (congela senza fermare):**
```bash
docker-compose pause
docker-compose unpause
```

---

## 🔧 Accesso al Container

### Aprire Shell nel Container

**Windows:**
```bash
docker-shell.bat
```

**Linux/Mac:**
```bash
./docker-shell.sh
```

**Oppure:**
```bash
docker-compose exec coinmaker-bot /bin/bash
```

**Comandi utili dentro il container:**
```bash
# Verifica struttura
ls -la

# Controlla logs
cat logs/trading_bot.log

# Test connessione
python test_connection.py

# Verifica config
python config.py

# Esci dalla shell
exit
```

---

### Eseguire Comandi Singoli

**Senza entrare in shell:**
```bash
# Verifica versione Python
docker-compose exec coinmaker-bot python --version

# Lista file
docker-compose exec coinmaker-bot ls -la

# Leggi log
docker-compose exec coinmaker-bot tail -n 50 logs/trading_bot.log

# Check processo
docker-compose exec coinmaker-bot ps aux
```

---

## 🗑️ Pulizia e Rimozione

### Rimozione Base (Solo Container)

**Ferma e rimuovi container:**
```bash
docker-compose down
```

**Cosa rimuove:**
- ✅ Container coinmaker-bot
- ✅ Network coinmaker-network
- ❌ Volumi (logs, data) - **CONSERVATI**
- ❌ Immagine - **CONSERVATA**

---

### Rimozione Completa Container + Volumi

**Ferma, rimuovi container E volumi:**
```bash
docker-compose down -v
```

**Cosa rimuove:**
- ✅ Container coinmaker-bot
- ✅ Network coinmaker-network
- ✅ Volumi (logs, data) - **CANCELLATI!**
- ❌ Immagine - **CONSERVATA**

⚠️ **ATTENZIONE:** Perdi tutti i logs e dati storici!

---

### Rimozione Immagine

**Rimuovi solo immagine:**
```bash
docker rmi coinmaker_coinmaker-bot:latest
```

**Oppure con force:**
```bash
docker rmi -f coinmaker_coinmaker-bot:latest
```

**Lista tutte le immagini del progetto:**
```bash
docker images | grep coinmaker
```

---

### Rimozione TOTALE del Progetto Docker

**⚠️ CANCELLAZIONE COMPLETA ⚠️**

Questo rimuove TUTTO relativo al progetto Coinmaker Docker, ma NON tocca altri progetti Docker.

**Step 1: Ferma container**
```bash
docker-compose down -v
```

**Step 2: Rimuovi immagine**
```bash
docker rmi coinmaker_coinmaker-bot:latest
```

**Step 3: Rimuovi volumi orfani (opzionale)**
```bash
docker volume prune
# Conferma con 'y'
```

**Step 4: Verifica pulizia**
```bash
# Nessun container coinmaker
docker ps -a | grep coinmaker

# Nessuna immagine coinmaker
docker images | grep coinmaker

# Nessun volume coinmaker
docker volume ls | grep coinmaker
```

**Script All-in-One (Linux/Mac):**
```bash
#!/bin/bash
echo "Rimozione COMPLETA progetto Coinmaker..."
docker-compose down -v
docker rmi -f coinmaker_coinmaker-bot:latest 2>/dev/null
echo "✓ Pulizia completata!"
```

**Script All-in-One (Windows):**
```batch
@echo off
echo Rimozione COMPLETA progetto Coinmaker...
docker-compose down -v
docker rmi -f coinmaker_coinmaker-bot:latest
echo Pulizia completata!
pause
```

---

### Pulizia Docker Generale (ATTENZIONE!)

**⚠️ Questi comandi toccano TUTTI i progetti Docker, non solo Coinmaker!**

**Rimuovi TUTTI i container fermi:**
```bash
docker container prune
```

**Rimuovi TUTTE le immagini non usate:**
```bash
docker image prune -a
```

**Rimuovi TUTTI i volumi non usati:**
```bash
docker volume prune
```

**Rimuovi TUTTO il sistema Docker non usato:**
```bash
docker system prune -a --volumes
```

**⚠️ Usa questi comandi SOLO se sai cosa stai facendo!**

---

## 📁 Persistenza Dati

### Volumi Docker

Il progetto usa volumi per persistere i dati:

```yaml
volumes:
  - ./logs:/app/logs    # Logs persistenti
  - ./data:/app/data    # Dati persistenti
```

**Directory host → Directory container**

**Vantaggi:**
- ✅ Dati sopravvivono a restart container
- ✅ Accessibili da host (logs leggibili direttamente)
- ✅ Backup facile (copia cartelle logs/ e data/)

### Backup Logs e Dati

**Backup manuale:**
```bash
# Windows
xcopy logs logs_backup /E /I
xcopy data data_backup /E /I

# Linux/Mac
cp -r logs logs_backup
cp -r data data_backup
```

**Backup con timestamp:**
```bash
# Linux/Mac
tar -czf coinmaker_backup_$(date +%Y%m%d_%H%M%S).tar.gz logs/ data/

# Windows (PowerShell)
Compress-Archive -Path logs,data -DestinationPath "coinmaker_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').zip"
```

---

## 🔄 Workflow Tipici

### Workflow 1: Prima Esecuzione

```bash
# 1. Configura .env
copy .env.example .env
# [Modifica .env con le tue API keys]

# 2. Build immagine
docker-compose build

# 3. Test connessione
docker-compose run --rm coinmaker-bot python test_connection.py

# 4. Avvia in modalità interactive (per vedere cosa succede)
docker-compose up

# 5. Se tutto ok, Ctrl+C e avvia in background
docker-compose up -d

# 6. Controlla logs
docker-compose logs -f
```

---

### Workflow 2: Uso Quotidiano

```bash
# Mattina: Verifica stato
docker-compose ps

# Controlla logs
docker-compose logs --tail=100

# Se serve riavvio
docker-compose restart

# Sera: Backup logs
cp -r logs logs_backup_$(date +%Y%m%d)
```

---

### Workflow 3: Aggiornamento Codice

```bash
# 1. Ferma bot
docker-compose down

# 2. Aggiorna codice (git pull, modifica files, etc.)
git pull

# 3. Rebuild immagine
docker-compose build

# 4. Riavvia bot
docker-compose up -d

# 5. Verifica logs
docker-compose logs -f
```

---

### Workflow 4: Debug Problema

```bash
# 1. Controlla logs
docker-compose logs --tail=200

# 2. Statistiche risorse
docker stats coinmaker-bot

# 3. Apri shell per investigare
docker-compose exec coinmaker-bot /bin/bash

# 4. Dentro container: check file, test manuale, etc.
cat logs/trading_bot.log
python test_connection.py
exit

# 5. Se serve, restart
docker-compose restart
```

---

### Workflow 5: Rimozione Completa

```bash
# 1. Ferma e rimuovi container + volumi
docker-compose down -v

# 2. Rimuovi immagine
docker rmi coinmaker_coinmaker-bot:latest

# 3. Verifica pulizia
docker images | grep coinmaker
docker ps -a | grep coinmaker

# 4. (Opzionale) Cancella anche file locali
rm -rf logs/ data/
```

---

## 🛠️ Troubleshooting Docker

### Problema: "Cannot connect to Docker daemon"

**Causa:** Docker Desktop non avviato

**Soluzione:**
- Windows/Mac: Avvia Docker Desktop
- Linux: `sudo systemctl start docker`

---

### Problema: "Port already in use"

**Causa:** Porta occupata (solo se usi network mapping)

**Soluzione:**
```bash
# Trova processo che usa la porta
# Windows
netstat -ano | findstr :8080

# Linux/Mac
lsof -i :8080

# Killa processo o cambia porta in docker-compose.yml
```

---

### Problema: Container si riavvia continuamente

**Causa:** Errore nel bot, crash all'avvio

**Soluzione:**
```bash
# Controlla logs
docker-compose logs

# Disabilita restart temporaneo
# In docker-compose.yml: restart: "no"

# Testa manualmente
docker-compose run --rm coinmaker-bot python test_connection.py
```

---

### Problema: Build fallisce

**Causa:** Dipendenze mancanti, errore Dockerfile

**Soluzione:**
```bash
# Build verbose per vedere errore
docker-compose build --progress=plain

# Build senza cache
docker-compose build --no-cache

# Verifica requirements.txt
cat requirements.txt
```

---

### Problema: Volumi non persistono

**Causa:** Volumi non montati correttamente

**Soluzione:**
```bash
# Verifica mount
docker inspect coinmaker-bot | grep -A 10 Mounts

# Ricrea container
docker-compose down
docker-compose up -d
```

---

## 📊 Comandi Docker Utili - Cheatsheet

```bash
# BUILD
docker-compose build                    # Build immagine
docker-compose build --no-cache         # Rebuild completo

# RUN
docker-compose up                       # Avvia foreground
docker-compose up -d                    # Avvia background
docker-compose run --rm bot CMD         # Esegui comando singolo

# STOP/START
docker-compose stop                     # Ferma
docker-compose start                    # Riavvia (se già creato)
docker-compose restart                  # Restart
docker-compose down                     # Ferma e rimuovi
docker-compose down -v                  # Ferma, rimuovi + volumi

# LOGS
docker-compose logs                     # Tutti i logs
docker-compose logs -f                  # Follow logs
docker-compose logs --tail=100          # Ultimi 100
docker-compose logs --since 30m         # Ultimi 30 min

# STATUS
docker-compose ps                       # Stato container
docker stats coinmaker-bot              # Risorse real-time
docker inspect coinmaker-bot            # Info dettagliate

# EXEC
docker-compose exec bot /bin/bash       # Apri shell
docker-compose exec bot CMD             # Esegui comando

# CLEANUP (solo progetto)
docker-compose down -v                  # Rimuovi container+volumi
docker rmi coinmaker_coinmaker-bot      # Rimuovi immagine

# CLEANUP (globale - ATTENZIONE!)
docker system prune -a --volumes        # Pulisci tutto Docker
```

---

## 🎓 Best Practices

### Sicurezza

1. ✅ **Mai committare .env** (già in .gitignore)
2. ✅ **Usa testnet** per test
3. ✅ **Limiti risorse** configurati in docker-compose.yml
4. ✅ **Utente non-root** nel container
5. ✅ **Update regolari** dell'immagine base

### Performance

1. ✅ **Multi-stage build** per immagini leggere
2. ✅ **Cache layers** per build veloci
3. ✅ **Volumi** per I/O efficiente
4. ✅ **Limiti CPU/RAM** per non monopolizzare risorse

### Manutenzione

1. ✅ **Backup regolari** di logs/data
2. ✅ **Monitoring logs** giornaliero
3. ✅ **Update dipendenze** periodici
4. ✅ **Pulizia volumi** non usati

---

## 🚀 Prossimi Passi

1. **Configurazione**: Crea `.env` con le tue API keys
2. **Build**: `docker-compose build`
3. **Test**: `docker-compose run --rm coinmaker-bot python test_connection.py`
4. **Avvio**: `docker-compose up -d`
5. **Monitor**: `docker-compose logs -f`

---

**Docker Setup Completato! 🐳**

*Il tuo bot ora gira in un ambiente isolato, sicuro e facilmente gestibile!*
