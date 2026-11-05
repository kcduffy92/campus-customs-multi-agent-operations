"""Run the campus-customs MCP server over HTTP for the backend (Homework 5, Problem 7).

backend/main.py starts this as a child process when the API starts and stops it when the API
stops. It serves the unchanged mcp_server/server.py tools, so the Problem 4 stdio setup in
.mcp.json keeps working as before.

The backend holds this process's stdin open. If the backend dies without a clean shutdown
(for example when `uvicorn --reload` restarts its worker on Windows), stdin closes and this
process exits at once, so a reload never leaves a second MCP server holding the port.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

import server  # noqa: E402  (mcp_server/server.py)


def _exit_when_parent_goes() -> None:
    try:
        sys.stdin.buffer.read()  # returns only when the backend closes the pipe or exits
    finally:
        os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="campus-customs MCP server, supervised by the backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    threading.Thread(target=_exit_when_parent_goes, daemon=True).start()
    server.mcp.run(transport="http", host=args.host, port=args.port, show_banner=False, log_level="warning")


if __name__ == "__main__":
    main()
