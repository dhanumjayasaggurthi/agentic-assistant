"""
RDI AI — startup script.

  python run.py           # dev mode (auto-reload on backend/frontend changes)
  python run.py --dev     # same as above — explicit dev flag
  python run.py --prod    # production mode (4 workers, no reload)
  python run.py --port 9000 --workers 8
"""
import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="RDI AI server")
    parser.add_argument("--dev",  action="store_true", help="Dev mode — auto-reload (default when no flag given)")
    parser.add_argument("--prod", action="store_true", help="Production mode — 4 workers, no reload")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--workers", type=int, default=None, help="Worker count (prod default: 4)")
    args = parser.parse_args()

    cmd = [sys.executable, "-m", "uvicorn", "backend.main:app"]
    cmd += ["--host", args.host, "--port", str(args.port)]

    if args.prod:
        workers = args.workers or 4
        cmd += [
            "--workers", str(workers),
            "--timeout-keep-alive", "75",
            "--log-level", "warning",
        ]
        print(f"[RDI AI] Production mode — {workers} workers on {args.host}:{args.port}")
    else:
        # Dev: reload ONLY backend/ and frontend/ — NOT workspace (avoids restart on file creation)
        cmd += [
            "--reload",
            "--reload-dir", "backend",
            "--reload-dir", "frontend",
            "--log-level", "info",
        ]
        if args.workers:
            cmd += ["--workers", str(args.workers)]
        print(f"[RDI AI] Dev mode — auto-reload on backend/frontend only — {args.host}:{args.port}")

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\n[RDI AI] Stopped.")


if __name__ == "__main__":
    main()
