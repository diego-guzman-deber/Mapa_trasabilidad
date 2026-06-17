#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  exec python3 -u mantener_mapa.py
fi

if command -v python >/dev/null 2>&1; then
  exec python -u mantener_mapa.py
fi

echo "No se encontro Python 3."
echo "Instala Python 3 y vuelve a ejecutar este script."
exit 1
