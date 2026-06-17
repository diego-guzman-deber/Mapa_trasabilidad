"""
iniciar_mapa.py — Servidor local del Mapa de Transitabilidad ABC Bolivia.

Estrategia anti-bloqueo:
  • Solo UNA petición a ABC por hora, realizada por el worker en background.
  • Los endpoints API leen exclusivamente del cache en memoria o disco.
  • Headers de navegador real (Chrome/Firefox) + User-Agent rotativo.
  • Delay aleatorio pre-petición (1.5 – 4.5 s) para no parecer bot.
  • Backoff exponencial en fallos: 5 min → 15 min → 30 min → 60 min.
  • GeoJSON de departamentos cacheado 24 h en disco (evita llamadas a ArcGIS).
  • El cache JSON incluye metadatos de timestamp para control de frescura.
  • Worker con jitter ± 5 min para no ser predecible.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
import functools
import json
import random
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

try:
    import requests as _req_lib  # type: ignore[import]
    _HAS_REQUESTS = True
except ImportError:
    _req_lib = None
    _HAS_REQUESTS = False

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "mapa transitabilidad"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "transitabilidad_history.db"
ABC_CACHE_PATH = DATA_DIR / "latest_abc_data.json"
GEOJSON_CACHE_PATH = DATA_DIR / "departments_geojson.json"
MANUAL_CACHE_PATH = DATA_DIR / "manual_abc_data.json"

# ── URLs ───────────────────────────────────────────────────────────────────
ABC_DATA_URL = "https://transitabilidad.abc.gob.bo/api/v1/data"
DEPARTMENTS_GEOJSON_URL = (
    "https://services7.arcgis.com/2Tnf1ndg2tSoKCCU/ArcGIS/rest/services/"
    "departamento/FeatureServer/0/query?where=1%3D1&outFields=*&f=geojson"
)

# ── Tiempos y límites ──────────────────────────────────────────────────────
# Máximo 1 consulta a ABC por hora. El worker respeta este TTL.
ABC_CACHE_TTL_SECONDS = 3600

# El GeoJSON de departamentos cambia muy raramente; cacheamos 24 h.
GEOJSON_CACHE_TTL_SECONDS = 86_400

# Backoff exponencial: fallo 1→5 min, 2→15 min, 3→30 min, 4+→60 min
ABC_BACKOFF_SCHEDULE = [300, 900, 1800, 3600]

# Worker: cada 1 hora ± 5 minutos (jitter anti-patrón)
WORKER_INTERVAL_BASE = 3600
WORKER_JITTER = 300

BOLIVIA_TZ = timezone(timedelta(hours=-4))
HOST = "0.0.0.0"
LOCAL_HOST = "127.0.0.1"
PORTS = range(8000, 8011)

# ── Locks y estado compartido ──────────────────────────────────────────────
DB_LOCK = threading.Lock()
ABC_LOCK = threading.Lock()
GEOJSON_LOCK = threading.Lock()

ABC_STATE: dict = {
    "items": None,        # lista en memoria
    "fetched_at": 0.0,    # timestamp último fetch exitoso
    "failed_until": 0.0,  # timestamp hasta el que no reintentar
    "last_error": "",
    "failure_count": 0,   # fallos consecutivos (para backoff)
}
GEOJSON_STATE: dict = {"data": None, "fetched_at": 0.0}

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


# ══════════════════════════════════════════════════════════════════════════
# HTTP SERVER
# ══════════════════════════════════════════════════════════════════════════

class Utf8StaticHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/history":
            self.send_json(get_history())
            return
        if path == "/api/cache/status":
            self.send_json(get_cache_status())
            return
        if path == "/api/today-summary":
            # Lee del cache; nunca dispara una petición a ABC
            try:
                self.send_json(save_today_snapshot())
            except Exception as exc:
                self.send_json(latest_history_summary(error=str(exc)))
            return
        if path == "/api/v1/data":
            # Sirve desde cache; el worker actualiza en background
            try:
                self.send_json(fetch_abc_data(enrich_departments=True))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=502)
            return
        if path == "/api/map/departments":
            try:
                self.send_json(fetch_department_geojson())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=502)
            return
        super().do_GET()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path):
        content_type = super().guess_type(path)
        if content_type in (
            "text/html", "text/css", "text/javascript", "application/javascript"
        ):
            return f"{content_type}; charset=utf-8"
        return content_type

    def log_message(self, format, *args):  # noqa: A002
        # Solo loguear requests al API, no archivos estáticos
        if args and "/api/" in str(args[0]):
            super().log_message(format, *args)


# ══════════════════════════════════════════════════════════════════════════
# CAPA DE RED — solo se llama desde el worker, nunca desde los endpoints
# ══════════════════════════════════════════════════════════════════════════

def _browser_headers(url: str) -> dict:
    """Headers que imitan un navegador moderno para la URL dada."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-BO,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": f"{origin}/mapa",
        "Origin": origin,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Connection": "keep-alive",
    }


