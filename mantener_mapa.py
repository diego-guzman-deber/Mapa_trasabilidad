from pathlib import Path
from urllib.request import urlopen
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
SERVER_SCRIPT = ROOT / "iniciar_mapa.py"
HEALTH_URL = "http://127.0.0.1:8000/api/history"
CHECK_SECONDS = 8
RESTART_SECONDS = 3


def write_guard_log(message):
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with (LOG_DIR / "mapa-guardian.log").open("a", encoding="utf-8") as log:
        log.write(f"[{timestamp}] {message}\n")


def is_healthy():
    try:
        with urlopen(HEALTH_URL, timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def start_server():
    LOG_DIR.mkdir(exist_ok=True)
    server_log = (LOG_DIR / "mapa-server.log").open("a", encoding="utf-8")
    popen_options = {}
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    write_guard_log("Iniciando servidor del mapa")
    return subprocess.Popen(
        [sys.executable, "-u", str(SERVER_SCRIPT), "--no-browser"],
        cwd=str(ROOT),
        stdout=server_log,
        stderr=subprocess.STDOUT,
        **popen_options,
    )


def main():
    write_guard_log("Guardian iniciado")
    process = None

    while True:
        if is_healthy():
            time.sleep(CHECK_SECONDS)
            continue

        if process and process.poll() is None:
            write_guard_log("Servidor no responde; terminando proceso para reinicio")
            try:
                process.terminate()
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=8)
            except OSError as exc:
                write_guard_log(f"No se pudo terminar el proceso: {exc}")

        if process and process.poll() is not None:
            write_guard_log(f"Servidor cerrado con codigo {process.returncode}")

        time.sleep(RESTART_SECONDS)
        process = start_server()
        time.sleep(CHECK_SECONDS)


if __name__ == "__main__":
    main()
