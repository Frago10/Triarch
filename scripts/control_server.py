"""
Triarch — servidor de CONTROL local (hace funcional el switch de la web).

GitHub Pages es estático: la página no puede escribir config/runtime.yaml por
sí sola. Este mini servidor corre DENTRO del proceso del bot (run_live lo
arranca en un thread) y escucha SOLO en 127.0.0.1 — únicamente las páginas
abiertas en la máquina del bot pueden hablarle. La web (local o GH Pages*)
lo detecta al cargar: si responde, los toggles "Trades reales" se vuelven
interactivos y escriben runtime.yaml al instante; si no, quedan en lectura.

(*) Chrome/Edge/Firefox tratan http://127.0.0.1 como origen confiable, por lo
que una página https puede hacerle fetch. Chrome además exige el header
Access-Control-Allow-Private-Network en el preflight — lo incluimos.

Endpoints:
  GET  /status            → estado live: take_trades + modo efectivo por activo
  POST /toggle            → body {"symbol": "XAUUSD", "value": false}
  OPTIONS                 → preflight CORS

Sin autenticación A PROPÓSITO: el binding 127.0.0.1 limita el acceso a
procesos locales de la misma máquina (mismo nivel de confianza que editar
runtime.yaml a mano). NO exponer en 0.0.0.0 sin añadir auth.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from loguru import logger

from config.runtime import get_take_trades, set_take_trades
from config.settings import get_settings, get_symbols

DEFAULT_PORT = 8772


class _Handler(BaseHTTPRequestHandler):
    server_version = "TriarchControl/1.0"

    # ─── helpers ───
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome Private Network Access: página https → http://127.0.0.1
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ─── HTTP ───
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/status":
            self._json(404, {"error": "not found"})
            return
        try:
            symbols = get_symbols()
            out: dict[str, dict] = {}
            for name, cfg in symbols.items():
                live = get_take_trades(name, default=cfg.take_trades)
                out[name] = {
                    "take_trades": live,
                    "mode_yaml": cfg.mode.value,
                    "effective_mode": cfg.mode.value if live else "SIGNAL_ONLY",
                    "timeframe": cfg.timeframe,
                }
            self._json(200, {
                "ok": True,
                "control": True,
                "kill": bool(get_settings().triarch_kill),
                "symbols": out,
            })
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] != "/toggle":
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{}")
            symbol = str(data.get("symbol", ""))
            value = bool(data.get("value"))
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"error": f"body inválido: {exc}"})
            return
        if symbol not in get_symbols():
            self._json(400, {"error": f"símbolo desconocido: {symbol}"})
            return
        set_take_trades(symbol, value)
        logger.info(f"[control] toggle web → take_trades[{symbol}] = {value}")
        self._json(200, {"ok": True, "symbol": symbol, "take_trades": value})

    def log_message(self, fmt: str, *args) -> None:  # silenciar log por request
        return


def start_control_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer | None:
    """Arranca el servidor de control en un daemon thread. None si el puerto está ocupado."""
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        logger.warning(f"[control] no se pudo abrir 127.0.0.1:{port} ({exc}) — switch web deshabilitado.")
        return None
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="triarch-control")
    t.start()
    logger.info(f"[control] switch web activo en http://127.0.0.1:{port} (GET /status · POST /toggle)")
    return srv
