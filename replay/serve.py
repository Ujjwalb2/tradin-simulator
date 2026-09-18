#!/usr/bin/env python3
"""Serve the chart replay tool (gold, NIFTY ...) on this machine and open it in the browser.

    python replay/serve.py              # http://127.0.0.1:8765
    python replay/serve.py 9000 --no-open

If the tool is already running on that port, this just opens it. Only the standard library
is needed. The data it serves is built by src/build_tf.py (gold) and src/build_nse.py (NSE).
"""
from __future__ import annotations

import errno
import functools
import http.server
import socketserver
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")  # a rebuilt data file must never be served stale
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # keep the terminal quiet
        pass


def already_serving(url: str) -> bool:
    """True when the replay tool itself is answering on this address."""
    try:
        with urllib.request.urlopen(url + "data/symbols.json", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def main() -> None:
    ports = [a for a in sys.argv[1:] if not a.startswith("--")]
    port = int(ports[0]) if ports else 8765
    opener = "--no-open" not in sys.argv
    if not (ROOT / "data" / "symbols.json").exists():
        sys.exit("replay/data is empty. Build it first:  python src/build_tf.py  (gold)  or  python src/build_nse.py  (NIFTY)")

    url = f"http://127.0.0.1:{port}/"
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    handler = functools.partial(Handler, directory=str(ROOT))
    try:
        httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        if not already_serving(url):
            sys.exit(f"Port {port} is taken by another program. Try:  python replay/serve.py {port + 1}")
        print(f"Chart replay is already running at {url}", flush=True)
        if opener:
            webbrowser.open(url)
        return

    with httpd:
        print(f"Chart replay running at {url}  (Ctrl+C to stop)", flush=True)
        if opener:
            threading.Timer(0.6, webbrowser.open, args=(url,)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