def fetch_json_url(url: str, timeout: int = 30) -> object:
    """Descarga JSON con headers de navegador. Usa `requests` si está disponible."""
    headers = _browser_headers(url)
    if _HAS_REQUESTS:
        with _req_lib.Session() as session:
            session.headers.update(headers)
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
    # Fallback urllib
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_abc_from_network() -> list:
    """
    La ÚNICA función que realiza una petición real a ABC.
    Agrega un delay aleatorio para evitar detección como bot.
    Llamar solo desde el worker de background.
    """
    delay = random.uniform(1.5, 4.5)
    _log(f"[ABC] Pausa anti-bot: {delay:.1f}s ...")
    time.sleep(delay)
    data = fetch_json_url(ABC_DATA_URL)
    return extract_abc_items(data)


# ══════════════════════════════════════════════════════════════════════════
# ESTADO EN MEMORIA — ABC
# ══════════════════════════════════════════════════════════════════════════

def get_memory_abc_items(now: float | None = None) -> list:
    now = now or time.time()
    with ABC_LOCK:
        items = ABC_STATE["items"]
        fetched_at = ABC_STATE["fetched_at"]
    if items and now - fetched_at < ABC_CACHE_TTL_SECONDS:
        return [dict(item) for item in items]
    return []


def remember_abc_success(items: list) -> None:
    with ABC_LOCK:
        ABC_STATE["items"] = [dict(item) for item in items]
        ABC_STATE["fetched_at"] = time.time()
        ABC_STATE["failed_until"] = 0.0
        ABC_STATE["last_error"] = ""
        ABC_STATE["failure_count"] = 0
    _log(f"[ABC] Cache en memoria actualizado: {len(items)} registros.")


def remember_abc_failure(error) -> None:
    err_str = str(error)
    with ABC_LOCK:
        count = ABC_STATE["failure_count"] + 1
        ABC_STATE["failure_count"] = count
        idx = min(count - 1, len(ABC_BACKOFF_SCHEDULE) - 1)
        backoff = ABC_BACKOFF_SCHEDULE[idx]
        ABC_STATE["failed_until"] = time.time() + backoff
        ABC_STATE["last_error"] = err_str
    _log(f"[ABC] Fallo #{count}. Backoff: {backoff}s. Error: {err_str}")


def abc_retry_cooling_down(now: float | None = None) -> bool:
    now = now or time.time()
    with ABC_LOCK:
        return now < ABC_STATE["failed_until"]


def abc_recently_checked(now: float | None = None) -> bool:
    now = now or time.time()
    with ABC_LOCK:
        fetched_at = ABC_STATE["fetched_at"]
    return bool(fetched_at and now - fetched_at < ABC_CACHE_TTL_SECONDS)


def abc_cooldown_error() -> str:
    with ABC_LOCK:
        error = ABC_STATE["last_error"]
        failed_until = ABC_STATE["failed_until"]
        fetched_at = ABC_STATE["fetched_at"]
    retry_at = max(
        failed_until,
        (fetched_at + ABC_CACHE_TTL_SECONDS) if fetched_at else 0,
    )
    remaining = max(0, int(retry_at - time.time()))
    if error:
        return f"ABC temporalmente bloqueado ({error}). Reintento en {remaining}s"
    return f"Cache local vigente. Proxima consulta ABC en {remaining}s"


