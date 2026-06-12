# 🐳 Docker Quick Start

Guida rapida per avviare il bot con Docker in 3 minuti.

---

## ⚡ Setup Rapido

### 1. Prerequisiti
- ✅ Docker Desktop installato ([Download](https://www.docker.com/products/docker-desktop/))
- ✅ Docker Desktop avviato
- ✅ File `.env` configurato con API keys

### 2. Configura API Keys

```bash
# Copia template
copy .env.example .env

# Modifica .env con le tue Deribit API keys
DERIBIT_API_KEY=tua_key
DERIBIT_API_SECRET=tuo_secret
DERIBIT_ENV=test
```

```bash
chmod +x docker-start.sh
chmod +x docker-stop.sh
chmod +x docker-logs.sh
chmod +x docker-restart.sh
chmod +x docker-shell.sh
```
### 3. Avvia Bot

**Windows:**
```bash
docker-start.bat
```

**Linux/Mac:**
```bash
./docker-start.sh
```

✅ **Fatto!** Il bot ora gira in background.

---

## 🎮 Comandi Essenziali

### Visualizza Logs
```bash
# Windows
docker-logs.bat

# Linux/Mac
./docker-logs.sh

# Oppure
docker-compose logs -f
```

### Ferma Bot
```bash
# Windows
docker-stop.bat

# Linux/Mac
./docker-stop.sh

# Oppure
docker-compose stop
```

### Riavvia Bot
```bash
# Windows
docker-restart.bat

# Linux/Mac
./docker-restart.sh

# Oppure
docker-compose restart
```

### Verifica Stato
```bash
docker-compose ps
```

### Apri Shell nel Container
```bash
# Windows
docker-shell.bat

# Linux/Mac
./docker-shell.sh

# Oppure
docker-compose exec coinmaker-bot /bin/bash
```

---

## 🗑️ Rimozione Completa

### Rimuovi Solo Container
```bash
docker-compose down
```
*Conserva logs e dati*

### Rimuovi Container + Dati
```bash
docker-compose down -v
```
⚠️ *Cancella anche logs e dati!*

### Rimuovi Anche Immagine
```bash
docker-compose down -v
docker rmi coinmaker_coinmaker-bot:latest
```
🗑️ *Rimozione totale del progetto*

---

## 🔍 Troubleshooting

### "Cannot connect to Docker daemon"
➡️ Avvia Docker Desktop

### Build fallisce
```bash
docker-compose build --no-cache
```

### Container si riavvia continuamente
```bash
docker-compose logs
# Leggi l'errore e correggi
```

---

## 📚 Documentazione Completa

Per dettagli su:
- Build dell'immagine
- Modalità interactive vs demone
- Gestione volumi
- Backup e restore
- Workflow avanzati

📖 **[Leggi la Guida Docker Completa →](DOCKER_GUIDE.md)**

---

**Docker Setup Completato! 🐳**

*Il bot gira in un ambiente isolato e sicuro!*
