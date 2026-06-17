# ── Python slim ────────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="Mapa Transitabilidad Bolivia"
LABEL description="Servidor del Mapa de Transitabilidad ABC Bolivia"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1. Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Código del servidor
COPY iniciar_mapa.py .
COPY descargar_abc.py .
COPY preparar_datos.py .

# 3. Frontend estático (nombre con espacio → sintaxis array JSON)
COPY ["mapa transitabilidad/", "mapa transitabilidad/"]

# 4. Seed data: los JSON de ABC se copian a /app/data-seed/
#    El entrypoint los siembra en /app/data/ al arrancar.
#    Así el servidor tiene datos desde el primer inicio,
#    incluso si hay un volumen vacío montado en /app/data/.
RUN mkdir -p /app/data-seed
COPY data/ /app/data-seed/

# 5. Entrypoint que siembra los datos y luego arranca el servidor
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8000/api/history', timeout=8)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-u", "iniciar_mapa.py", "--no-browser"]