# ══════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA PARA DATOS ABC (solo cache, nunca red directa)
# ══════════════════════════════════════════════════════════════════════════

def fetch_abc_data(enrich_departments: bool = False, allow_fallback: bool = True) -> list:
    """
    Retorna ítems ABC desde cache (memoria → disco).
    NUNCA hace una petición de red a ABC; eso es exclusivo del worker.
    """
    # 1. Cache en memoria
    memory_items = get_memory_abc_items()
    if memory_items:
        return enrich_abc_items(memory_items) if enrich_departments else memory_items

    # 2. Cache en disco (incluso si está desactualizado, es mejor que nada)
    disk_items = load_cached_abc_data()
    if disk_items:
        remember_abc_success(disk_items)  # promover a memoria
        return enrich_abc_items(disk_items) if enrich_departments else disk_items

    # 3. Cadena de fallback
    if allow_fallback:
        error = (
            abc_cooldown_error()
            if abc_retry_cooling_down()
            else "Sin datos en caché. El worker los obtendrá pronto."
        )
        return fallback_abc_items(error, enrich_departments)

    raise RuntimeError("No hay datos ABC disponibles en caché.")


def refresh_abc_data() -> bool:
    """
    Llama a ABC si el cache tiene más de 1 hora. Actualiza memoria y disco.
    Solo debe ser invocado por el worker de background.
    Retorna True si se obtuvo data nueva.
    """
    if abc_recently_checked():
        _log("[ABC] Cache vigente, se omite la consulta.")
        return True

    if abc_retry_cooling_down():
        _log(f"[ABC] Backoff activo: {abc_cooldown_error()}")
        return False

    try:
        items = fetch_abc_from_network()
        if not items:
            remember_abc_failure("La API devolvió lista vacía")
            return False
        save_cached_abc_data(items)
        remember_abc_success(items)
        return True
    except Exception as exc:
        remember_abc_failure(exc)
        return False


# ══════════════════════════════════════════════════════════════════════════
# PERSISTENCIA JSON (cache en disco con metadatos de timestamp)
# ══════════════════════════════════════════════════════════════════════════

def extract_abc_items(data: object) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Formato envuelto: {"items": [...], "fetched_at": ...}
        for key in ("items", "data", "value"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def load_cached_abc_data() -> list:
    try:
        with ABC_CACHE_PATH.open("r", encoding="utf-8") as fh:
            content = json.load(fh)
        items = extract_abc_items(content)
        return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_cached_abc_data(items: list) -> None:
    """Guarda items en JSON con metadatos de timestamp para control de frescura."""
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "fetched_at": datetime.now(BOLIVIA_TZ).isoformat(timespec="seconds"),
        "fetched_at_ts": time.time(),
        "source": ABC_DATA_URL,
        "item_count": len(items),
        "items": items,
    }
    tmp_path = ABC_CACHE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp_path.replace(ABC_CACHE_PATH)  # escritura atómica
    _log(f"[Cache] {len(items)} ítems → {ABC_CACHE_PATH.name}")


def load_manual_abc_data() -> list:
    try:
        with MANUAL_CACHE_PATH.open("r", encoding="utf-8") as fh:
            return extract_abc_items(json.load(fh))
    except (OSError, json.JSONDecodeError):
        return []


def mark_cached_items(items: list, source: str) -> list:
    return [{**item, "__cached": True, "__cache_source": source} for item in items]


def fallback_abc_items(error: str, enrich_departments: bool) -> list:
    manual_items = load_manual_abc_data()
    if manual_items:
        _log(f"[Fallback] Usando carga manual. ({error})")
        items = mark_cached_items(manual_items, "carga manual")
        return enrich_abc_items(items) if enrich_departments else items

    cached_items = load_cached_abc_data()
    if cached_items:
        _log(f"[Fallback] Usando cache local. ({error})")
        items = mark_cached_items(cached_items, "cache local")
        return enrich_abc_items(items) if enrich_departments else items

    history_items = build_items_from_latest_history()
    if history_items:
        _log(f"[Fallback] Usando historial local. ({error})")
        return enrich_abc_items(history_items) if enrich_departments else history_items

    raise RuntimeError(error)


