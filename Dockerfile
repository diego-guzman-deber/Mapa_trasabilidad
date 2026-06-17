# ── Etapa única: Python slim ───────────────────────────────────────────────
FROM python:3.12-slim

# Metadatos
LABEL maintainer="Mapa Transitabilidad Bolivia"
LABEL description="Servidor del Mapa de Transitabilidad ABC Bolivia"

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# 1. Instalar dependencias Python primero (capa cacheada)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copiar el código del servidor
COPY iniciar_mapa.py .
COPY descargar_abc.py .

# 3. Copiar el frontend estático
COPY "mapa transitabilidad/" "./mapa transitabilidad/"

# 4. Copiar el sample de data manual (el directorio data/ real es un volumen)
RUN mkdir -p data
COPY data/manual_abc_data.sample.json data/manual_abc_data.sample.json

# Puerto que expone el servidor Python
EXPOSE 8000

# Health check: verifica que la API responde
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "from urllib.request import urlopen; urlopen('http://localhost:8000/api/history', timeout=8)" || exit 1

# Arrancar sin abrir browser (modo servidor)
CMD ["python", "-u", "iniciar_mapa.py", "--no-browser"]
