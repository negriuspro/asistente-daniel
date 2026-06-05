#!/bin/sh
# Backup periódico de Redis RDB + conversaciones JSONL para Daniel.
# Redis: /data/dump.rdb        → /backups/redis_TS.rdb.gz
# Data:  /app-data/*.jsonl     → /backups/data_TS.tar.gz
# Retiene los últimos BACKUP_KEEP_DAYS días (default: 7).
set -e

INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

mkdir -p "$BACKUP_DIR"
echo "[backup-daniel] Iniciando. Primer backup en 60s."
echo "[backup-daniel] Intervalo: ${INTERVAL}s | Retención: ${KEEP_DAYS} días | Destino: ${BACKUP_DIR}"

sleep 60

while true; do
  TS=$(date +%Y%m%d_%H%M%S)
  echo "[backup-daniel] ── ${TS} ────────────────────"

  # ── Redis RDB ──────────────────────────────────────────────────────────────
  if cp /data/dump.rdb "${BACKUP_DIR}/redis_${TS}.rdb" 2>/dev/null; then
    gzip -f "${BACKUP_DIR}/redis_${TS}.rdb"
    SIZE=$(du -sh "${BACKUP_DIR}/redis_${TS}.rdb.gz" 2>/dev/null | cut -f1 || echo "?")
    echo "[backup-daniel] OK redis → redis_${TS}.rdb.gz (${SIZE})"
  else
    echo "[backup-daniel] AVISO: /data/dump.rdb no disponible (Redis vacío o arrancando)"
  fi

  # ── Conversaciones JSONL ────────────────────────────────────────────────────
  if find /app-data -name "*.jsonl" 2>/dev/null | grep -q .; then
    tar -czf "${BACKUP_DIR}/data_${TS}.tar.gz" -C /app-data . 2>/dev/null
    SIZE=$(du -sh "${BACKUP_DIR}/data_${TS}.tar.gz" 2>/dev/null | cut -f1 || echo "?")
    echo "[backup-daniel] OK data  → data_${TS}.tar.gz (${SIZE})"
  else
    echo "[backup-daniel] AVISO: /app-data sin archivos JSONL aún"
  fi

  # ── Limpieza por retención ──────────────────────────────────────────────────
  find "$BACKUP_DIR" -name "redis_*.rdb.gz" -mtime "+${KEEP_DAYS}" -delete
  find "$BACKUP_DIR" -name "data_*.tar.gz"  -mtime "+${KEEP_DAYS}" -delete
  TOTAL=$(find "$BACKUP_DIR" -name "*.gz" 2>/dev/null | wc -l || echo 0)
  echo "[backup-daniel] ${TOTAL} backup(s) retenidos. Próximo en ${INTERVAL}s."

  sleep "$INTERVAL"
done
