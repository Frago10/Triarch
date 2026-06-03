# ───────────────────────────────────────────────────────────────
# Triarch — lanzador del bot como SERVICIO (sin terminal).
#
# Lo arranca la Tarea Programada "Triarch Bot" al iniciar sesión de Windows
# (oculto, sin ventana). Mantiene el bot vivo: si el proceso muere, espera y
# lo relanza. Loguea a logs/service.log.
#
# El bot:
#   · opera en vivo (XAUUSD en AUTO ejecuta en la demo; NAS100/EURUSD señal),
#   · manda señales y latido a Telegram,
#   · publica el snapshot del dashboard a GitHub cada 10 min (full 1×/día),
#     para que la web de GitHub Pages refleje la actividad.
#
# Registrar / quitar la tarea:  ver scripts/install_service.ps1
# Para PARAR el servicio: Task Scheduler → "Triarch Bot" → End / Disable,
#   o cerrar el python, o TRIARCH_KILL=1 en .env.
# ───────────────────────────────────────────────────────────────

$ErrorActionPreference = "Continue"

$proj = "C:\Users\jeanp\OneDrive\מסמכים\OB vault\03 - Resources\Data Engineering\Python\triarch"
Set-Location -LiteralPath $proj

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$py = Join-Path $proj ".venv\Scripts\python.exe"
$log = Join-Path $proj "logs\service.log"
New-Item -ItemType Directory -Force -Path (Join-Path $proj "logs") | Out-Null

while ($true) {
    "$(Get-Date -Format o)  [service] arrancando bot…" | Out-File -FilePath $log -Append -Encoding utf8
    & $py -m scripts.run_live --tick 30 --publish-every-min 10 --publish-full-every-min 1440 *>> $log
    "$(Get-Date -Format o)  [service] el bot salió (code=$LASTEXITCODE). Reintento en 30s." | Out-File -FilePath $log -Append -Encoding utf8
    Start-Sleep -Seconds 30
}
