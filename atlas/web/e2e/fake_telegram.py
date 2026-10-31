"""Minimal fake of the Telegram Bot API for local end-to-end tests (getMe, sendMessage).
Usage: python fake_telegram.py <port> <jsonl-log-path> <expected-token>
Records every sendMessage body to the log; rejects a wrong token with 401 like the real API."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, LOG, TOKEN = int(sys.argv[1]), sys.argv[2], sys.argv[3]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the console quiet
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != f"bot{TOKEN}":
            return self._send(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        if parts[1] == "getMe":
            return self._send(200, {"ok": True, "result": {"id": 1, "is_bot": True, "username": "fake_atlas_bot"}})
        if parts[1] == "sendMessage":
            with open(LOG, "a") as f:
                f.write(json.dumps(body) + "\n")
            return self._send(200, {"ok": True, "result": {"message_id": 1}})
        self._send(404, {"ok": False, "error_code": 404, "description": "Not Found"})


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
