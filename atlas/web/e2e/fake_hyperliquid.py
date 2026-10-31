"""Minimal fake of Hyperliquid's public /info endpoint for local end-to-end tests (userFillsByTime, userFunding).
Usage: python fake_hyperliquid.py <port> <jsonl-log-path>
Serves a fixed BTC round trip and one funding payment. Logs every request body so the test can prove no secret was ever sent."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, LOG = int(sys.argv[1]), sys.argv[2]
T = 1_767_225_600_000
FILLS = [
    {"coin": "BTC", "px": "60000.0", "sz": "0.1", "side": "B", "time": T, "startPosition": "0.0", "dir": "Open Long", "closedPnl": "0.0", "hash": "0xa1", "oid": 1, "crossed": True, "fee": "0.60", "tid": 101, "feeToken": "USDC"},
    {"coin": "BTC", "px": "61000.0", "sz": "0.1", "side": "A", "time": T + 7_200_000, "startPosition": "0.1", "dir": "Close Long", "closedPnl": "100.0", "hash": "0xa2", "oid": 2, "crossed": True, "fee": "0.61", "tid": 102, "feeToken": "USDC"},
    {"coin": "ETH", "px": "3000.0", "sz": "1", "side": "B", "time": T + 8_000_000, "startPosition": "0.0", "dir": "Open Long", "closedPnl": "0.0", "hash": "0xa3", "oid": 3, "crossed": True, "fee": "0.30", "tid": 103, "feeToken": "USDC"},
]
FUNDING = [{"time": T + 3_600_000, "hash": "0xf1", "delta": {"type": "funding", "coin": "BTC", "usdc": "-0.25", "szi": "0.1", "fundingRate": "0.0000125", "nSamples": None}}]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        with open(LOG, "a") as f:
            f.write(json.dumps(body) + "\n")
        out = FILLS if body.get("type") == "userFillsByTime" else FUNDING if body.get("type") == "userFunding" else []
        b = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
