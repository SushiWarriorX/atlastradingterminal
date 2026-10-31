"""Tiny RSS server for the news e2e: /a.xml, /b.xml (same Fed story worded differently), /broken.xml (500), /sym.xml?s=AAPL (per-symbol feed).
Usage: python fake_rss.py <port>. Includes hostile content on purpose: a <script> tag and a javascript: link must come out inert."""
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

PORT = int(sys.argv[1])
fmt = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).strftime("%a, %d %b %Y %H:%M:%S GMT")  # noqa: E731


def feed(items):
    body = "".join(f"<item><title><![CDATA[{t}]]></title><link>{l}</link><guid>{g}</guid><pubDate>{fmt(m)}</pubDate><description><![CDATA[{d}]]></description></item>" for t, l, g, m, d in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'.encode()


A = feed([("Fed holds interest rates steady on Wednesday", "https://example.com/fed-a", "a1", 30, "The central bank <b>kept</b> its policy rate unchanged."),
          ("Why $TSLA fell sharply today", "https://example.com/tsla", "a2", 50, "Shares of the carmaker dropped."),
          ("<script>alert('xss')</script>Hostile headline", "javascript:alert(1)", "a3", 70, "<img src=x onerror=alert(2)> plain text only")])
B = feed([("Fed holds interest rates steady Wednesday, Powell says", "https://example.org/fed-b", "b1", 20, "Another outlet, same story."),
          ("Bitcoin climbs above resistance", "https://example.org/btc", "b2", 90, "")])
SYM = lambda s: feed([(f"{s} supplier raises full-year forecast", f"https://example.net/{s}", f"s-{s}", 15, "")])  # noqa: E731


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path == "/broken.xml":
            self.send_response(500)
            self.end_headers()
            return
        body = {"/a.xml": A, "/b.xml": B}.get(u.path) or (SYM(parse_qs(u.query).get("s", ["X"])[0]) if u.path == "/sym.xml" else None)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
