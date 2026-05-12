# Setup MT5 demo — guía paso a paso

> Estado: tienes MT5 instalado pero sin cuenta demo. Esta guía te lleva de 0 a "el bot lee velas y account info".

## 1. Elegir broker (5 min)

Para MT5 necesitas una **cuenta demo** de un broker que ofrezca los 3 activos: **NAS100, XAUUSD, USDJPY**.

Recomendados (todos buenos para CFDs en demo, todos con MT5 nativo):

| Broker | Pros | Símbolos | URL |
|---|---|---|---|
| **IC Markets** | Spread bajo, ECN, infra sólida | NAS100, XAUUSD, USDJPY | https://www.icmarkets.com |
| **Pepperstone** | Spread bajo, regulado AU/UK | NAS100, XAUUSD, USDJPY | https://www.pepperstone.com |
| **XM** | Demo ilimitada, muchas instituciones lo usan | US100 (=NAS100), GOLD, USDJPY | https://www.xm.com |
| **Exness** | Sin verificación inmediata para demo | USTEC (=NAS100), XAUUSD, USDJPY | https://www.exness.com |

**Mi recomendación:** **IC Markets** o **Pepperstone**. Si quieres demo sin papeleo: **Exness**.

> ⚠️ Estás abriendo solo cuenta **DEMO**. No depositas dinero. No estás obligado a nada.

## 2. Abrir cuenta demo (5-10 min)

1. Ve al sitio del broker → "Demo account" o "Cuenta demo".
2. Llena formulario (nombre, email, teléfono).
3. Elige cuenta tipo **Standard** o **Raw/ECN** (no importa para demo).
4. Plataforma: **MetaTrader 5** (NO MT4).
5. Apalancamiento: 1:100 está bien para demo.
6. Balance virtual: 10.000 USD por defecto está bien.
7. Recibirás un email con:
   - **Login** (número de 7-8 dígitos)
   - **Password** (master + investor; nos importa el master)
   - **Server** (algo tipo `ICMarkets-Demo01`, `Pepperstone-Demo`, `Exness-MT5Trial7`)

**Anota los 3 valores.** Los necesitamos para `.env`.

## 3. Conectar MT5 terminal a la cuenta demo (3 min)

1. Abre MetaTrader 5 (la app de escritorio).
2. Menú `File` → `Login to Trade Account`.
3. Introduce login, password, server. Click `OK`.
4. Si todo va bien verás en la esquina inferior derecha algo como:
   `1234567 : Real Account / Demo Account` con números cambiando.
5. Verifica que en `Market Watch` aparecen los 3 símbolos:
   - Click derecho → `Show All` para mostrar todos, o
   - Click derecho → `Symbols` y busca cada uno.

> 🔍 **Nombres exactos varían por broker:**
> - IC Markets / Pepperstone: `NAS100`, `XAUUSD`, `USDJPY`
> - XM: `US100`, `GOLD`, `USDJPY`
> - Exness: `USTEC`, `XAUUSD`, `USDJPY`
>
> Anota los nombres exactos — los pondrás en `config/symbols.yaml`.

## 4. Habilitar auto-trading en el terminal (1 min)

Para que el paquete Python pueda colocar órdenes (cuando lleguemos al modo AUTO):

1. Menú `Tools` → `Options` → pestaña `Expert Advisors`.
2. Marca: ✅ `Allow algorithmic trading`.
3. (Opcional) ✅ `Allow DLL imports` — solo si lo necesitamos.
4. Click `OK`.

## 5. Instalar paquete Python `MetaTrader5` (2 min)

⚠️ El paquete oficial **solo funciona en Windows**. Si estás en Mac o Linux, necesitas Windows VM o WSL no funciona.

```powershell
cd "C:\Users\jeanp\Documents\OB vault\03 - Resources\Data Engineering\Python\triarch"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Verifica:

```powershell
python -c "import MetaTrader5; print(MetaTrader5.__version__)"
```

## 6. Configurar `.env` (1 min)

```powershell
copy .env.example .env
notepad .env
```

Llena:

```ini
MT5_LOGIN=1234567              # tu login demo
MT5_PASSWORD=tu_password_demo  # master password
MT5_SERVER=ICMarkets-Demo01    # tal cual aparece en MT5
TRIARCH_ENV=demo
```

Si MT5 está en path no estándar:

```ini
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
```

## 7. Ajustar `config/symbols.yaml` por broker (1 min)

Si tu broker usa nombres distintos, edita el campo `broker_symbol`:

```yaml
NAS100:
  broker_symbol: US100      # XM
  # broker_symbol: USTEC    # Exness
```

## 8. Test de conexión (1 min)

```powershell
python -m scripts.connect_mt5
```

Deberías ver:

```
Triarch — test de conexión MT5
✓ Conectado — TU NOMBRE (1234567)
  Server: ICMarkets-Demo01
  Balance: 10000.00 USD
  Equity: 10000.00 USD
  ...
┌────────┬──────────────┬─────────┬─────────┬────────┬─────────┬───────────────┐
│ Activo │ Broker symbol│ Bid     │ Ask     │ Spread │ Min lot │ Velas M15 (n) │
├────────┼──────────────┼─────────┼─────────┼────────┼─────────┼───────────────┤
│ NAS100 │ NAS100       │ 17452.5 │ 17453.0 │ 5      │ 0.10    │ 10            │
│ XAUUSD │ XAUUSD       │ 2014.50 │ 2014.80 │ 30     │ 0.01    │ 10            │
│ USDJPY │ USDJPY       │ 154.250 │ 154.255 │ 5      │ 0.01    │ 10            │
└────────┴──────────────┴─────────┴─────────┴────────┴─────────┴───────────────┘
```

Si todo va, ya estás listo para correr el bot:

```powershell
python -m scripts.run_live --tick 60
```

## Troubleshooting

### "MT5 initialize() falló: (-10005, 'IPC timeout')"
- MT5 terminal no está corriendo o no logueado.
- Solución: abre MT5 manualmente, asegúrate de que dice "Connected" en esquina inferior, vuelve a intentar.

### "No se pudo seleccionar el símbolo NAS100"
- El broker usa otro nombre. Mira el Market Watch en MT5, identifica el nombre exacto, edita `config/symbols.yaml`.

### "ImportError: cannot import name 'MetaTrader5'"
- No estás en Windows, o el venv está activado mal.
- Solución: `pip install MetaTrader5` y verifica con `python -c "import MetaTrader5"`.

### Velas vacías para algún activo
- El símbolo tiene que estar en Market Watch. Click derecho en MT5 → `Show All`.

## Próximos pasos

Una vez `connect_mt5` corre OK:
1. Edita `symbols.yaml` para ajustar las **ventanas de sesión** a los horarios reales (revisa en MT5 a qué hora UTC abre/cierra cada activo).
2. Corre `pytest tests/` para validar que los módulos no-MT5 pasan sus tests.
3. Corre `python -m scripts.run_live` durante una sesión para ver evaluaciones llegando a SQLite.
4. Abre el dashboard: `streamlit run dashboard/app.py`.
