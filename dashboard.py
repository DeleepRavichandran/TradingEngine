"""Serve the read-only trade dashboard on localhost, optionally following one journal."""
import argparse
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = Path(__file__).resolve().with_name("dashboard")
TYPES = {"index.html": "text/html", "journal.js": "text/javascript", "app.js": "text/javascript",
         "style.css": "text/css", "demo.json": "application/json"}


class Dashboard(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/session.jsonl" and self.server.journal is not None:
            source = self.server.journal
            media = "application/x-ndjson"
        elif path == "/" or path[1:] in TYPES:
            name = path[1:] or "index.html"
            source = ASSETS / name
            media = TYPES[name]
        else:
            self.send_error(404)
            return
        try:
            with source.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                tag = f'"{stat.st_ino}-{stat.st_mtime_ns}-{stat.st_size}"'
                if self.headers.get("If-None-Match") == tag:
                    self.send_response(304)
                    self.send_header("ETag", tag)
                    self.end_headers()
                    return
                data = handle.read(stat.st_size)
        except OSError:
            self.send_error(404, "File unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", media + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", tag)
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, help="Watch the specified solo.py session journal")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Dashboard) as server:
        server.journal = args.journal
        suffix = "?watch=1" if args.journal is not None else ""
        print(f"http://127.0.0.1:{server.server_port}/{suffix}", flush=True)
        server.serve_forever()
