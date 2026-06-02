"""
Triarch — configurador de notificaciones por Telegram (paso a paso, automático).

Qué hace:
  · Detecta tu CHAT_ID automáticamente (llamando a getUpdates de la API de
    Telegram tras que le escribas al bot).
  · Escribe TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en el .env por ti.
  · Manda un mensaje de PRUEBA para confirmar que todo funciona.

ANTES de correr esto necesitas (ver el README impreso con --help-es):
  1. Crear un bot con @BotFather en Telegram → te da un TOKEN.
  2. Abrir tu bot y enviarle CUALQUIER mensaje (ej. /start o "hola").

Uso:
  # Opción A — pasas el token y el script hace todo el resto:
  python -m scripts.setup_telegram --token 8123456789:AAH....

  # Opción B — si ya pusiste TELEGRAM_BOT_TOKEN en .env a mano:
  python -m scripts.setup_telegram

  # Solo mandar un mensaje de prueba con la config actual del .env:
  python -m scripts.setup_telegram --test

  # Ver la guía de creación del bot en español:
  python -m scripts.setup_telegram --help-es
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"

GUIDE_ES = """
═══════════════════════════════════════════════════════════════════
  CÓMO CREAR EL BOT DE TELEGRAM (una sola vez, ~3 minutos)
═══════════════════════════════════════════════════════════════════

PASO 1 — Crear el bot
  1. Abre Telegram (móvil o escritorio).
  2. En el buscador, escribe:  @BotFather   y ábrelo (tiene tilde azul).
  3. Envíale:  /newbot
  4. Te pedirá un NOMBRE (lo que se ve, ej: "Triarch Señales").
  5. Te pedirá un USERNAME que termine en 'bot' (ej: "triarch_frago_bot").
  6. BotFather te responde con un TOKEN como:
        8123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
     ↑ COPIA ese token completo.

PASO 2 — "Activar" el bot para que pueda escribirte
  7. En el mensaje de BotFather, toca el enlace t.me/tu_bot (o búscalo por
     su username) para abrir el chat con TU bot.
  8. Pulsa "Iniciar" / "Start"  (o escríbele cualquier cosa, ej: hola).
     ⚠ Esto es OBLIGATORIO: Telegram no deja que un bot te escriba si tú no
       le escribiste primero.

PASO 3 — Dejar que Triarch lo configure solo
  9. En la terminal del proyecto corre:
        python -m scripts.setup_telegram --token <PEGA_TU_TOKEN_AQUÍ>
     El script detecta tu chat_id, lo guarda en .env y te manda un mensaje
     de prueba. Si lo recibes en Telegram → ¡listo!

PASO 4 — Arrancar el bot normal
  10. python -m scripts.run_live --tick 30
      (o python -m scripts.serve --tick 30 --port 8765)
      Cada señal que emita llegará a tu Telegram.
═══════════════════════════════════════════════════════════════════
"""


def _read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _set_env_key(key: str, value: str) -> None:
    """Reemplaza o agrega KEY=VALUE en el .env, preservando el resto."""
    lines: list[str] = []
    found = False
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _get_updates(token: str) -> list[dict]:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    r = httpx.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram getUpdates error: {data}")
    return data.get("result", [])


def _detect_chat_id(token: str) -> tuple[str | None, str | None]:
    """Devuelve (chat_id, nombre) del chat más reciente que escribió al bot."""
    updates = _get_updates(token)
    chats: dict[str, str] = {}
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post")
        if not msg:
            continue
        chat = msg.get("chat", {})
        cid = chat.get("id")
        if cid is None:
            continue
        name = (
            chat.get("username")
            or chat.get("title")
            or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
            or "(sin nombre)"
        )
        chats[str(cid)] = name
    if not chats:
        return None, None
    # El más reciente queda último en el dict (orden de inserción)
    cid = list(chats.keys())[-1]
    return cid, chats[cid]


def _send_test(token: str, chat_id: str) -> bool:
    text = (
        "✅ *Triarch* conectado a Telegram.\n"
        "A partir de ahora recibirás aquí cada señal del bot.\n"
        "_(mensaje de prueba — la configuración funciona)_"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = httpx.post(
        url,
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  ✗ sendMessage falló: HTTP {r.status_code} — {r.text}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configura las notificaciones de Telegram para Triarch."
    )
    parser.add_argument("--token", help="Token del bot (de @BotFather). Si no, se lee del .env.")
    parser.add_argument("--chat-id", help="Forzar un chat_id específico (normalmente no hace falta).")
    parser.add_argument("--test", action="store_true", help="Solo enviar un mensaje de prueba con la config actual.")
    parser.add_argument("--help-es", action="store_true", help="Mostrar la guía paso a paso en español.")
    args = parser.parse_args()

    if args.help_es:
        print(GUIDE_ES)
        return 0

    env = _read_env()
    token = args.token or env.get("TELEGRAM_BOT_TOKEN", "")

    if not token:
        print("✗ No hay TOKEN. Pásalo con --token <TOKEN> o ponlo en .env.")
        print("  ¿No tienes bot todavía? Corre:  python -m scripts.setup_telegram --help-es")
        return 1

    # ─── Modo --test: usa el chat_id del .env ───
    if args.test:
        chat_id = args.chat_id or env.get("TELEGRAM_CHAT_ID", "")
        if not chat_id:
            print("✗ No hay TELEGRAM_CHAT_ID en .env. Corre sin --test para detectarlo.")
            return 1
        print(f"Enviando mensaje de prueba a chat_id={chat_id}…")
        ok = _send_test(token, chat_id)
        print("✓ Enviado. Revisa tu Telegram." if ok else "✗ Falló el envío.")
        return 0 if ok else 1

    # ─── Detectar chat_id ───
    chat_id = args.chat_id
    name = None
    if not chat_id:
        print("Buscando tu chat_id (¿le enviaste un mensaje al bot?)…")
        try:
            chat_id, name = _detect_chat_id(token)
        except httpx.HTTPStatusError as e:
            print(f"✗ El token parece inválido (HTTP {e.response.status_code}).")
            print("  Verifica que copiaste el token COMPLETO de @BotFather.")
            return 1
        except Exception as e:  # noqa: BLE001
            print(f"✗ Error consultando Telegram: {e}")
            return 1

    if not chat_id:
        print(
            "✗ No encontré ningún chat.\n"
            "  → Abre tu bot en Telegram y envíale CUALQUIER mensaje (ej: /start o 'hola'),\n"
            "    luego vuelve a correr este comando.\n"
            "  (Telegram no deja que el bot te escriba si tú no le escribiste primero.)"
        )
        return 1

    print(f"✓ chat_id detectado: {chat_id}" + (f"  ({name})" if name else ""))

    # ─── Guardar en .env ───
    _set_env_key("TELEGRAM_BOT_TOKEN", token)
    _set_env_key("TELEGRAM_CHAT_ID", str(chat_id))
    print(f"✓ Guardado en {ENV_PATH.name}: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID")

    # ─── Mensaje de prueba ───
    print("Enviando mensaje de prueba…")
    ok = _send_test(token, str(chat_id))
    if ok:
        print("✓ ¡Listo! Revisa tu Telegram, deberías ver el mensaje de Triarch.")
        print("  Ahora arranca el bot:  python -m scripts.run_live --tick 30")
        return 0
    else:
        print("✗ No se pudo enviar el mensaje de prueba. Revisa el token/chat.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
