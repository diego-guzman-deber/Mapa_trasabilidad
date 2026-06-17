#!/bin/sh
# entrypoint.sh — Siembra los datos del repo en /app/data al arrancar.
# Si hay un volumen montado en /app/data, los archivos del repo
# se copian encima para garantizar que siempre haya datos frescos.
set -e

DATA_DIR="/app/data"
SEED_DIR="/app/data-seed"

mkdir -p "$DATA_DIR"

echo "[Entrypoint] Sembrando datos iniciales..."
for f in latest_abc_data.json manual_abc_data.json manual_abc_data.sample.json departments_geojson.json; do
    src="$SEED_DIR/$f"
    dst="$DATA_DIR/$f"
    if [ -f "$src" ]; then
        cp "$src" "$dst"
        echo "[Entrypoint]   Copiado: $f"
    fi
done

echo "[Entrypoint] Datos listos. Iniciando servidor..."
exec "$@"
