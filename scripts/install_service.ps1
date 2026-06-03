# ───────────────────────────────────────────────────────────────
# Triarch — instala/quita la Tarea Programada que corre el bot como servicio.
#
# Uso (PowerShell normal, NO hace falta admin — corre como tu usuario):
#     .\scripts\install_service.ps1                 # instala (al iniciar sesión)
#     .\scripts\install_service.ps1 -Action status  # ver estado
#     .\scripts\install_service.ps1 -Action start    # arrancar ahora
#     .\scripts\install_service.ps1 -Action stop      # detener ahora
#     .\scripts\install_service.ps1 -Action uninstall # quitar la tarea
#
# La tarea arranca scripts/triarch_service.ps1 OCULTO al iniciar sesión y lo
# mantiene vivo. Requiere que MT5 esté abierto y logueado (ponlo a arrancar con
# Windows en MT5: Tools → Options → marca el auto-login de la cuenta demo).
# ───────────────────────────────────────────────────────────────

param(
    [ValidateSet("install", "uninstall", "status", "start", "stop")]
    [string]$Action = "install"
)

$TaskName = "Triarch Bot"
$proj = "C:\Users\jeanp\OneDrive\מסמכים\OB vault\03 - Resources\Data Engineering\Python\triarch"
$svc = Join-Path $proj "scripts\triarch_service.ps1"

switch ($Action) {
    "status" {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($t) {
            $t | Select-Object TaskName, State
            (Get-ScheduledTaskInfo -TaskName $TaskName) | Select-Object LastRunTime, LastTaskResult, NextRunTime
        } else { Write-Host "La tarea '$TaskName' no existe." -ForegroundColor Yellow }
        return
    }
    "start" { Start-ScheduledTask -TaskName $TaskName; Write-Host "Tarea arrancada." -ForegroundColor Green; return }
    "stop"  { Stop-ScheduledTask  -TaskName $TaskName; Write-Host "Tarea detenida."  -ForegroundColor Green; return }
    "uninstall" {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Tarea '$TaskName' eliminada." -ForegroundColor Green
        return
    }
}

# ─── install ───
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$svc`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Triarch trading bot — corre el loop live + publica el dashboard a GitHub. Arranca al iniciar sesión." `
    -Force | Out-Null

Write-Host "✓ Tarea '$TaskName' instalada (arranca al iniciar sesión)." -ForegroundColor Green
Write-Host "  Arrancar ya:   .\scripts\install_service.ps1 -Action start" -ForegroundColor Cyan
Write-Host "  Ver estado:    .\scripts\install_service.ps1 -Action status" -ForegroundColor Cyan
Write-Host "  Logs:          logs\service.log" -ForegroundColor Cyan
