"""
RGF Lead Collector — minimaler Microservice für Landing-Page-Anfragen.
Schreibt E-Mails mit Timestamp in eine SQLite-DB. Keine externen Dependencies.
"""
import sqlite3
import os
import json
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DB_PATH = os.environ.get("LEAD_DB", "/data/leads.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS leads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "email TEXT NOT NULL UNIQUE,"
        "created_at TEXT NOT NULL,"
        "source TEXT DEFAULT 'landing'"
        ")"
    )
    conn.commit()
    return conn


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._respond(200, {"status": "ok"})
        elif parsed.path == "/leads":
            token = self.headers.get("X-Admin-Token", "")
            if not token:
                self._respond(401, {"error": "Missing X-Admin-Token"})
                return
            db = get_db()
            rows = db.execute(
                "SELECT email, created_at, source FROM leads ORDER BY id DESC"
            ).fetchall()
            db.close()
            self._respond(
                200,
                [{"email": r[0], "created_at": r[1], "source": r[2]} for r in rows],
            )
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/leads":
            self._respond(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or "{}")
        email = (body.get("email") or "").strip().lower()

        if not email or "@" not in email or "." not in email.split("@")[-1]:
            self._respond(400, {"error": "Invalid email"})
            return

        try:
            db = get_db()
            db.execute(
                "INSERT OR IGNORE INTO leads (email, created_at, source) VALUES (?, ?, ?)",
                (email, datetime.now(timezone.utc).isoformat(), "landing"),
            )
            db.commit()
            db.close()
        except Exception as e:
            self._respond(500, {"error": str(e)})
            return

        self._respond(200, {"status": "ok"})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        allowed = {"https://resgov.silentops.cloud", "https://api.resgov.silentops.cloud"}
        if origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "https://resgov.silentops.cloud")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")

    def log_message(self, fmt, *args):
        pass  # silent


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    server = HTTPServer(("0.0.0.0", 8090), Handler)
    print("Lead collector running on :8090")
    server.serve_forever()
