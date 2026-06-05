"""
RGF Lead Collector — minimaler Microservice für Landing-Page-Anfragen.
Schreibt E-Mails + API-Keys in SQLite. Welcome-Mails werden via Webhook
an den Host getriggert (himalaya).
"""
import sqlite3
import os
import json
import urllib.request
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DB_PATH = os.environ.get("LEAD_DB", "/data/leads.db")
RESGOV_API = os.environ.get("RESGOV_API", "http://resgov-api:8080")
ADMIN_TOKEN = os.environ.get("RESGOV_ADMIN_TOKEN", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS leads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "email TEXT NOT NULL UNIQUE,"
        "api_key TEXT,"
        "lang TEXT DEFAULT 'en',"
        "mail_sent INTEGER DEFAULT 0,"
        "created_at TEXT NOT NULL,"
        "source TEXT DEFAULT 'landing'"
        ")"
    )
    conn.commit()
    return conn


def generate_api_key(email: str) -> str:
    """Generate a new API key via ResGov admin API."""
    if not ADMIN_TOKEN:
        return ""
    try:
        data = json.dumps({"email": email}).encode()
        req = urllib.request.Request(
            f"{RESGOV_API}/api/v1/admin/generate-key",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Admin-Token": ADMIN_TOKEN,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("api_key", "")
    except Exception as e:
        print(f"Key generation failed: {e}")
        return ""


def notify_host(email: str, api_key: str, lang: str):
    """Notify host via Discord webhook to trigger welcome email."""
    if not DISCORD_WEBHOOK:
        return
    try:
        if lang == "de":
            content = f"🆕 Neuer Lead: {email} | Key: {api_key[:12]}... | Sprache: DE"
        else:
            content = f"🆕 New lead: {email} | Key: {api_key[:12]}... | Lang: EN"
        data = json.dumps({"content": content}).encode()
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as e:
        print(f"Webhook failed: {e}")


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
                "SELECT email, api_key, lang, mail_sent, created_at FROM leads ORDER BY id DESC"
            ).fetchall()
            db.close()
            self._respond(
                200,
                [
                    {
                        "email": r[0],
                        "api_key": r[1],
                        "lang": r[2],
                        "mail_sent": r[3],
                        "created_at": r[4],
                    }
                    for r in rows
                ],
            )
        elif parsed.path == "/pending-mails":
            """Return leads where mail hasn't been sent yet."""
            token = self.headers.get("X-Admin-Token", "")
            if not token:
                self._respond(401, {"error": "Missing X-Admin-Token"})
                return
            db = get_db()
            rows = db.execute(
                "SELECT id, email, api_key, lang FROM leads WHERE mail_sent = 0 ORDER BY id ASC LIMIT 20"
            ).fetchall()
            db.close()
            self._respond(
                200,
                [
                    {"id": r[0], "email": r[1], "api_key": r[2], "lang": r[3]}
                    for r in rows
                ],
            )
        elif parsed.path.startswith("/mark-sent/"):
            token = self.headers.get("X-Admin-Token", "")
            if not token:
                self._respond(401, {"error": "Missing X-Admin-Token"})
                return
            try:
                lead_id = int(parsed.path.split("/")[-1])
                db = get_db()
                db.execute("UPDATE leads SET mail_sent = 1 WHERE id = ?", (lead_id,))
                db.commit()
                db.close()
                self._respond(200, {"status": "ok"})
            except Exception as e:
                self._respond(400, {"error": str(e)})
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
        lang = (body.get("lang") or "en").strip().lower()

        if not email or "@" not in email or "." not in email.split("@")[-1]:
            self._respond(400, {"error": "Invalid email"})
            return

        try:
            db = get_db()
            db.execute(
                "INSERT OR IGNORE INTO leads (email, lang, created_at, source) VALUES (?, ?, ?, ?)",
                (email, lang, datetime.now(timezone.utc).isoformat(), "landing"),
            )
            db.commit()
            db.close()
        except Exception as e:
            self._respond(500, {"error": str(e)})
            return

        # Generate API key
        api_key = generate_api_key(email)

        # Store API key in DB
        if api_key:
            try:
                db = get_db()
                db.execute("UPDATE leads SET api_key = ? WHERE email = ?", (api_key, email))
                db.commit()
                db.close()
            except Exception as e:
                print(f"DB update failed: {e}")

        # Notify host (triggers welcome email)
        notify_host(email, api_key, lang)

        self._respond(200, {"status": "ok", "key_created": bool(api_key)})

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
        pass


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    server = HTTPServer(("0.0.0.0", 8090), Handler)
    print("Lead collector running on :8090")
    server.serve_forever()
