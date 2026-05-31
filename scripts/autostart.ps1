# Daniel AI — Autostart Script
# Espera a que Docker Desktop esté listo y levanta los contenedores.
# Este script es ejecutado automáticamente por el Programador de tareas.

$ProjectDir = Split-Path -Parent $PSScriptRoot
$LogFile    = Join-Path $ProjectDir "data\autostart.log"

function Write-Log {
    param([string]$Msg)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts  $Msg" | Tee-Object -FilePath $LogFile -Append
}

Write-Log "=== Daniel AI Autostart iniciado ==="

# 1. Esperar a que Docker Engine responda (máx. 3 minutos)
$timeout = 180
$elapsed = 0
Write-Log "Esperando a que Docker Engine esté listo..."

while ($elapsed -lt $timeout) {
    $result = & docker info 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Log "Docker Engine listo ($elapsed segundos)."
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
}

if ($elapsed -ge $timeout) {
    Write-Log "ERROR: Docker Engine no respondió en $timeout segundos. Abortando."
    exit 1
}

# 2. Levantar los contenedores
Set-Location $ProjectDir
Write-Log "Ejecutando: docker compose up -d"
& docker compose up -d 2>&1 | ForEach-Object { Write-Log $_ }

if ($LASTEXITCODE -eq 0) {
    Write-Log "Daniel AI levantado correctamente."
} else {
    Write-Log "ERROR al levantar los contenedores (código $LASTEXITCODE)."
    exit 1
}
