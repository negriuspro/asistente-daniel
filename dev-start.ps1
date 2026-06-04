# dev-start.ps1 — asistente-daniel en modo local (sin Docker)
# El backend FastAPI sirve tambien el frontend (StaticFiles en /)
# Uso: .\dev-start.ps1

$ROOT    = $PSScriptRoot
$BACKEND = "$ROOT\server"

Write-Host "`n=== Asistente Daniel DEV ===" -ForegroundColor Cyan
Write-Host "  Backend + Frontend en: http://localhost:3002" -ForegroundColor DarkGray

# ── Dependencias ───────────────────────────────────────────────────────────
Write-Host "[1/2] Instalando dependencias..." -ForegroundColor Yellow
Push-Location $BACKEND
pip install -r requirements.txt -q

# .env.dev con configuracion local
if (-not (Test-Path ".env.dev")) {
    @"
GROQ_API_KEY=
ANTHROPIC_API_KEY=
DANIEL_ADMIN_TOKEN=dev-token-local
WAKE_WORDS=daniel,hey daniel
LOG_LEVEL=debug
"@ | Out-File ".env.dev" -Encoding utf8
    Write-Host "      Creado .env.dev — agrega tus API keys reales" -ForegroundColor DarkYellow
}
Pop-Location

# ── Arrancar backend (sirve client/ en /) ─────────────────────────────────
Write-Host "[2/2] Arrancando en http://localhost:3002 ..." -ForegroundColor Yellow
Start-Process "powershell" -ArgumentList "-NoExit", "-Command", @"
cd '$BACKEND'
Get-Content '.env.dev' | ForEach-Object {
    if (`$_ -match '^([^#=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable(`$matches[1].Trim(), `$matches[2].Trim())
    }
}
Write-Host 'Daniel backend iniciando...' -ForegroundColor Green
python -m uvicorn server.main:app --host 0.0.0.0 --port 3002 --reload --app-dir '$ROOT'
"@

Start-Sleep -Seconds 3
Start-Process "http://localhost:3002"

Write-Host "`n✓ Daniel corriendo en http://localhost:3002" -ForegroundColor Green
Write-Host "  WebSocket: ws://localhost:3002/ws (detectado automatico)" -ForegroundColor White
Write-Host "  Di 'Daniel' para activar el asistente`n" -ForegroundColor White