# ══════════════════════════════════════════════════════════════════════════
# GEOJSON DEPARTAMENTOS (cache 24 h en disco + memoria)
# ══════════════════════════════════════════════════════════════════════════

def fetch_department_geojson() -> dict:
    now = time.time()

    # 1. Memoria
    with GEOJSON_LOCK:
        geo_data = GEOJSON_STATE["data"]
        geo_ts = GEOJSON_STATE["fetched_at"]
    if geo_data and now - geo_ts < GEOJSON_CACHE_TTL_SECONDS:
        return geo_data

    # 2. Disco
    try:
        if GEOJSON_CACHE_PATH.exists():
            mtime = GEOJSON_CACHE_PATH.stat().st_mtime
            if now - mtime < GEOJSON_CACHE_TTL_SECONDS:
                with GEOJSON_CACHE_PATH.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and isinstance(data.get("features"), list):
                    with GEOJSON_LOCK:
                        GEOJSON_STATE["data"] = data
                        GEOJSON_STATE["fetched_at"] = mtime
                    return data
    except (OSError, json.JSONDecodeError):
        pass

    # 3. Red
    time.sleep(random.uniform(0.5, 2.0))
    data = fetch_json_url(DEPARTMENTS_GEOJSON_URL)
    if isinstance(data, dict) and isinstance(data.get("features"), list):
        try:
            DATA_DIR.mkdir(exist_ok=True)
            with GEOJSON_CACHE_PATH.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass
        with GEOJSON_LOCK:
            GEOJSON_STATE["data"] = data
            GEOJSON_STATE["fetched_at"] = time.time()
        return data

    return {"features": []}


# ══════════════════════════════════════════════════════════════════════════
# STATUS DEL CACHE
# ══════════════════════════════════════════════════════════════════════════

def get_cache_status() -> dict:
    manual_items = load_manual_abc_data()
    disk_items = load_cached_abc_data()

    disk_fetched_at = None
    disk_age_seconds = None
    try:
        if ABC_CACHE_PATH.exists():
            with ABC_CACHE_PATH.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                disk_fetched_at = raw.get("fetched_at")
                ts = raw.get("fetched_at_ts")
                disk_age_seconds = int(time.time() - float(ts)) if ts else None
            if disk_age_seconds is None:
                disk_age_seconds = int(time.time() - ABC_CACHE_PATH.stat().st_mtime)
    except (OSError, json.JSONDecodeError, TypeError):
        pass

    history = latest_history_summary()
    with ABC_LOCK:
        failed_until = ABC_STATE["failed_until"]
        fetched_at_ts = ABC_STATE["fetched_at"]
        last_error = ABC_STATE["last_error"]
        failure_count = ABC_STATE["failure_count"]

    return {
        "manual_cache": {
            "exists": MANUAL_CACHE_PATH.exists(),
            "items": len(manual_items),
            "path": str(MANUAL_CACHE_PATH),
        },
        "abc_cache": {
            "exists": ABC_CACHE_PATH.exists(),
            "items": len(disk_items),
            "fetched_at": disk_fetched_at,
            "age_seconds": disk_age_seconds,
            "fresh": (disk_age_seconds is not None and disk_age_seconds < ABC_CACHE_TTL_SECONDS),
            "path": str(ABC_CACHE_PATH),
        },
        "history": {
            "date": history.get("date"),
            "total": history.get("total"),
            "conflicts": history.get("conflicts"),
        },
        "abc_state": {
            "fetched_at": fetched_at_ts,
            "failed_until": failed_until,
            "failure_count": failure_count,
            "cooling_down": abc_retry_cooling_down(),
            "last_error": last_error,
            "next_retry_in_seconds": max(0, int(failed_until - time.time()))
            if failed_until > time.time()
            else 0,
        },
    }


# ══════════════════════════════════════════════════════════════════════════
# SNAPSHOT / HISTORIAL
# ══════════════════════════════════════════════════════════════════════════

