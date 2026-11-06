#!/usr/bin/env python3
"""Family Finance Dashboard — Module 1 local server (Python standard library only).

Run:  python3 server.py            -> http://127.0.0.1:8765
Env:  FINANCE_DB=path/to.sqlite  FINANCE_PORT=8765
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import re
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from finance import core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.environ.get("FINANCE_DB", os.path.join(BASE_DIR, "data", "finance.sqlite"))
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
HOST = "127.0.0.1"
PORT = int(os.environ.get("FINANCE_PORT", "8765"))
MAX_BODY = 20 * 1024 * 1024

_lock = threading.Lock()  # serialize all DB access; single-user local app


def _csv_bytes(rows) -> bytes:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel shows Thai correctly


class Handler(BaseHTTPRequestHandler):
    server_version = "FamilyFinance/0.3"

    # ---- plumbing -------------------------------------------------------
    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, status, body: bytes, ctype, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise core.ValidationError("ข้อมูลที่ส่งมีขนาดใหญ่เกินไป")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise core.ValidationError("รูปแบบข้อมูลไม่ถูกต้อง (JSON)")
        return data

    def _same_origin(self) -> bool:
        # Basic CSRF guard: browsers send Origin on cross-site POSTs.
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://{HOST}:{PORT}", f"http://localhost:{PORT}")

    def _dispatch(self, method):
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith("/api/"):
            if method != "GET":
                return self._json({"error": "not found"}, 404)
            return self._static(path)
        if method != "GET" and not self._same_origin():
            return self._json({"error": "forbidden"}, 403)
        try:
            with _lock:
                conn = core.connect(DB_PATH)
                try:
                    return self._api(method, path, conn)
                finally:
                    conn.close()
        except core.NotFoundError as e:
            self._json({"error": str(e)}, 404)
        except core.ValidationError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # pragma: no cover
            self.log_error("internal error: %r", e)
            self._json({"error": "เกิดข้อผิดพลาดภายในระบบ"}, 500)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.realpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    # ---- API ------------------------------------------------------------
    def _api(self, method, path, conn):
        m = re.fullmatch
        if method == "GET" and path == "/api/state":
            return self._json(core.get_state(conn))

        if method == "POST" and path == "/api/accounts":
            b = self._body()
            aid = core.create_account(conn, b.get("name"), b.get("group_code"), b.get("note"))
            return self._json({"id": aid}, 201)

        if (r := m(r"/api/accounts/([\w-]+)", path)) and method == "PATCH":
            b = self._body()
            acc = core.get_account(conn, r.group(1))
            structural = ("group_code" in b and b["group_code"] != acc["group_code"]) or \
                         ("is_active" in b and bool(b["is_active"]) != bool(acc["is_active"]))
            if structural:
                core.backup_db(conn, BACKUP_DIR, "before-account-change")
            return self._json(core.update_account(conn, r.group(1), **b))

        if method == "POST" and path == "/api/groups":
            b = self._body()
            return self._json({"code": core.create_group(conn, b.get("name"), b.get("note"))}, 201)

        if (r := m(r"/api/groups/([\w-]+)", path)) and method == "PATCH":
            b = self._body()
            g = core.get_group(conn, r.group(1))
            if "is_active" in b and bool(b["is_active"]) != g["is_active"]:
                core.backup_db(conn, BACKUP_DIR, "before-group-change")
            return self._json(core.update_group(conn, r.group(1), **b))

        if (r := m(r"/api/groups/([\w-]+)/move", path)) and method == "POST":
            core.move_group(conn, r.group(1), self._body().get("direction"))
            return self._json({"ok": True})

        if (r := m(r"/api/accounts/([\w-]+)/move", path)) and method == "POST":
            core.move_account(conn, r.group(1), self._body().get("direction"))
            return self._json({"ok": True})

        if method == "POST" and path == "/api/periods":
            b = self._body()
            return self._json(core.add_period(conn, b.get("period"), b.get("carry_groups") or []), 201)

        if (r := m(r"/api/periods/([\d-]+)", path)) and method == "DELETE":
            core.delete_period(conn, r.group(1))
            return self._json({"ok": True})

        if (r := m(r"/api/periods/([\d-]+)/carry", path)) and method == "POST":
            b = self._body()
            return self._json({"carried": core.carry_forward(conn, r.group(1), b.get("account_ids"))})

        if method == "PUT" and path == "/api/balances":
            b = self._body()
            if "note" in b and "amount" not in b:
                core.set_balance_note(conn, b.get("account_id"), b.get("period"), b.get("note"))
                return self._json({"ok": True})
            res = core.set_balance(conn, b.get("account_id"), b.get("period"), b.get("amount"),
                                   b.get("note"), keep_note="note" not in b)
            return self._json({"ok": True, **res})

        if method == "GET" and path == "/api/dependents":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            return self._json(core.dependents(conn, q.get("account_id", [""])[0],
                                              core.parse_period(q.get("period", [""])[0])))

        if (r := m(r"/api/allocations/([\d-]+)/preview", path)) and method == "POST":
            return self._json(core.preview_allocation(conn, r.group(1), self._body().get("inputs")))

        if (r := m(r"/api/allocations/([\d-]+)/confirm", path)) and method == "POST":
            b = self._body()
            return self._json(core.confirm_allocation(conn, r.group(1), b.get("inputs"), b.get("balances"),
                                                      bool(b.get("accept_negative"))))

        if (r := m(r"/api/allocations/([\d-]+)", path)) and method == "DELETE":
            core.delete_allocation(conn, r.group(1))
            return self._json({"ok": True})

        if method == "GET" and path == "/api/audit":
            return self._json(core.list_audit(conn, 300))

        if method == "POST" and path == "/api/backup":
            p = core.backup_db(conn, BACKUP_DIR, "manual")
            return self._json({"path": p})

        if method == "GET" and path == "/api/backups":
            files = sorted((f for f in os.listdir(BACKUP_DIR) if f.endswith(".sqlite")), reverse=True) \
                if os.path.isdir(BACKUP_DIR) else []
            return self._json({"dir": BACKUP_DIR, "files": files[:50]})

        if method == "POST" and path == "/api/restore":
            data = self._body()
            p = core.backup_db(conn, BACKUP_DIR, "before-restore")
            res = core.restore_json(conn, data)
            return self._json({**res, "backup_before_restore": p})

        if method == "GET" and path.startswith("/api/export/"):
            name = path.rsplit("/", 1)[1]
            stamp = core._now()[:10]
            if name == "monthly.csv":
                body, fn = _csv_bytes(core.export_wide_rows(conn)), f"monthly-summary-{stamp}.csv"
            elif name == "balances.csv":
                body, fn = _csv_bytes(core.export_long_rows(conn)), f"balances-{stamp}.csv"
            elif name == "backup.json":
                body = json.dumps(core.export_json(conn), ensure_ascii=False, indent=1).encode("utf-8")
                fn = f"finance-backup-{stamp}.json"
            else:
                return self._json({"error": "not found"}, 404)
            ctype = "application/json" if fn.endswith(".json") else "text/csv; charset=utf-8"
            return self._send(200, body, ctype, {"Content-Disposition": f'attachment; filename="{fn}"'})

        return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)


def main():
    pre = core.backup_file_before_migration(DB_PATH, BACKUP_DIR)
    if pre:
        print(f"สำรองฐานข้อมูลก่อนอัปเกรดโครงสร้าง: {pre}")
    conn = core.connect(DB_PATH)
    today = f"finance-{core._now()[:10].replace('-', '')}"
    done_today = os.path.isdir(BACKUP_DIR) and any(
        f.startswith(today) and "startup" in f for f in os.listdir(BACKUP_DIR))
    if core.list_accounts(conn) and not done_today:  # one automatic backup per day
        core.backup_db(conn, BACKUP_DIR, "startup")
    conn.close()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Family Finance Dashboard: http://{HOST}:{PORT}  (DB: {DB_PATH})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
