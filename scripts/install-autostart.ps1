# Daniel AI — Instalar tarea de inicio automático en el Programador de tareas de Windows.
# Ejecutar UNA SOLA VEZ como Administrador:
#   Right-click → "Ejecutar como administrador"

$TaskName   = "DanielAI-Autostart"
$ScriptPath = Join-Path $PSScriptRoot "autostart.ps1"

# Verificar que el script existe
if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: No se encontró $ScriptPath" -ForegroundColor Red
    exit 1
}

# Eliminar tarea anterior si existe
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Tarea anterior eliminada." -ForegroundColor Yellow
}

# Acción: ejecutar PowerShell con el script
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Disparador: al iniciar sesión del usuario actual
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# Configuración: esperar 30s después del login para dar tiempo a Docker Desktop
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 2)

$Settings.StartDelay = "PT30S"  # Esperar 30 segundos antes de arrancar

# Registrar la tarea
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Levanta los contenedores de Daniel AI después de iniciar sesión." `
    -Force | Out-Null

Write-Host ""
Write-Host "✓ Tarea '$TaskName' registrada exitosamente." -ForegroundColor Green
Write-Host ""
Write-Host "Pasos finales (solo la primera vez):" -ForegroundColor Cyan
Write-Host "  1. Abre Docker Desktop"
Write-Host "  2. Ve a Settings → General"
Write-Host "  3. Activa: 'Start Docker Desktop when you sign in to Windows'"
Write-Host "  4. Guarda y reinicia la PC"
Write-Host ""
Write-Host "Desde ahora, al encender la PC Daniel AI arranca solo." -ForegroundColor Green
Write-Host "Log de arranque: $PSScriptRoot\..\data\autostart.log"
