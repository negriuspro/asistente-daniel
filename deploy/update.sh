#!/usr/bin/env bash
# =============================================================================
# Jarvis — Actualizar desde git y redesplegar
# Uso: bash update.sh
# =============================================================================
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[update] Directorio: $INSTALL_DIR"
cd "$INSTALL_DIR"

echo "[update] Descargando cambios..."
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "[update] Ya estás en la versión más reciente. Nada que hacer."
    exit 0
fi

echo "[update] Nuevos commits detectados — actualizando..."
git pull origin master

echo "[update] Reconstruyendo imágenes modificadas..."
docker compose build

echo "[update] Reiniciando servicios con zero-downtime..."
docker compose up -d --remove-orphans

echo "[update] Estado actual:"
docker compose ps

echo "[update] Listo. $(git log -1 --pretty='%h %s')"
