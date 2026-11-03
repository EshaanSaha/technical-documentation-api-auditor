"""Single-command launcher for Technical Documentation & API Consistency Auditor.

Starts:
1. FastAPI backend via Uvicorn (default: http://127.0.0.1:8000)
2. Streamlit frontend dashboard (default: http://localhost:8501)

Usage (from project root with .venv activated):
    python run.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.database.db import init_db  # noqa: E402
from scripts.generate_sample_files import ensure_sample_files  # noqa: E402


def _wait_for_backend(url: str, timeout_sec: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.4)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the Technical Documentation & API Consistency Auditor.")
    parser.add_argument("--backend-only", action="store_true", help="Start only the FastAPI backend server.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window automatically.")
    args = parser.parse_args()

    init_db()
    ensure_sample_files()

    python_exe = sys.executable
    api_url = f"http://{settings.api_host}:{settings.api_port}"
    ui_url = f"http://localhost:{settings.ui_port}"

    print("=" * 72)
    print(" Technical Documentation & API Consistency Auditor")
    print("=" * 72)
    print(f" Python executable : {python_exe}")
    print(f" FastAPI Backend   : {api_url}  (OpenAPI docs: {api_url}/docs)")
    if not args.backend_only:
        print(f" Streamlit UI      : {ui_url}")
    print("=" * 72)

    backend_cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "app.backend.main:app",
        "--host",
        settings.api_host,
        "--port",
        str(settings.api_port),
    ]
    backend_proc = subprocess.Popen(backend_cmd, cwd=str(PROJECT_ROOT))

    try:
        if not _wait_for_backend(api_url):
            print("[ERROR] FastAPI backend did not become ready in time.", file=sys.stderr)
            backend_proc.terminate()
            return 1
        print("[OK] FastAPI backend is online.")

        if args.backend_only:
            backend_proc.wait()
            return backend_proc.returncode or 0

        streamlit_cmd = [
            python_exe,
            "-m",
            "streamlit",
            "run",
            str(PROJECT_ROOT / "app" / "frontend" / "dashboard.py"),
            "--server.port",
            str(settings.ui_port),
            "--server.headless",
            "true" if args.no_browser else "false",
        ]
        ui_proc = subprocess.Popen(streamlit_cmd, cwd=str(PROJECT_ROOT))
        try:
            while True:
                if backend_proc.poll() is not None:
                    print("[WARN] Backend process exited.")
                    break
                if ui_proc.poll() is not None:
                    break
                time.sleep(0.5)
        finally:
            if ui_proc.poll() is None:
                ui_proc.terminate()
                try:
                    ui_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ui_proc.kill()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down services...")
    finally:
        if backend_proc.poll() is None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

