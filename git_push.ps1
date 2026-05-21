# ───────────────────────────────────────────────────────────────
# Triarch — commit + push de la versión actual a GitHub
# Uso (desde la raíz del proyecto):
#     .\git_push.ps1
#
# Para el SETUP INICIAL del repo (git init), usar setup_git.ps1.
# Este script es para los commits siguientes.
# ───────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

# ─── Limpiar lock stale (lo deja el sandbox de Claude, Windows sí puede borrarlo) ───
if (Test-Path .git\index.lock) {
    Write-Host "==> Quitando .git\index.lock stale..." -ForegroundColor Cyan
    Remove-Item .git\index.lock -Force
}

# ─── Verificar que estamos en un repo git ───
if (-not (Test-Path .git)) {
    Write-Host "No hay repo git todavía. Corre primero .\setup_git.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "==> git add ." -ForegroundColor Cyan
git add -A

Write-Host ""
Write-Host "==> Cambios a commitear:" -ForegroundColor Yellow
git status --short

Write-Host ""
Write-Host "==> Chequeo anti-secretos..." -ForegroundColor Yellow
$sensitive = git diff --cached --name-only | Select-String -Pattern "(^\.env$|\.venv|data_cache|^logs/|\.sqlite$|egg-info)"
if ($sensitive) {
    Write-Host "PARA — algo sensible quedo en el stage:" -ForegroundColor Red
    $sensitive
    exit 1
} else {
    Write-Host "OK — nada sensible." -ForegroundColor Green
}

# ─── Si no hay nada staged, salir ───
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host ""
    Write-Host "No hay cambios para commitear. Nada que hacer." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "==> Commit..." -ForegroundColor Cyan

$commitMsg = @"
Tuning #2 + EURUSD + fix M5 + UI v3

Dashboard UI v3 (sin perder funcionalidad):
- Splash de bienvenida con wordmark gradient
- Sidebar branded: entorno, cuenta MT5, kill switch, atajos
- Tabs reorganizadas: 6 -> 5 (nueva "Inicio" con resumen 24h;
  Signals/Evals/Stats consolidadas en "Datos" con sub-tabs)
- CSS moderno: glassmorphism, pills translucidas, hover en KPIs,
  dots con halo, empty states con emoji

Estrategias y backtesting:
- Nueva estrategia BB_MR (Bollinger Mean Reversion)
- RR dinamico: ORB/EMA_MOMENTUM/BB_MR usan max(rr_propio, cfg.min_rr)
- SCALPER reescrito: 2 gatillos + filtro de tendencia ema_sep_min
- Backtester aplica RR-min + cap diario + sesion; precalcula indicadores
  (20x mas rapido); fix de OOM en el slice de velas futuras
- Confluencia configurable por activo (build_confluence_for)

Fix descarga de historico (forex/M5 devolvia 0 velas):
- mt5_client.get_rates ahora descarga EN CHUNKS con reintentos
- copy_rates_range en 1 sola llamada fallaba con M5 + rangos largos
  (solo devuelve lo cacheado por el terminal)
- fetch_history: mensajes que distinguen simbolo-malo de historico-no-bajado

Config validada en backtest (1 ano data real):
- XAUUSD: EMA_MOMENTUM sola @ min_rr 2.2 -> PF 1.51, WR 41%, E +0.30R
- 3er activo cambiado de USDJPY a EURUSD en todo el proyecto
  (symbols.yaml, runtime.yaml, README, docs, comentarios)
- EURUSD: perfil scalper, sesion 07:00-16:00 UTC, SCALPER+BB_MR

Otros:
- contexto.txt actualizado (secciones 03, 05, 07, 10, 11, 12)
"@

git commit -m $commitMsg

Write-Host ""
Write-Host "==> Push a origin/main..." -ForegroundColor Cyan
git push origin main

Write-Host ""
Write-Host "==> Listo. Version pusheada a https://github.com/Frago10/Triarch" -ForegroundColor Green
