"""python -m controlplane [--host 0.0.0.0] [--port 8000]"""
from __future__ import annotations

import argparse

import uvicorn

from controlplane.app import create_app
from sentinel.llm import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m controlplane", description="AIOps Sentinel control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_dotenv()
    print(f"AIOps Sentinel on http://{args.host}:{args.port}/")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
