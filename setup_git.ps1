# ───────────────────────────────────────────────────────────────
# Triarch — setup inicial de git + remoto + primer commit
# Uso (desde la raíz del proyecto):
#     .\setup_git.ps1
# ───────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

Write-Host "==> Limpiando .git parcial si existiera..." -ForegroundColor Cyan
if (Test-Path .git) {
    Remove-Item .git -Recurse -Force
}

Write-Host "==> git init (rama main)..." -ForegroundColor Cyan
git init -b main

Write-Host "==> Configurando identidad local del repo..." -ForegroundColor Cyan
git config user.email "jeanpaulfrago10@gmail.com"
git config user.name  "Frago"

Write-Host "==> git add ." -ForegroundColor Cyan
git add .

Write-Host ""
Write-Host "==> Lo que se va a commitear (resumen):" -ForegroundColor Yellow
git status --short

Write-Host ""
Write-Host "==> Verificando que no se cuelan secretos..." -ForegroundColor Yellow
$sensitive = git ls-files --cached | Select-String -Pattern "(^\.env$|\.venv|data_cache|^logs/|\.sqlite$|egg-info)"
if ($sensitive) {
    Write-Host "PARA — algo sensible quedo en el stage:" -ForegroundColor Red
    $sensitive
    exit 1
} else {
    Write-Host "OK — nada sensible." -ForegroundColor Green
}

Write-Host ""
Write-Host "==> Primer commit..." -ForegroundColor Cyan

# Here-string para mensaje multilinea (asi PowerShell no se confunde con los saltos)
$commitMsg = @"
Snapshot inicial - Triarch tras reconstruccion + dashboard 2.0

- 4 estrategias: ORB, VWAP_MR, EMA_MOMENTUM, SCALPER
- Perfiles por activo (balanced, quality, scalper) en symbols.yaml
- Switches en vivo (config/runtime.yaml) controlados desde dashboard
- Dashboard Streamlit con 6 tabs (Live and Control, Decisiones, Backtesting, Signals, Evals, Stats)
- Backtester con Sharpe, Sortino, SQN + equity curve + trade log
- scripts.serve: loop + dashboard en un solo comando
- contexto.txt indexado (12 secciones) como memoria del proyecto
"@

git commit -m $commitMsg

Write-Host ""
Write-Host "==> Conectando remoto a github.com/Frago10/Triarch..." -ForegroundColor Cyan
# Si ya existe el remoto (rerun del script), lo reemplazamos
$existing = git remote 2>$null
if ($existing -contains "origin") {
    git remote set-url origin https://github.com/Frago10/Triarch.git
} else {
    git remote add origin https://github.com/Frago10/Triarch.git
}

Write-Host ""
Write-Host "==> Listo. Para empujar al remoto corre:" -ForegroundColor Green
Write-Host "    git push -u origin main" -ForegroundColor White
Write-Host ""
Write-Host "Si es la primera vez, Windows va a abrir una ventana para autenticarte" -ForegroundColor Gray
Write-Host "(Personal Access Token o login con tu cuenta de GitHub via browser)." -ForegroundColor Gray
