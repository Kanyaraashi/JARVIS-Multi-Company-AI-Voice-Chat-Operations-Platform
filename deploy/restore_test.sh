#!/usr/bin/env bash
# Proves a backup really works by restoring it into a THROWAWAY database (never your live one).
#   BACKUP_PASSPHRASE='...' bash deploy/restore_test.sh backups/jarvis-XXXX.sql.gz.enc
# A backup you have never restored is only a hope. Do this once a month.
set -euo pipefail
: "${BACKUP_PASSPHRASE:?Set BACKUP_PASSPHRASE first}"
file="${1:?Give the backup file}"
DB_SERVICE="${DB_SERVICE:-db}"; DB_USER="${DB_USER:-postgres}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml}"
scratch="jarvis_restore_test"
dc() { docker compose $COMPOSE_FILES exec -T "$DB_SERVICE" "$@"; }
dc psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS $scratch" >/dev/null
dc psql -U "$DB_USER" -d postgres -c "CREATE DATABASE $scratch" >/dev/null
openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "$file" | gunzip \
  | dc psql -U "$DB_USER" -d "$scratch" -v ON_ERROR_STOP=1 -q >/dev/null
for t in companies customers support_tickets call_records; do
  n=$(dc psql -U "$DB_USER" -d "$scratch" -tA -c "SELECT count(*) FROM $t" | tr -d '\r')
  echo "  $t: $n rows"
done
dc psql -U "$DB_USER" -d postgres -c "DROP DATABASE $scratch" >/dev/null
echo "RESTORE TEST PASSED: the backup opens and the data is there."
