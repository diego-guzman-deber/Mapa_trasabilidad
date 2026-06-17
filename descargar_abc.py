#!/usr/bin/env python3
"""
descargar_abc.py — Descarga datos de transitabilidad.abc.gob.bo y los guarda en JSON.

Uso:
    python descargar_abc.py              # Descarga solo si el cache tiene >1 hora
    python descargar_abc.py --force      # Fuerza la descarga siempre
    python descargar_abc.py --status     # Muestra el estado del cache sin descargar

Automatización en Windows (Task Scheduler):
    Programa:   python
    Argumentos: C:\\ruta\\descargar_abc.py
    Disparador: cada 2 horas

Automatización en Linux (cron):
    0 */2 * * *  cd /ruta && python3 descargar_abc.py >> logs/descarga_abc.log 2>&1
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import random
import sys
import time

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    from urllib.request import Request, urlopen  # type: ignore[assignment]
    _HAS_REQUESTS = False

# ── Config ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ABC_CACHE_PATH = DATA_DIR / "latest_abc_data.json"
LOG_DIR = ROOT / "logs"

ABC_DATA_URL = "https://transitabilidad.abc.gob.bo/api/v1/data"
CACHE_TTL_SECONDS = 3600   # 1 hora: no descargar si el cache es más fresco
BOLIVIA_TZ = timezone(timedelta(hours=-4))

# ── User-Agents reales (rotatorio) ─────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


# ── Logging ────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now(BOLIVIA_TZ).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    # Escribir también al log en disco
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with (LOG_DIR / "descarga_abc.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ── Cache helpers ──────────────────────────────────────────────────────────

def get_cache_age() -> float | None:
    """Retorna la antigüedad del cache en segundos, o None si no existe."""
    if not ABC_CACHE_PATH.exists():
        return None
    try:
        with ABC_CACHE_PATH.open("r", encoding="utf-8") as fh:
            content = json.load(fh)
        if isinstance(content, dict) and content.get("fetched_at_ts"):
            return time.time() - float(content["fetched_at_ts"])
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    try:
        return time.time() - ABC_CACHE_PATH.stat().st_mtime
    except OSError:
        return None


def show_status() -> None:
    age = get_cache_age()
    if age is None:
        _log("Estado del cache: NO EXISTE")
        return

    if age < CACHE_TTL_SECONDS:
        _log(f"Estado del cache: VIGENTE  (antigüedad: {age:.0f}s / {age/60:.1f} min)")
    else:
        _log(f"Estado del cache: VENCIDO  (antigüedad: {age:.0f}s / {age/3600:.1f} h)")

    try:
        with ABC_CACHE_PATH.open("r", encoding="utf-8") as fh:
            content = json.load(fh)
        if isinstance(content, dict):
            _log(f"  Obtenido en  : {content.get('fetched_at', 'desconocido')}")
            _log(f"  Ítems        : {content.get('item_count', '?')}")
            _log(f"  Archivo      : {ABC_CACHE_PATH}")
    except (OSError, json.JSONDecodeError):
        pass


# ── Fetch desde ABC ────────────────────────────────────────────────────────

def _build_headers() -> dict:
    ua = random.choice(_USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://transitabilidad.abc.gob.bo/mapa",
        "Origin": "https://transitabilidad.abc.gob.bo",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
    }


def fetch_abc() -> list:
    """Descarga datos de ABC con headers de navegador + delay aleatorio."""
    delay = random.uniform(1.5, 5.0)
    _log(f"Pausa anti-bot: {delay:.1f}s ...")
    time.sleep(delay)

    headers = _build_headers()
    _log(f"User-Agent: {headers['User-Agent'][:60]}...")

    if _HAS_REQUESTS:
        with requests.Session() as session:
            session.headers.update(headers)
            response = session.get(ABC_DATA_URL, timeout=30)
            response.raise_for_status()
            data = response.json()
    else:
        from urllib.request import urlopen, Request  # noqa: PLC0415
        req = Request(ABC_DATA_URL, headers=headers)
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

    # Extraer lista de ítems
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "value"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


# ── Guardar JSON ───────────────────────────────────────────────────────────

def save_cache(items: list) -> None:
    """Guarda la lista de ítems en JSON con metadatos de timestamp."""
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "fetched_at": datetime.now(BOLIVIA_TZ).isoformat(timespec="seconds"),
        "fetched_at_ts": time.time(),
        "source": ABC_DATA_URL,
        "item_count": len(items),
        "items": items,
    }
    # Escritura atómica: escribir en .tmp y luego renombrar
    tmp_path = ABC_CACHE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp_path.replace(ABC_CACHE_PATH)
    _log(f"Guardado → {ABC_CACHE_PATH}  ({len(items)} ítems)")


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    force = "--force" in sys.argv
    status_only = "--status" in sys.argv

    _log("=" * 50)
    _log("descargar_abc.py — Mapa de Transitabilidad")
    _log("=" * 50)

    if not _HAS_REQUESTS:
        _log("AVISO: 'requests' no instalado. Usando urllib (sin headers Sec-Fetch-*).")
        _log("  Instala con: pip install requests")

    if status_only:
        show_status()
        return 0

    # Verificar si el cache está vigente
    age = get_cache_age()
    if age is not None and age < CACHE_TTL_SECONDS and not force:
        _log(
            f"Cache vigente ({age:.0f}s / {age/60:.1f} min). "
            "No se descargará. Usa --force para forzar."
        )
        show_status()
        return 0

    if age is None:
        _log("Cache no existe. Descargando...")
    else:
        _log(f"Cache vencido ({age:.0f}s). Descargando datos frescos...")

    try:
        items = fetch_abc()
    except Exception as exc:
        _log(f"ERROR al descargar: {exc}")
        return 1

    if not items:
        _log("ERROR: La API devolvió una lista vacía.")
        return 1

    save_cache(items)
    _log(f"OK — {len(items)} registros disponibles en cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