def count_snapshot(items: list) -> dict:
    geojson = fetch_department_geojson()
    departments: dict = {}
    for item in items:
        department = (
            normalize_department(item.get("departamento"))
            or infer_department(item, geojson)
        )
        status = int(item.get("id_estado") or 0)
        if not department:
            continue
        bucket = departments.setdefault(
            department,
            {"total": 0, "conflicts": 0, "closed": 0, "caution": 0, "detours": 0, "restrictions": 0},
        )
        bucket["total"] += 1
        if status == 5:
            bucket["conflicts"] += 1
        if status == 4:
            bucket["closed"] += 1
        if status == 2:
            bucket["caution"] += 1
        if status == 3:
            bucket["detours"] += 1
        if status in (7, 8):
            bucket["restrictions"] += 1

    return {
        "date": bolivia_today(),
        "total": len(items),
        "conflicts": sum(1 for i in items if int(i.get("id_estado") or 0) == 5),
        "closed": sum(1 for i in items if int(i.get("id_estado") or 0) == 4),
        "caution": sum(1 for i in items if int(i.get("id_estado") or 0) == 2),
        "detours": sum(1 for i in items if int(i.get("id_estado") or 0) == 3),
        "restrictions": sum(1 for i in items if int(i.get("id_estado") or 0) in (7, 8)),
        "departments": departments,
        "updated_at": datetime.now(BOLIVIA_TZ).isoformat(timespec="seconds"),
    }


def save_today_snapshot() -> dict:
    """Guarda el resumen del día usando datos del cache (sin llamar a ABC)."""
    items = get_memory_abc_items() or load_cached_abc_data()
    if not items:
        history_items = build_items_from_latest_history()
        if not history_items:
            raise RuntimeError("Sin datos en caché para generar el resumen.")
        items = history_items

    snapshot = count_snapshot(items)
    with DB_LOCK:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO daily_counts (
                    date, total, conflicts, closed, caution, detours,
                    restrictions, departments_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    total        = excluded.total,
                    conflicts    = excluded.conflicts,
                    closed       = excluded.closed,
                    caution      = excluded.caution,
                    detours      = excluded.detours,
                    restrictions = excluded.restrictions,
                    departments_json = excluded.departments_json,
                    updated_at   = excluded.updated_at
                """,
                (
                    snapshot["date"],
                    snapshot["total"],
                    snapshot["conflicts"],
                    snapshot["closed"],
                    snapshot["caution"],
                    snapshot["detours"],
                    snapshot["restrictions"],
                    json.dumps(snapshot["departments"], ensure_ascii=False),
                    snapshot["updated_at"],
                ),
            )
            conn.commit()
    return snapshot


def get_history(limit: int = 60) -> dict:
    init_history_db()
    with DB_LOCK:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT date, total, conflicts, closed, caution, detours,
                       restrictions, departments_json, updated_at
                FROM daily_counts
                ORDER BY date DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    history = [
        {
            "date": row["date"],
            "total": row["total"],
            "conflicts": row["conflicts"],
            "closed": row["closed"],
            "caution": row["caution"],
            "detours": row["detours"],
            "restrictions": row["restrictions"],
            "departments": json.loads(row["departments_json"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return {"history": history}


def latest_history_summary(error: str | None = None) -> dict:
    init_history_db()
    with DB_LOCK:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT date, total, conflicts, closed, caution, detours,
                       restrictions, departments_json, updated_at
                FROM daily_counts
                ORDER BY date DESC
                LIMIT 1
                """
            ).fetchone()
    if not row:
        return {"error": error or "Sin historial local", "stale": True}
    return {
        "date": row["date"],
        "total": row["total"],
        "conflicts": row["conflicts"],
        "closed": row["closed"],
        "caution": row["caution"],
        "detours": row["detours"],
        "restrictions": row["restrictions"],
        "departments": json.loads(row["departments_json"]),
        "updated_at": row["updated_at"],
        "stale": True,
        "error": error,
    }


