"""Run the production web server with daily, retention-managed log files."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("OCR_WEB_LOG_DIR", APP_DIR / "logs")).resolve()
LOG_PREFIX = os.environ.get("OCR_WEB_LOG_PREFIX", "workbench_6008").strip() or "workbench_6008"
RETENTION_DAYS = max(0, int(os.environ.get("OCR_WEB_LOG_RETENTION_DAYS", "7")))
CHECK_INTERVAL_SECONDS = max(60, int(os.environ.get("OCR_WEB_LOG_CHECK_INTERVAL_SECONDS", "3600")))
TEE_STDOUT = os.environ.get("OCR_WEB_LOG_TEE_STDOUT", "1").strip().lower() not in {"0", "false", "no"}
HOST = os.environ.get("OCR_WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("OCR_WEB_PORT", "6008"))

stop_event = threading.Event()
child: subprocess.Popen[str] | None = None


def cleanup_expired_logs() -> None:
    if RETENTION_DAYS <= 0:
        return
    cutoff = time.time() - RETENTION_DAYS * 86400
    for path in LOG_DIR.glob(f"{LOG_PREFIX}_*.log"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except FileNotFoundError:
            pass


def cleanup_loop() -> None:
    while not stop_event.wait(CHECK_INTERVAL_SECONDS):
        cleanup_expired_logs()


def daily_log_path() -> Path:
    return LOG_DIR / f"{LOG_PREFIX}_{datetime.now().strftime('%Y-%m-%d')}.log"


def stop_child(_signum: int, _frame: object) -> None:
    stop_event.set()
    if child and child.poll() is None:
        child.terminate()


def main() -> int:
    global child
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_expired_logs()
    threading.Thread(target=cleanup_loop, name="log-cleaner", daemon=True).start()

    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "server_entry:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]
    child = subprocess.Popen(
        command,
        cwd=APP_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    current_path: Path | None = None
    log_file = None
    try:
        assert child.stdout is not None
        for line in child.stdout:
            next_path = daily_log_path()
            if next_path != current_path:
                if log_file:
                    log_file.close()
                current_path = next_path
                log_file = current_path.open("a", encoding="utf-8", buffering=1)
            log_file.write(line)
            if TEE_STDOUT:
                print(line, end="", flush=True)
        return child.wait()
    finally:
        stop_event.set()
        if log_file:
            log_file.close()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
