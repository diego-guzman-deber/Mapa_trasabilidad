#!/usr/bin/env python3
"""
preparar_datos.py — Convierte el JSON descargado del navegador al formato
                    del cache del servidor y lo sube al repo.

Uso:
    1. Guardar la respuesta de https://transitabilidad.abc.gob.bo/api/v1/data
       como  data/latest_abc_data.json  (lo que el navegador muestra).
    2. Ejecutar:  python preparar_datos.py
    3. Hacer commit+push al repo para que Dokploy lo despliegue.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ABC_CACHE_PATH = DATA_DIR / "latest_abc_data.json"
MANUAL_CACHE_PATH = DATA_DIR / "manual_abc_data.json"
BOLIVIA_TZ = timezone(timedelta(hours=-4))


def log(msg: str) -> None:
    print(f"[{datetime.now(BOLIVIA_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def extract_items(data: object) -> list:
    """Extrae la lista de ítems de cualquier formato de respuesta de ABC."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "value"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def validate_items(items: list) -> bool:
    """Valida que los ítems tengan la estructura mínima esperada."""
    if not items:
        return False
    sample = items[0]
    required = {"id_estado"}
    missing = required - set(sample.keys())
    if missing:
        log(f"ADVERTENCIA: Falta campo '{missing}' en los ítems. ¿Es el formato correcto?")
    return True


def main() -> int:
    log("=" * 55)
    log("preparar_datos.py — Mapa de Transitabilidad")
    log("=" * 55)

    if not ABC_CACHE_PATH.exists():
        log(f"ERROR: No se encontró {ABC_CACHE_PATH}")
        log("")
        log("Pasos:")
        log("  1. Abre en el navegador:")
        log("     https://transitabilidad.abc.gob.bo/api/v1/data")
        log("  2. Guarda la página como:")
        log(f"     {ABC_CACHE_PATH}")
        log("  3. Vuelve a ejecutar este script.")
        return 1

    log(f"Leyendo: {ABC_CACHE_PATH.name} ({ABC_CACHE_PATH.stat().st_size:,} bytes)")

    try:
        with ABC_CACHE_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        log(f"ERROR: El archivo no es JSON válido: {exc}")
        log("Asegúrate de guardar solo el contenido JSON, no la página HTML.")
        return 1

    items = extract_items(raw)
    if not items:
        log("ERROR: No se encontraron ítems en el archivo.")
        log("El archivo debe ser un array JSON o contener un campo 'data'/'items'.")
        return 1

    log(f"Encontrados {len(items)} registros.")

    if not validate_items(items):
        log("ERROR: Los ítems no tienen el formato esperado.")
        return 1

    # ── 1. Guardar como cache principal (con metadatos) ────────────────────
    now = time.time()
    payload = {
        "fetched_at": datetime.now(BOLIVIA_TZ).isoformat(timespec="seconds"),
        "fetched_at_ts": now,
        "source": "navegador-manual",
        "item_count": len(items),
        "items": items,
    }
    tmp = ABC_CACHE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(ABC_CACHE_PATH)
    log(f"✅ Cache principal actualizado: {ABC_CACHE_PATH.name}")

    # ── 2. Guardar también como manual_abc_data.json (fallback) ───────────
    with MANUAL_CACHE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False)
    log(f"✅ Cache manual guardado: {MANUAL_CACHE_PATH.name}")

    # ── 3. Verificación rápida ─────────────────────────────────────────────
    estados = {}
    for item in items:
        e = int(item.get("id_estado") or 0)
        estados[e] = estados.get(e, 0) + 1

    nombres = {2: "Precaución", 3: "Desvío", 4: "Cerrado", 5: "Conflicto", 7: "Restricción"}
    log("")
    log("Resumen de estados:")
    for estado, count in sorted(estados.items(), reverse=True):
        nombre = nombres.get(estado, f"Estado {estado}")
        log(f"  {nombre} (id={estado}): {count}")
    log("")

    # ── 4. Instrucciones para subir al repo ───────────────────────────────
    log("Ahora ejecuta:")
    log("")
    log("  git add data/latest_abc_data.json data/manual_abc_data.json")
    log("  git commit -m \"data: actualizar cache ABC desde navegador\"")
    log("  git push")
    log("")
    log("Dokploy detectará el push y redesplegará con los datos reales.")
    log("")
    log("NOTA: El archivo data/ debe NO estar en .gitignore para esto.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