def build_items_from_latest_history() -> list:
    summary = latest_history_summary()
    departments = summary.get("departments") or {}
    if not departments:
        return []
    items = []
    for department, bucket in departments.items():
        status_plan = (
            (5, int(bucket.get("conflicts") or 0), "Conflicto social"),
            (4, int(bucket.get("closed") or 0), "Cerrado"),
            (3, int(bucket.get("detours") or 0), "Desvio"),
            (7, int(bucket.get("restrictions") or 0), "Restriccion"),
            (2, int(bucket.get("caution") or 0), "Precaucion"),
        )
        known_total = sum(count for _, count, _ in status_plan)
        remaining = max(0, int(bucket.get("total") or 0) - known_total)
        status_plan = status_plan + ((2, remaining, "Dato local"),)
        for status, count, event in status_plan:
            for index in range(count):
                items.append(
                    {
                        "__cached": True,
                        "id_estado": status,
                        "departamento": department,
                        "ruta": "",
                        "tramo": f"Resumen {department}",
                        "descr_sector": f"{event} - ultimo dato disponible",
                        "inicio_seccion": "Historial local",
                        "fin_seccion": summary.get("date") or "ABC no disponible",
                        "evento": {"descripcion_evento": event},
                        "id_registro": f"cache-{department}-{status}-{index}",
                        "id_seccion": index,
                        "__synthetic": True,
                    }
                )
    return items


# ══════════════════════════════════════════════════════════════════════════
# HELPERS DE GEOGRAFÍA
# ══════════════════════════════════════════════════════════════════════════

def normalize_department(value: object) -> str:
    return str(value or "").strip().upper()


def infer_department(item: dict, geojson: dict) -> str:
    try:
        lon = float(item.get("longitud_inicio_seccion"))
        lat = float(item.get("latitud_inicio_seccion"))
    except (TypeError, ValueError):
        return ""
    for feature in geojson.get("features", []):
        if geometry_contains_point(feature.get("geometry"), (lon, lat)):
            props = feature.get("properties") or {}
            return normalize_department(
                props.get("Departamento") or props.get("NOM_DEP")
            )
    return ""


def enrich_abc_items(items: list) -> list:
    geojson = fetch_department_geojson()
    enriched = []
    for item in items:
        copy = dict(item)
        if not normalize_department(copy.get("departamento")):
            department = infer_department(copy, geojson)
            if department:
                copy["departamento"] = department
        enriched.append(copy)
    return enriched


def geometry_contains_point(geometry: dict | None, point: tuple) -> bool:
    if not geometry:
        return False
    coordinates = geometry.get("coordinates") or []
    polygons = (
        coordinates if geometry.get("type") == "MultiPolygon" else [coordinates]
    )
    return any(polygon and point_in_ring(point, polygon[0]) for polygon in polygons)


def point_in_ring(point: tuple, ring: list) -> bool:
    x, y = point
    inside = False
    j = len(ring) - 1
    for i, current in enumerate(ring):
        previous = ring[j]
        xi, yi = float(current[0]), float(current[1])
        xj, yj = float(previous[0]), float(previous[1])
        intersects = (yi > y) != (yj > y) and x < (
            (xj - xi) * (y - yi)
        ) / ((yj - yi) or 1e-9) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


# ══════════════════════════════════════════════════════════════════════════
# BASE DE DATOS
# ══════════════════════════════════════════════════════════════════════════

