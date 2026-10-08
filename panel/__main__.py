"""python -m panel [--port 8080] [--speed 3] [--no-browser]"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from panel.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m panel", description="Sentinel Console")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--speed", type=float, default=3.0, help="replay speed multiplier (default 3)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Sentinel Console on {url}  (replay speed {args.speed}x)")
    uvicorn.run(create_app(speed=args.speed), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
