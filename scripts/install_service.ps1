# ---------------------------------------------------------------
# Triarch - instala/quita la Tarea Programada que corre el bot como servicio.
#
# Uso (PowerShell normal, NO necesita admin - corre como tu usuario):
#     .\scripts\install_service.ps1                  # instala (al iniciar sesion)
#     .\scripts\install_service.ps1 -Action status   # ver estado
#     .\scripts\install_service.ps1 -Action start     # arrancar ahora
#     .\scripts\install_service.ps1 -Action stop       # detener ahora
#     .\scripts\install_service.ps1 -Action uninstall  # quitar la tarea
#
# La tarea arranca scripts/triarch_service.ps1 OCULTO al iniciar sesion y lo
# mantiene vivo. Requiere MT5 abierto y logueado (en MT5 activa el auto-login
# de la cuenta demo para que este listo al arrancar Windows).
#
# ASCII puro: Windows PowerShell 5.1 mal-parsea .ps1 con no-ASCII sin BOM.
# ---------------------------------------------------------------

param(
    [ValidateSet("install", "uninstall", "status", "start", "stop")]
    [string]$Action = "install"
)

$TaskName = "Triarch Bot"
$proj = Split-Path -Parent $PSScriptRoot
$svc = Join-Path $proj "scripts\triarch_service.ps1"

switch ($Action) {
    "status" {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($t) {
            $t | Select-Object TaskName, State | Format-Table -AutoSize
            Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List
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

# --- install ---
# No usar $action como nombre de variable: colisiona con el parametro $Action.
$argline = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $svc + '"'
$taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argline
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$register = @{
    TaskName    = $TaskName
    Action      = $taskAction
    Trigger     = $trigger
    Settings    = $settings
    Principal   = $principal
    Description = "Triarch trading bot: loop live + publica el dashboard a GitHub. Arranca al iniciar sesion."
    Force       = $true
}
Register-ScheduledTask @register | Out-Null

Write-Host "OK - Tarea '$TaskName' instalada (arranca al iniciar sesion)." -ForegroundColor Green
Write-Host "  Arrancar ya:   .\scripts\install_service.ps1 -Action start" -ForegroundColor Cyan
Write-Host "  Ver estado:    .\scripts\install_service.ps1 -Action status" -ForegroundColor Cyan
Write-Host "  Logs:          logs\service.log" -ForegroundColor Cyan
