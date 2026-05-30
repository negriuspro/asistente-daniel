#!/usr/bin/env bash
# =============================================================================
# Jarvis — Deploy inicial en Ubuntu Server
# Ejecutar como usuario con permisos Docker (no root).
# Uso: bash deploy.sh
# =============================================================================
set -euo pipefail

REPO_URL="https://github.com/negriuspro/jarvis.git"
INSTALL_DIR="$HOME/jarvis"
ENV_FILE="$INSTALL_DIR/.env"

echo "=============================================="
echo "  Jarvis — Deploy producción Ubuntu Server"
echo "=============================================="

# ── 1. Dependencias del sistema ───────────────────────────────────────────────
echo "[1/6] Verificando dependencias del sistema..."
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker no está instalado."
    echo "Instálalo con: curl -fsSL https://get.docker.com | sh"
    exit 1
fi
if ! command -v git &>/dev/null; then
    sudo apt-get update && sudo apt-get install -y git
fi

# ── 2. Clonar repositorio ─────────────────────────────────────────────────────
echo "[2/6] Clonando repositorio..."
if [ -d "$INSTALL_DIR" ]; then
    echo "Directorio $INSTALL_DIR ya existe — actualizando..."
    cd "$INSTALL_DIR" && git pull origin master
else
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# ── 3. Configurar .env ────────────────────────────────────────────────────────
echo "[3/6] Configurando variables de entorno..."
if [ ! -f "$ENV_FILE" ]; then
    cp "$INSTALL_DIR/.env.example" "$ENV_FILE"
    echo ""
    echo "IMPORTANTE: Edita el archivo .env con tus claves antes de continuar."
    echo "  nano $ENV_FILE"
    echo ""
    echo "Variables requeridas:"
    echo "  GROQ_API_KEY          — tu API key de Groq"
    echo "  JARVIS_ADMIN_TOKEN    — token secreto para la API de Docker"
    echo "  TUYA_ACCESS_ID        — credenciales Tuya (si usas Smart Home)"
    echo "  TUYA_ACCESS_SECRET"
    echo ""
    read -rp "¿Ya editaste el .env? (s/N): " confirm
    if [[ ! "$confirm" =~ ^[sS]$ ]]; then
        echo "Abriendo editor..."
        "${EDITOR:-nano}" "$ENV_FILE"
    fi
else
    echo ".env ya existe — omitiendo."
fi

# ── 4. Crear directorios de datos ─────────────────────────────────────────────
echo "[4/6] Creando directorios de datos..."
mkdir -p "$INSTALL_DIR/data/reminders"

# ── 5. Build y arranque ───────────────────────────────────────────────────────
echo "[5/6] Construyendo imágenes y arrancando servicios..."
cd "$INSTALL_DIR"
docker compose pull redis  2>/dev/null || true
docker compose build --no-cache
docker compose up -d

# ── 6. Verificación ───────────────────────────────────────────────────────────
echo "[6/6] Verificando estado de los servicios..."
sleep 15
docker compose ps

echo ""
echo "=============================================="
echo "  Jarvis desplegado correctamente"
echo "  Accede en: http://$(hostname -I | awk '{print $1}'):${APP_PORT:-3000}"
echo "=============================================="
