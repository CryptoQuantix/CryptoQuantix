#!/usr/bin/env bash
# Backup giornaliero dei dati cryptoquantix — gira sul HOST (Raspberry Pi),
# fuori da Docker. Vedi microevolutive/PLAN_DEPLOY_RASPBERRY.md §7.
#
# Cosa salva: data/ (journal.db, signal_log.db, positioning_history.db,
# state JSON, backup .env) + il .env stesso.
# I database SQLite vengono snapshottati con `sqlite3 .backup` (consistente
# anche a bot in scrittura); serve `apt install sqlite3` sul host.
#
# Cron consigliato (crontab -e):
#   15 3 * * * /home/pi/cryptoquantix/scripts/backup_data.sh >> /home/pi/backups/cryptoquantix/backup.log 2>&1
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST_DIR="${CRYPTOQUANTIX_BACKUP_DIR:-$HOME/backups/cryptoquantix}"
KEEP=14   # giorni di backup da tenere

STAMP="$(date +%Y%m%d_%H%M%S)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$DEST_DIR"
mkdir -p "$STAGE/data"

echo "[$(date -Is)] backup cryptoquantix -> $DEST_DIR"

# 1. Database SQLite: snapshot consistente con l'API di backup di sqlite
for db in "$PROJECT_DIR"/data/*.db; do
    [ -e "$db" ] || continue
    name="$(basename "$db")"
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$db" ".backup '$STAGE/data/$name'"
    else
        echo "  [WARN] sqlite3 non installato: copia semplice di $name (rischio copia sporca se in scrittura)"
        cp "$db" "$STAGE/data/$name"
    fi
done

# 2. Tutto il resto di data/ (state JSON, env_backups, flags, cache) e .env
rsync -a --exclude='*.db' "$PROJECT_DIR/data/" "$STAGE/data/"
cp "$PROJECT_DIR/.env" "$STAGE/.env"

# 3. Archivio compresso
ARCHIVE="$DEST_DIR/cryptoquantix_data_$STAMP.tar.gz"
tar czf "$ARCHIVE" -C "$STAGE" .
echo "  [OK] $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# 4. Retention: tieni gli ultimi $KEEP archivi
ls -1t "$DEST_DIR"/cryptoquantix_data_*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

# 5. (OPZIONALE) copia offsite — decommentare se rclone e' configurato:
# rclone copy "$ARCHIVE" remote:cryptoquantix-backups/

echo "  [OK] backup completato"
