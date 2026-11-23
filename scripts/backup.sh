#!/bin/sh
# Database copies: one a day and whenever the bot asks (admin menu -> "Copy now").
# Runs in the "backup" container (postgres image, so pg_dump matches the server). Copies older than 14 days are deleted.
# Restore: gunzip -c backups/db-YYYYMMDD-HHMM.sql.gz | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
set -u
export PGPASSWORD="$POSTGRES_PASSWORD"
DIR=/backups
INTERVAL=86400
last=0
mkdir -p "$DIR"
while true; do
  now=$(date +%s)
  if [ -f "$DIR/.request" ] || [ $((now - last)) -ge $INTERVAL ]; then
    rm -f "$DIR/.request"
    name="$DIR/db-$(date +%Y%m%d-%H%M).sql.gz"
    if pg_dump --clean --if-exists -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" -U "$POSTGRES_USER" "$POSTGRES_DB" \
        | gzip > "$name.tmp" && [ -s "$name.tmp" ]; then
      mv "$name.tmp" "$name"
      echo "backup saved: $name"
    else
      rm -f "$name.tmp"
      echo "backup FAILED" >&2
      date +%s > "$DIR/.failed"
    fi
    find "$DIR" -name 'db-*.sql.gz' -mtime +14 -delete
    last=$now
  fi
  sleep 60
done
