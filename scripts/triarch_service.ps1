# ---------------------------------------------------------------
# Triarch - launcher del bot como SERVICIO (sin terminal).
#
# Lo arranca la Tarea Programada "Triarch Bot" al iniciar sesion de Windows
# (oculto, sin ventana). Mantiene el bot vivo: si el proceso muere, espera y
# lo relanza. Loguea a logs/service.log.
#
# El bot: opera en vivo (XAUUSD AUTO ejecuta en demo; NAS100/EURUSD solo senal),
# manda senales y latido a Telegram, y publica el snapshot del dashboard a
# GitHub cada 10 min (refresh completo 1x/dia) para la web de GitHub Pages.
#
# ASCII puro a proposito: Windows PowerShell 5.1 mal-parsea .ps1 con no-ASCII
# sin BOM. La ruta del proyecto se deriva de $PSScriptRoot (no se hardcodea).
# ---------------------------------------------------------------

$ErrorActionPreference = "Continue"

# $PSScriptRoot = carpeta scripts\ ; el proyecto es su carpeta padre.
$proj = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $proj

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$py = Join-Path $proj ".venv\Scripts\python.exe"
$logDir = Join-Path $proj "logs"
$log = Join-Path $logDir "service.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

while ($true) {
    "$(Get-Date -Format o)  [service] arrancando bot..." | Out-File -FilePath $log -Append -Encoding utf8
    & $py -m scripts.run_live --tick 30 --publish-every-min 10 --publish-full-every-min 1440 *>> $log
    "$(Get-Date -Format o)  [service] el bot salio (code=$LASTEXITCODE). Reintento en 30s." | Out-File -FilePath $log -Append -Encoding utf8
    Start-Sleep -Seconds 30
}
