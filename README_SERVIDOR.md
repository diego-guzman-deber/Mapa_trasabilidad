# Mapa de Transitabilidad

Servidor local y API para el mapa de transitabilidad vial de Bolivia (fuente: ABC).

## Requisitos

- Python 3.10 o superior.
- Acceso saliente a internet desde el servidor para consultar ABC y el mapa base.
- Puerto 8000 abierto para la red local o pública.

```bash
pip install requests
```

> `requests` es el único paquete externo. Si no está instalado, el servidor
> cae automáticamente a `urllib` (modo de compatibilidad).

---

## Cómo levantar en local (Windows)

### Opción A — doble clic (más fácil)

1. Abrir `iniciar_windows.bat`.
2. El navegador se abre automáticamente en `http://127.0.0.1:8000/`.
3. Dejar la ventana abierta mientras se usa el mapa.

### Opción B — terminal

```powershell
cd "C:\ruta\al\proyecto"
pip install requests
python iniciar_mapa.py
```

### Opción C — descarga manual primero (si ABC está bloqueando)

```powershell
# 1. Descarga el JSON de ABC ahora mismo
python descargar_abc.py

# 2. Arranca el servidor (ya tendrá cache, no llamará a ABC al arrancar)
python iniciar_mapa.py
```

---

## Cómo levantar en Linux / servidor

```bash
pip install requests
chmod +x iniciar_linux.sh
./iniciar_linux.sh
```

Luego abrir:

```
http://IP_DEL_SERVIDOR:8000/
```

---

## Estrategia anti-bloqueo

El servidor **solo consulta ABC UNA VEZ POR HORA** y lo hace en segundo plano.
Los endpoints del API leen siempre del cache local (memoria → disco).

| Capa | Descripción |
|---|---|
| Cache en memoria | Items frescos (<1 h) en RAM, sin I/O |
| Cache en disco | `data/latest_abc_data.json` con metadatos de timestamp |
| GeoJSON departamentos | `data/departments_geojson.json`, TTL 24 h |
| Headers de navegador | User-Agent Chrome/Firefox rotativo + headers Sec-Fetch-* |
| Delay aleatorio | 1.5 – 4.5 s antes de cada petición a ABC |
| Backoff exponencial | Fallo 1→5 min, 2→15 min, 3→30 min, 4+→60 min |
| Jitter del worker | Intervalo de 1 hora ± 5 min para no ser predecible |
| Arranque sin ABC | Si el JSON tiene <1 h de antigüedad, no llama a ABC al iniciar |

---

## script `descargar_abc.py`

Descarga datos de ABC y los guarda en `data/latest_abc_data.json`.
Útil para pre-cargar el cache o programar descargas periódicas.

```bash
# Ver estado del cache
python descargar_abc.py --status

# Descargar si el cache tiene >1 hora (modo normal)
python descargar_abc.py

# Forzar descarga aunque el cache esté vigente
python descargar_abc.py --force
```

### Automatización en Windows (Task Scheduler)

1. Abrir **Programador de tareas** → Crear tarea básica.
2. Disparador: Diario, cada **2 horas**.
3. Acción: **Iniciar un programa**.
   - Programa: `python`
   - Argumentos: `C:\ruta\descargar_abc.py`
   - Inicio en: `C:\ruta\`

### Automatización en Linux (cron)

```bash
crontab -e
# Agregar:
0 */2 * * *  cd /ruta && python3 descargar_abc.py >> logs/descarga_abc.log 2>&1
```

---

## Despliegue en Dokploy

### `Dockerfile` sugerido

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "iniciar_mapa.py", "--no-browser"]
```

### Variables de entorno

No se requieren variables de entorno. El servidor es autocontenido.

### Persistencia de datos

Para no perder el historial y el cache entre reinicios, montar un volumen:

```yaml
# En la config de Dokploy / docker-compose
volumes:
  - ./data:/app/data
  - ./logs:/app/logs
```

---

## APIs locales

| Endpoint | Descripción |
|---|---|
| `/api/v1/data` | Datos ABC enriquecidos con departamento (desde cache) |
| `/api/map/departments` | GeoJSON departamental (cache 24 h) |
| `/api/today-summary` | Resumen del día (desde cache, guarda en DB) |
| `/api/history` | Historial diario guardado en SQLite |
| `/api/cache/status` | Estado detallado del cache y backoff |

---

## Archivos importantes

| Archivo | Descripción |
|---|---|
| `mapa transitabilidad/` | App web (HTML, JS, CSS, logos) |
| `iniciar_mapa.py` | Servidor HTTP + APIs locales |
| `descargar_abc.py` | Script de descarga standalone |
| `mantener_mapa.py` | Guardian que reinicia el servidor si se cae |
| `data/latest_abc_data.json` | Cache de puntos ABC (incluye timestamp) |
| `data/departments_geojson.json` | Cache GeoJSON departamentos (24 h) |
| `data/transitabilidad_history.db` | Historial diario SQLite |
| `data/manual_abc_data.json` | Carga manual opcional cuando ABC está bloqueado |
| `logs/descarga_abc.log` | Log de descargas del script standalone |