def init_history_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_counts (
                date             TEXT PRIMARY KEY,
                total            INTEGER NOT NULL,
                conflicts        INTEGER NOT NULL,
                closed           INTEGER NOT NULL,
                caution          INTEGER NOT NULL,
                detours          INTEGER NOT NULL,
                restrictions     INTEGER NOT NULL,
                departments_json TEXT NOT NULL,
                updated_at       TEXT NOT NULL
            )
            """
        )
        conn.commit()


def bolivia_today() -> str:
    return datetime.now(BOLIVIA_TZ).date().isoformat()


# ══════════════════════════════════════════════════════════════════════════
# WORKER DE BACKGROUND (actualiza ABC una vez por hora con jitter)
# ══════════════════════════════════════════════════════════════════════════

def start_history_worker() -> None:
    def worker():
        # Delay inicial para que el servidor arranque primero
        initial = random.uniform(5, 20)
        _log(f"[Worker] Primer ciclo en {initial:.0f}s")
        time.sleep(initial)

        while True:
            try:
                _log("[Worker] Iniciando ciclo de actualización...")
                got_fresh = refresh_abc_data()
                if got_fresh:
                    snapshot = save_today_snapshot()
                    _log(
                        f"[Worker] OK — {snapshot['date']} | "
                        f"total={snapshot['total']} conflictos={snapshot['conflicts']}"
                    )
                else:
                    _log("[Worker] No se actualizó (backoff o cache vigente).")
            except Exception as exc:
                _log(f"[Worker] Error: {exc}")

            # Jitter: ± WORKER_JITTER segundos alrededor de 1 hora
            sleep_time = WORKER_INTERVAL_BASE + random.uniform(
                -WORKER_JITTER, WORKER_JITTER
            )
            next_run = datetime.now(BOLIVIA_TZ) + timedelta(seconds=sleep_time)
            _log(
                f"[Worker] Próxima consulta a las "
                f"{next_run.strftime('%H:%M:%S')} (en {sleep_time:.0f}s)"
            )
            time.sleep(sleep_time)

    t = threading.Thread(target=worker, daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════════════
# PRECARGA AL ARRANCAR
# ══════════════════════════════════════════════════════════════════════════

def preload_cache_from_disk() -> None:
    """
    Al iniciar: carga el JSON de disco en memoria si es reciente (<1 h).
    Evita que el worker haga una petición inmediata en cada reinicio.
    """
    disk_items = load_cached_abc_data()
    if not disk_items:
        _log("[Startup] Sin cache local de ABC.")
        return

    age: float | None = None
    try:
        with ABC_CACHE_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        ts = raw.get("fetched_at_ts") if isinstance(raw, dict) else None
        age = time.time() - float(ts) if ts else time.time() - ABC_CACHE_PATH.stat().st_mtime
    except (OSError, json.JSONDecodeError, TypeError):
        age = 0.0

    if age is not None and age < ABC_CACHE_TTL_SECONDS:
        remember_abc_success(disk_items)
        _log(
            f"[Startup] Cache válido: {len(disk_items)} registros, "
            f"antigüedad {age:.0f}s. No se consultará ABC al arrancar."
        )
    else:
        age_str = f"{age:.0f}s" if age is not None else "desconocida"
        _log(
            f"[Startup] Cache desactualizado (antigüedad {age_str}). "
            "El worker lo renovará pronto."
        )


# ══════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════════

def _log(msg: str) -> None:
    ts = datetime.now(BOLIVIA_TZ).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def find_server():
    handler = functools.partial(Utf8StaticHandler, directory=str(APP_DIR))
    for port in PORTS:
        try:
            return port, ThreadingHTTPServer((HOST, port), handler)
        except OSError:
            continue
    return None, None


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main(open_browser: bool = True) -> int:
    if not (APP_DIR / "index.html").exists():
        print("No se encontro la app.")
        print(f"Falta: {APP_DIR / 'index.html'}")
        input("Presiona Enter para cerrar...")
        return 1

    if not _HAS_REQUESTS:
        print("[Advertencia] 'requests' no instalado. Usando urllib (sin headers Sec-Fetch-*).")
        print("  Ejecuta: pip install requests")

    init_history_db()
    preload_cache_from_disk()   # ← carga JSON existente sin llamar a ABC
    start_history_worker()      # ← arranca el worker que llama a ABC cada ~1 h

    port, server = find_server()
    if server is None:
        print("No se pudo iniciar el servidor local.")
        print("Los puertos 8000 a 8010 estan ocupados.")
        input("Presiona Enter para cerrar...")
        return 1

    lan_ip = get_lan_ip()
    local_url = f"http://{LOCAL_HOST}:{port}/"
    network_url = f"http://{lan_ip}:{port}/"
    print()
    print("══════════════════════════════════════════")
    print("   Mapa de Transitabilidad — iniciado")
    print("══════════════════════════════════════════")
    print(f"  Local:  {local_url}")
    print(f"  Red:    {network_url}")
    print("  Cache:  /api/cache/status")
    print()
    print("  Ctrl+C para detener.")
    print("══════════════════════════════════════════")
    print()

    try:
        socket.create_connection((LOCAL_HOST, port), timeout=2).close()
        if open_browser:
            webbrowser.open(local_url)
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Servidor detenido.")
    except Exception as exc:
        print()
        print(f"Error: {exc}")
        input("Presiona Enter para cerrar...")
        return 1
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(open_browser="--no-browser" not in sys.argv))
