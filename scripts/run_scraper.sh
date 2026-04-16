#!/usr/bin/env bash
# 6-hourly cron entrypoint. Wraps scrape_jobs.py with logging + lockfile.
set -euo pipefail

ROOT="/home/usfbarrima/jobQuery"
LOG="$ROOT/logs/cron.log"
LOCK="$ROOT/logs/.scrape.lock"

mkdir -p "$ROOT/logs"

# Single-flight lock so two runs never overlap (cron + manual invocation safety).
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date -Is)] previous scrape still running; skipping this tick" >> "$LOG"
  exit 0
fi

echo "[$(date -Is)] cron tick: starting scrape" >> "$LOG"

# Use system python3 (no venv needed - script uses stdlib only).
cd "$ROOT"
python3 "$ROOT/scripts/scrape_jobs.py" >> "$LOG" 2>&1 || {
  echo "[$(date -Is)] scrape FAILED with exit $?" >> "$LOG"
  exit 1
}

echo "[$(date -Is)] cron tick: done" >> "$LOG"
