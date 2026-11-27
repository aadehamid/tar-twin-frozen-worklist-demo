"""Echo server for the exe.dev hosting spike. Standard library only.

Listens on the given ports, logs peer address and headers as JSON lines,
and returns the same JSON. Header names keep their case and duplicates.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

args = sys.argv[1:]
BIND = "0.0.0.0"
if "--bind" in args:
    i = args.index("--bind")
    BIND = args[i + 1]
    del args[i:i + 2]
LOG = args[0]
PORTS = [int(p) for p in args[1:]]
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        record = {
            "port": self.server.server_address[1],
            "peer": self.client_address[0],
            "path": self.path,
            "headers": [[k, v] for k, v in self.headers.items()],
        }
        body = json.dumps(record).encode()
        with lock, open(LOG, "a") as f:
            f.write(body.decode() + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


for port in PORTS:
    srv = ThreadingHTTPServer((BIND, port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
threading.Event().wait()
