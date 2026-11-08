#!/usr/bin/env bash
# Encrypted nightly database backup.  Run on the SERVER from the project folder:
#   BACKUP_PASSPHRASE='long secret' bash deploy/backup.sh
# Optional: DB_SERVICE (compose service of Postgres, default "db"), DB_USER, DB_NAME, BACKUP_DIR, KEEP_DAYS (default 14),
#           COMPOSE_FILES (default "-f docker-compose.yml").
# Keep the passphrase in your password manager. WITHOUT IT THE BACKUPS CANNOT BE OPENED.
set -euo pipefail
: "${BACKUP_PASSPHRASE:?Set BACKUP_PASSPHRASE first}"
DB_SERVICE="${DB_SERVICE:-db}"; DB_USER="${DB_USER:-postgres}"; DB_NAME="${DB_NAME:-jarvis}"
BACKUP_DIR="${BACKUP_DIR:-backups}"; KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml}"
mkdir -p "$BACKUP_DIR"; umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/jarvis-$stamp.sql.gz.enc"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T "$DB_SERVICE" pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "$out"
size=$(wc -c < "$out")
if [ "$size" -lt 1000 ]; then echo "BACKUP FAILED: file is only $size bytes"; rm -f "$out"; exit 1; fi
find "$BACKUP_DIR" -name 'jarvis-*.sql.gz.enc' -mtime +"$KEEP_DAYS" -delete
echo "OK  $out  ($size bytes). Old backups beyond $KEEP_DAYS days removed."
echo "Copy this file OFF the server too (another machine or cloud storage), or a dead server takes the backups with it."
