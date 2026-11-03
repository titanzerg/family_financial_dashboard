"""Core data model and calculations for Module 1 — Monthly Asset Summary.

Money is stored as integer satang (1 THB = 100 satang) to avoid float errors.
A missing balance (no row) is NOT zero; zero must be entered explicitly.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation

SCHEMA_VERSION = 1

DEFAULT_GROUPS = [
    ("A", "บัญชีบริหารค่าใช้จ่ายและเงินกันไว้", "Expense-management & earmarked", 1,
     "เงินกันไว้สำหรับค่าใช้จ่ายตามแผน และบัญชีใช้จ่ายรายเดือน — ไม่ใช่เงินเหลือใช้"),
    ("B", "เงินฝากและเงินออม", "Bank deposits & savings", 2,
     "บัญชีเงินฝาก/ออมทรัพย์ที่ไม่ได้ใช้จ่ายประจำ"),
    ("C", "การลงทุนและสินทรัพย์ที่อัปเดตไม่บ่อย", "Investments & low-frequency assets", 3,
     "หุ้น สหกรณ์ ทองคำ ฯลฯ — มูลค่าอาจไม่ได้อัปเดตทุกเดือน"),
    ("D", "เงินสำรองโปะบ้าน (ยืดหยุ่น)", "Flexible mortgage reserve", 4,
     "เงินที่กันไว้เผื่อโปะสินเชื่อบ้าน"),
]
GROUP_CODES = tuple(g[0] for g in DEFAULT_GROUPS)


class ValidationError(Exception):
    """Raised for invalid user input; message is user-facing (Thai)."""


class NotFoundError(ValidationError):
    pass


# --------------------------------------------------------------------------
# Connection & migrations
# --------------------------------------------------------------------------

def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit; explicit txns
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"Database schema v{version} is newer than this program (v{SCHEMA_VERSION})")
    if version < 1:
        with transaction(conn):
            for stmt in _SCHEMA_V1:
                conn.execute(stmt)
            conn.executemany(
                "INSERT OR IGNORE INTO account_groups(code, name_th, name_en, sort_order, description)"
                " VALUES (?,?,?,?,?)", DEFAULT_GROUPS)
            conn.execute("PRAGMA user_version = 1")
    # Future migrations: `if version < 2: ...` — test against a copy of real data first.


_SCHEMA_V1 = [
    """CREATE TABLE IF NOT EXISTS account_groups (
        code TEXT PRIMARY KEY,
        name_th TEXT NOT NULL,
        name_en TEXT NOT NULL,
        sort_order INTEGER NOT NULL,
        description TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        group_code TEXT NOT NULL REFERENCES account_groups(code),
        sort_order INTEGER NOT NULL,
        note TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS periods (
        period TEXT PRIMARY KEY,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS balances (
        account_id TEXT NOT NULL REFERENCES accounts(id),
        period TEXT NOT NULL REFERENCES periods(period),
        amount_satang INTEGER NOT NULL,
        is_carried INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (account_id, period)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        action TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT
    )""",
]


class transaction:
    """Context manager for an explicit transaction on an autocommit connection."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _audit(conn, entity, entity_id, action, old=None, new=None):
    conn.execute(
        "INSERT INTO audit_log(ts, entity, entity_id, action, old_value, new_value) VALUES (?,?,?,?,?,?)",
        (_now(), entity, entity_id, action,
         None if old is None else json.dumps(old, ensure_ascii=False),
         None if new is None else json.dumps(new, ensure_ascii=False)))


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_period(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("รูปแบบเดือนไม่ถูกต้อง (ต้องเป็น YYYY-MM)")
    m = _PERIOD_RE.match(value.strip())
    if not m:
        raise ValidationError(f"รูปแบบเดือนไม่ถูกต้อง: {value!r} (ต้องเป็น YYYY-MM ปี ค.ศ.)")
    year, month = int(m.group(1)), int(m.group(2))
    if not (1900 <= year <= 2200):
        raise ValidationError(f"ปีไม่ถูกต้อง: {year} (ใช้ปี ค.ศ.)")
    if not (1 <= month <= 12):
        raise ValidationError(f"เดือนไม่ถูกต้อง: {month}")
    return f"{year:04d}-{month:02d}"


def parse_amount(value) -> int | None:
    """Parse user input into satang. Empty/None -> None (not recorded)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("ยอดเงินต้องเป็นตัวเลข")
    if isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("฿", "").replace(" ", "")
        if text == "":
            return None
    else:
        raise ValidationError("ยอดเงินต้องเป็นตัวเลข")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValidationError(f"ยอดเงินต้องเป็นตัวเลข: {value!r}")
    if not d.is_finite():
        raise ValidationError("ยอดเงินต้องเป็นตัวเลข")
    satang = d * 100
    if satang != satang.to_integral_value():
        raise ValidationError("ยอดเงินมีทศนิยมได้ไม่เกิน 2 ตำแหน่ง")
    if abs(satang) > Decimal(10) ** 15:
        raise ValidationError("ยอดเงินมากเกินไป")
    return int(satang)


def format_amount(satang: int | None) -> str:
    if satang is None:
        return ""
    sign = "-" if satang < 0 else ""
    s = abs(satang)
    return f"{sign}{s // 100}.{s % 100:02d}"


def _clean_text(value, field, required=False, max_len=500):
    if value is None:
        if required:
            raise ValidationError(f"กรุณาระบุ{field}")
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field}ไม่ถูกต้อง")
    v = value.strip()
    if required and not v:
        raise ValidationError(f"กรุณาระบุ{field}")
    if len(v) > max_len:
        raise ValidationError(f"{field}ยาวเกินไป")
    return v or None


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def list_groups(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM account_groups ORDER BY sort_order")]


def list_accounts(conn):
    rows = conn.execute(
        "SELECT a.* FROM accounts a JOIN account_groups g ON g.code = a.group_code"
        " ORDER BY g.sort_order, a.sort_order, a.created_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        out.append(d)
    return out


def get_account(conn, account_id):
    r = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not r:
        raise NotFoundError("ไม่พบบัญชี")
    d = dict(r)
    d["is_active"] = bool(d["is_active"])
    return d


def _check_group(conn, code):
    if not conn.execute("SELECT 1 FROM account_groups WHERE code = ?", (code,)).fetchone():
        raise ValidationError(f"ไม่พบกลุ่มบัญชี: {code!r}")


def _next_sort(conn, group_code):
    return conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM accounts WHERE group_code = ?",
                        (group_code,)).fetchone()[0]


def create_account(conn, name, group_code, note=None) -> str:
    name = _clean_text(name, "ชื่อบัญชี", required=True, max_len=100)
    note = _clean_text(note, "หมายเหตุ")
    _check_group(conn, group_code)
    account_id = "acc_" + uuid.uuid4().hex[:12]
    now = _now()
    with transaction(conn):
        conn.execute(
            "INSERT INTO accounts(id, name, group_code, sort_order, note, is_active, created_at, updated_at)"
            " VALUES (?,?,?,?,?,1,?,?)",
            (account_id, name, group_code, _next_sort(conn, group_code), note, now, now))
        _audit(conn, "account", account_id, "create", None,
               {"name": name, "group_code": group_code, "note": note})
    return account_id


def update_account(conn, account_id, **changes) -> dict:
    """Rename / regroup / annotate / (de)activate. The Account ID never changes."""
    acc = get_account(conn, account_id)
    allowed = {"name", "group_code", "note", "is_active"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError(f"ไม่รองรับการแก้ไขฟิลด์: {', '.join(sorted(unknown))}")
    new = {}
    if "name" in changes:
        new["name"] = _clean_text(changes["name"], "ชื่อบัญชี", required=True, max_len=100)
    if "note" in changes:
        new["note"] = _clean_text(changes["note"], "หมายเหตุ")
    if "is_active" in changes:
        if not isinstance(changes["is_active"], bool):
            raise ValidationError("สถานะบัญชีไม่ถูกต้อง")
        new["is_active"] = int(changes["is_active"])
    if "group_code" in changes:
        _check_group(conn, changes["group_code"])
        new["group_code"] = changes["group_code"]
    new = {k: v for k, v in new.items() if (int(acc[k]) if k == "is_active" else acc[k]) != v}
    if not new:
        return acc
    with transaction(conn):
        if "group_code" in new:
            new["sort_order"] = _next_sort(conn, new["group_code"])
        new["updated_at"] = _now()
        sets = ", ".join(f"{k} = ?" for k in new)
        conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", (*new.values(), account_id))
        old = {k: acc[k] for k in new if k not in ("updated_at", "sort_order")}
        _audit(conn, "account", account_id, "update", old,
               {k: v for k, v in new.items() if k not in ("updated_at", "sort_order")})
    return get_account(conn, account_id)


def move_account(conn, account_id, direction) -> None:
    if direction not in ("up", "down"):
        raise ValidationError("ทิศทางไม่ถูกต้อง")
    acc = get_account(conn, account_id)
    with transaction(conn):
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM accounts WHERE group_code = ? ORDER BY sort_order, created_at",
            (acc["group_code"],))]
        i = ids.index(account_id)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        for n, aid in enumerate(ids, start=1):
            conn.execute("UPDATE accounts SET sort_order = ? WHERE id = ?", (n, aid))


# --------------------------------------------------------------------------
# Periods & balances
# --------------------------------------------------------------------------

def list_periods(conn):
    return [r[0] for r in conn.execute("SELECT period FROM periods ORDER BY period")]


def add_period(conn, period, carry_groups=()) -> dict:
    period = parse_period(period)
    for g in carry_groups:
        _check_group(conn, g)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM periods WHERE period = ?", (period,)).fetchone():
            raise ValidationError(f"มีเดือน {period} อยู่แล้ว")
        conn.execute("INSERT INTO periods(period, created_at) VALUES (?,?)", (period, _now()))
        _audit(conn, "period", period, "create")
        carried = 0
        if carry_groups:
            ids = [r[0] for r in conn.execute(
                f"SELECT id FROM accounts WHERE is_active = 1 AND group_code IN ({','.join('?' * len(carry_groups))})",
                tuple(carry_groups))]
            carried = _carry_forward(conn, period, ids)
    return {"period": period, "carried": carried}


def delete_period(conn, period) -> None:
    period = parse_period(period)
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM periods WHERE period = ?", (period,)).fetchone():
            raise NotFoundError(f"ไม่พบเดือน {period}")
        n = conn.execute("SELECT COUNT(*) FROM balances WHERE period = ?", (period,)).fetchone()[0]
        if n:
            raise ValidationError(f"ลบเดือน {period} ไม่ได้ เพราะมียอดบันทึกอยู่ {n} รายการ (ลบได้เฉพาะเดือนที่ว่าง)")
        conn.execute("DELETE FROM periods WHERE period = ?", (period,))
        _audit(conn, "period", period, "delete")


def set_balance(conn, account_id, period, amount, note=None, keep_note=False) -> dict | None:
    """Create/update/clear one month-end balance. amount=None/'' clears the entry."""
    period = parse_period(period)
    get_account(conn, account_id)
    satang = parse_amount(amount)
    note = _clean_text(note, "หมายเหตุ")
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM periods WHERE period = ?", (period,)).fetchone():
            conn.execute("INSERT INTO periods(period, created_at) VALUES (?,?)", (period, _now()))
            _audit(conn, "period", period, "create")
        old = conn.execute("SELECT amount_satang, is_carried, note FROM balances WHERE account_id = ? AND period = ?",
                           (account_id, period)).fetchone()
        old_d = dict(old) if old else None
        key = f"{account_id}@{period}"
        if satang is None:
            if old:
                conn.execute("DELETE FROM balances WHERE account_id = ? AND period = ?", (account_id, period))
                _audit(conn, "balance", key, "clear", old_d, None)
            return None
        if keep_note and old:
            note = old["note"]
        new_d = {"amount_satang": satang, "is_carried": 0, "note": note}
        if old_d == new_d:
            return new_d
        conn.execute(
            "INSERT INTO balances(account_id, period, amount_satang, is_carried, note, updated_at)"
            " VALUES (?,?,?,0,?,?) ON CONFLICT(account_id, period) DO UPDATE SET"
            " amount_satang = excluded.amount_satang, is_carried = 0, note = excluded.note,"
            " updated_at = excluded.updated_at",
            (account_id, period, satang, note, _now()))
        _audit(conn, "balance", key, "update" if old else "create", old_d, new_d)
        return new_d


def set_balance_note(conn, account_id, period, note) -> None:
    period = parse_period(period)
    note = _clean_text(note, "หมายเหตุ")
    with transaction(conn):
        old = conn.execute("SELECT note FROM balances WHERE account_id = ? AND period = ?",
                           (account_id, period)).fetchone()
        if not old:
            raise ValidationError("ต้องบันทึกยอดก่อนจึงจะใส่หมายเหตุได้")
        if old["note"] == note:
            return
        conn.execute("UPDATE balances SET note = ?, updated_at = ? WHERE account_id = ? AND period = ?",
                     (note, _now(), account_id, period))
        _audit(conn, "balance", f"{account_id}@{period}", "note", {"note": old["note"]}, {"note": note})


def carry_forward(conn, period, account_ids=None) -> int:
    """Fill EMPTY cells of active accounts with their latest earlier balance, flagged as carried."""
    period = parse_period(period)
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM periods WHERE period = ?", (period,)).fetchone():
            raise NotFoundError(f"ไม่พบเดือน {period}")
        if account_ids is None:
            account_ids = [r[0] for r in conn.execute("SELECT id FROM accounts WHERE is_active = 1")]
        return _carry_forward(conn, period, account_ids)


def _carry_forward(conn, period, account_ids) -> int:
    n = 0
    for aid in account_ids:
        if conn.execute("SELECT 1 FROM balances WHERE account_id = ? AND period = ?", (aid, period)).fetchone():
            continue
        prev = conn.execute(
            "SELECT period, amount_satang FROM balances WHERE account_id = ? AND period < ?"
            " ORDER BY period DESC LIMIT 1", (aid, period)).fetchone()
        if not prev:
            continue
        conn.execute(
            "INSERT INTO balances(account_id, period, amount_satang, is_carried, note, updated_at)"
            " VALUES (?,?,?,1,NULL,?)", (aid, period, prev["amount_satang"], _now()))
        _audit(conn, "balance", f"{aid}@{period}", "carry", None,
               {"amount_satang": prev["amount_satang"], "from_period": prev["period"]})
        n += 1
    return n


def list_balances(conn):
    return [dict(r) for r in conn.execute(
        "SELECT account_id, period, amount_satang, is_carried, note, updated_at FROM balances"
        " ORDER BY period, account_id")]


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------

def cell_status(account, period, entry, first, last) -> str:
    """entered | carried | missing | not_yet | closed."""
    if entry is not None:
        return "carried" if entry["is_carried"] else "entered"
    if first is None or period < first:
        return "not_yet"
    if account["is_active"] or period < last:
        return "missing"
    return "closed"


def compute(conn) -> dict:
    """Totals, month-to-month changes and per-account metadata. Pure read."""
    groups = list_groups(conn)
    accounts = list_accounts(conn)
    periods = list_periods(conn)
    balances = list_balances(conn)
    by_key = {(b["account_id"], b["period"]): b for b in balances}

    meta = {}
    for a in accounts:
        mine = [b for b in balances if b["account_id"] == a["id"]]
        verified = [b["period"] for b in mine if not b["is_carried"]]
        meta[a["id"]] = {
            "first_period": mine[0]["period"] if mine else None,
            "last_period": mine[-1]["period"] if mine else None,
            "last_verified_period": verified[-1] if verified else None,
        }

    summary = []
    prev = None
    for p in periods:
        total = 0
        group_totals = {g["code"]: 0 for g in groups}
        group_counts = {g["code"]: 0 for g in groups}
        entered = carried = 0
        missing, carried_accounts = [], []
        for a in accounts:
            e = by_key.get((a["id"], p))
            m = meta[a["id"]]
            st = cell_status(a, p, e, m["first_period"], m["last_period"])
            if e is not None:
                total += e["amount_satang"]
                group_totals[a["group_code"]] += e["amount_satang"]
                group_counts[a["group_code"]] += 1
                if e["is_carried"]:
                    carried += 1
                    carried_accounts.append(a["id"])
                else:
                    entered += 1
            elif st == "missing":
                missing.append(a["id"])
        has_data = (entered + carried) > 0
        row = {
            "period": p,
            "has_data": has_data,
            "total_satang": total if has_data else None,
            "group_totals_satang": {k: (v if group_counts[k] else None) for k, v in group_totals.items()},
            "entered_count": entered,
            "carried_count": carried,
            "carried_accounts": carried_accounts,
            "missing_accounts": missing,
            "prev_period": None,
            "change_satang": None,
        }
        if has_data and prev is not None:
            row["prev_period"] = prev["period"]
            row["change_satang"] = total - prev["total_satang"]
        summary.append(row)
        if has_data:
            prev = row
    latest = next((r["period"] for r in reversed(summary) if r["has_data"]), None)
    return {"summary": summary, "account_meta": meta, "latest_period": latest}


def get_state(conn) -> dict:
    return {
        "groups": list_groups(conn),
        "accounts": list_accounts(conn),
        "periods": list_periods(conn),
        "balances": list_balances(conn),
        **compute(conn),
    }


# --------------------------------------------------------------------------
# Export / backup / restore
# --------------------------------------------------------------------------

def export_wide_rows(conn) -> list[list[str]]:
    """Excel-like layout: accounts as rows, months as columns, plus totals."""
    st = get_state(conn)
    periods = st["periods"]
    by_key = {(b["account_id"], b["period"]): b for b in st["balances"]}
    gname = {g["code"]: g["name_th"] for g in st["groups"]}
    rows = [["กลุ่ม", "Account ID", "บัญชี", "สถานะ", *periods]]
    for g in st["groups"]:
        for a in [x for x in st["accounts"] if x["group_code"] == g["code"]]:
            cells = []
            for p in periods:
                e = by_key.get((a["id"], p))
                cells.append("" if e is None else format_amount(e["amount_satang"]) + (" (ยกมา)" if e["is_carried"] else ""))
            rows.append([f'{g["code"]} {gname[g["code"]]}', a["id"], a["name"],
                         "ใช้งาน" if a["is_active"] else "ปิดใช้งาน", *cells])
        rows.append([f'{g["code"]} {gname[g["code"]]}', "", f'รวมกลุ่ม {g["code"]}', "",
                     *[format_amount(s["group_totals_satang"][g["code"]]) for s in st["summary"]]])
    rows.append(["", "", "รวมสินทรัพย์", "", *[format_amount(s["total_satang"]) for s in st["summary"]]])
    rows.append(["", "", "เปลี่ยนแปลงจากเดือนก่อนหน้า", "", *[format_amount(s["change_satang"]) for s in st["summary"]]])
    rows.append(["", "", "เทียบกับเดือน", "", *[s["prev_period"] or "" for s in st["summary"]]])
    return rows


def export_long_rows(conn) -> list[list[str]]:
    accounts = {a["id"]: a for a in list_accounts(conn)}
    rows = [["period", "account_id", "account_name", "group_code", "amount", "is_carried", "note", "updated_at"]]
    for b in list_balances(conn):
        a = accounts[b["account_id"]]
        rows.append([b["period"], b["account_id"], a["name"], a["group_code"], format_amount(b["amount_satang"]),
                     str(b["is_carried"]), b["note"] or "", b["updated_at"]])
    return rows


def export_json(conn) -> dict:
    return {
        "format": "family-finance-dashboard/backup",
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now(),
        "groups": list_groups(conn),
        "accounts": [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id")],
        "periods": [dict(r) for r in conn.execute("SELECT * FROM periods ORDER BY period")],
        "balances": [dict(r) for r in conn.execute("SELECT * FROM balances ORDER BY period, account_id")],
        "audit_log": [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id")],
    }


def restore_json(conn, data) -> dict:
    """Replace all data with a JSON backup. Validates everything before touching the DB."""
    if not isinstance(data, dict) or data.get("format") != "family-finance-dashboard/backup":
        raise ValidationError("ไฟล์ไม่ใช่ไฟล์สำรองข้อมูลของโปรแกรมนี้")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValidationError(f"เวอร์ชันไฟล์สำรองไม่รองรับ: {data.get('schema_version')}")
    try:
        groups = [(g["code"], g["name_th"], g["name_en"], int(g["sort_order"]), g.get("description"))
                  for g in data["groups"]]
        accounts = []
        for a in data["accounts"]:
            if a["group_code"] not in {g[0] for g in groups}:
                raise ValidationError(f"บัญชี {a['id']} อ้างอิงกลุ่มที่ไม่มีอยู่")
            accounts.append((str(a["id"]), _clean_text(a["name"], "ชื่อบัญชี", True, 100), a["group_code"],
                             int(a["sort_order"]), a.get("note"), 1 if a["is_active"] else 0,
                             a["created_at"], a["updated_at"]))
        ids = {a[0] for a in accounts}
        periods = [(parse_period(p["period"]), p["created_at"]) for p in data["periods"]]
        pset = {p[0] for p in periods}
        balances = []
        for b in data["balances"]:
            if b["account_id"] not in ids or b["period"] not in pset:
                raise ValidationError("ยอดเงินอ้างอิงบัญชีหรือเดือนที่ไม่มีอยู่")
            if not isinstance(b["amount_satang"], int) or isinstance(b["amount_satang"], bool):
                raise ValidationError("ยอดเงินในไฟล์สำรองไม่ถูกต้อง")
            balances.append((b["account_id"], b["period"], b["amount_satang"], 1 if b["is_carried"] else 0,
                             b.get("note"), b["updated_at"]))
        audit = [(a["ts"], a["entity"], a["entity_id"], a["action"], a.get("old_value"), a.get("new_value"))
                 for a in data.get("audit_log", [])]
    except (KeyError, TypeError, ValueError) as e:
        raise ValidationError(f"ไฟล์สำรองข้อมูลไม่สมบูรณ์: {e}")
    with transaction(conn):
        for t in ("balances", "periods", "accounts", "audit_log", "account_groups"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany("INSERT INTO account_groups VALUES (?,?,?,?,?)", groups)
        conn.executemany("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?)", accounts)
        conn.executemany("INSERT INTO periods VALUES (?,?)", periods)
        conn.executemany("INSERT INTO balances VALUES (?,?,?,?,?,?)", balances)
        conn.executemany("INSERT INTO audit_log(ts, entity, entity_id, action, old_value, new_value)"
                         " VALUES (?,?,?,?,?,?)", audit)
        _audit(conn, "system", "restore", "restore", None,
               {"accounts": len(accounts), "periods": len(periods), "balances": len(balances)})
    return {"accounts": len(accounts), "periods": len(periods), "balances": len(balances)}


def backup_db(conn, backup_dir, reason="manual") -> str:
    """Consistent copy of the SQLite DB via the online backup API."""
    os.makedirs(backup_dir, exist_ok=True)
    safe = re.sub(r"[^a-z0-9_-]", "", reason.lower())[:30] or "manual"
    path = os.path.join(backup_dir, f"finance-{_dt.datetime.now():%Y%m%d-%H%M%S}-{safe}.sqlite")
    i = 1
    while os.path.exists(path):
        path = path.replace(".sqlite", f"-{i}.sqlite")
        i += 1
    dest = sqlite3.connect(path)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return path


def list_audit(conn, limit=200):
    return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),))]
