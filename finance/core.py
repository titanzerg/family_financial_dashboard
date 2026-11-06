"""Core data model and calculations for Module 1 — Monthly Asset Summary (spec v0.3).

Money is stored as integer satang (1 THB = 100 satang) to avoid float errors.
A missing balance (no row) is NOT zero; zero must be entered explicitly.

Each account has ONE balance per month, recorded after the month's salary has been
allocated (the salary arriving at the end of October is allocated, and the resulting
balances are recorded as November).

Every balance row records its `source`:
  'manual'    — typed/edited by the user
  'carried'   — copied automatically from the account's latest earlier balance
  'allocated' — filled automatically by the salary allocation (จัดสรรเงินเดือน) for a
                designated account (เงินเดือน / A-1 / A-2 / A-3 / LH)
Automatic values ('carried'/'allocated') follow later edits of the balance they were
derived from; manual values are never overwritten automatically.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation

SCHEMA_VERSION = 3

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

SOURCES = ("manual", "carried", "allocated")

# Designated accounts for the salary allocation (spec v0.3 §2-3).
# Identified by a role stored on the account (persistent ID), never by display name.
ROLES = {
    "SAL": {"label": "เงินเดือน", "desc": "บัญชีรับเงินเดือน — ต้นทางของการโอนทั้งหมด"},
    "A1": {"label": "A-1", "desc": "เงินเก็บค่าใช้จ่ายรายปี", "fixed_satang": 2_700_000},
    "A2": {"label": "A-2", "desc": "เงินใช้รายเดือนพี่สัก (จ่ายบัตรเครดิต)", "target_satang": 3_660_000},
    "A3": {"label": "A-3", "desc": "เงินใช้รายเดือนแวร์ (จ่ายบัตรเครดิต)", "target_satang": 2_400_000},
    "LH": {"label": "LH", "desc": "พักเงินค่างวดบ้าน และเงินสำรองฉุกเฉิน — รับเงินที่เหลือทั้งหมด"},
}
ROLE_ORDER = ("SAL", "A1", "A2", "A3", "LH")
TRANSFER_ORDER = ("A2", "A3", "A1", "LH")  # the order the user makes the transfers
LH_RESERVE_RANGE_SATANG = (20_000_000, 30_000_000)  # shown as information only, not a rule


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


def schema_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> None:
    version = schema_version(conn)
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
    if version < 2:
        # v1 stored one month-end balance per account/month. Those rows become 'end' balances.
        with transaction(conn):
            for stmt in _MIGRATE_V2:
                conn.execute(stmt)
            conn.execute("PRAGMA user_version = 2")
    if version < 3:
        # v2 split each month into ต้นเดือน/ปลายเดือน. v3 returns to one balance per month:
        # the v2 'end' rows (the original v1 meaning) are kept; v2 'begin' rows and income plans are
        # archived in legacy_v2_* tables (no constraints) rather than deleted.
        with transaction(conn):
            for stmt in _MIGRATE_V3:
                conn.execute(stmt)
            conn.execute("PRAGMA user_version = 3")
    # Future migrations: `if version < 4: ...` — test against a copy of real data first.


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

_BALANCES_V2 = """CREATE TABLE {name} (
        account_id TEXT NOT NULL REFERENCES accounts(id),
        period TEXT NOT NULL REFERENCES periods(period),
        kind TEXT NOT NULL CHECK (kind IN ('begin', 'end')),
        amount_satang INTEGER NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('manual', 'carried', 'transfer')),
        note TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (account_id, period, kind)
    )"""

_MIGRATE_V2 = [
    "ALTER TABLE account_groups ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE accounts ADD COLUMN role TEXT",
    "CREATE UNIQUE INDEX accounts_role ON accounts(role) WHERE role IS NOT NULL",
    _BALANCES_V2.format(name="balances_v2"),
    """INSERT INTO balances_v2(account_id, period, kind, amount_satang, source, note, updated_at)
       SELECT account_id, period, 'end', amount_satang,
              CASE WHEN is_carried THEN 'carried' ELSE 'manual' END, note, updated_at FROM balances""",
    "DROP TABLE balances",
    "ALTER TABLE balances_v2 RENAME TO balances",
    """CREATE TABLE month_plans (
        period TEXT PRIMARY KEY REFERENCES periods(period),
        income_satang INTEGER,
        status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'confirmed')),
        calc_json TEXT,
        confirmed_at TEXT,
        updated_at TEXT NOT NULL
    )""",
]


_MIGRATE_V3 = [
    """CREATE TABLE balances_v3 (
        account_id TEXT NOT NULL REFERENCES accounts(id),
        period TEXT NOT NULL REFERENCES periods(period),
        amount_satang INTEGER NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('manual', 'carried', 'allocated')),
        note TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (account_id, period)
    )""",
    """INSERT INTO balances_v3(account_id, period, amount_satang, source, note, updated_at)
       SELECT account_id, period, amount_satang, CASE WHEN source = 'carried' THEN 'carried' ELSE 'manual' END,
              note, updated_at FROM balances WHERE kind = 'end'""",
    "CREATE TABLE legacy_v2_balances AS SELECT * FROM balances",
    "DROP TABLE balances",
    "ALTER TABLE balances_v3 RENAME TO balances",
    "CREATE TABLE legacy_v2_month_plans AS SELECT * FROM month_plans",
    "DROP TABLE month_plans",
    """CREATE TABLE allocations (
        period TEXT PRIMARY KEY REFERENCES periods(period),
        inputs_json TEXT NOT NULL,
        calc_json TEXT NOT NULL,
        confirmed_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
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


def prev_month(period: str) -> str:
    """The immediately preceding calendar month."""
    y, m = int(period[:4]), int(period[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def next_month(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


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


def _ensure_period(conn, period):
    if not conn.execute("SELECT 1 FROM periods WHERE period = ?", (period,)).fetchone():
        conn.execute("INSERT INTO periods(period, created_at) VALUES (?,?)", (period, _now()))
        _audit(conn, "period", period, "create")


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------

def list_groups(conn):
    out = []
    for r in conn.execute("SELECT * FROM account_groups ORDER BY sort_order, code"):
        d = dict(r)
        d["is_active"] = bool(d["is_active"])
        out.append(d)
    return out


def get_group(conn, code):
    r = conn.execute("SELECT * FROM account_groups WHERE code = ?", (code,)).fetchone()
    if not r:
        raise NotFoundError(f"ไม่พบกลุ่มบัญชี: {code!r}")
    d = dict(r)
    d["is_active"] = bool(d["is_active"])
    return d


def create_group(conn, name, note=None) -> str:
    name = _clean_text(name, "ชื่อกลุ่ม", required=True, max_len=100)
    note = _clean_text(note, "หมายเหตุกลุ่ม")
    code = "G" + uuid.uuid4().hex[:8]
    with transaction(conn):
        sort = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM account_groups").fetchone()[0]
        conn.execute("INSERT INTO account_groups(code, name_th, name_en, sort_order, description, is_active)"
                     " VALUES (?,?,?,?,?,1)", (code, name, "", sort, note))
        _audit(conn, "group", code, "create", None, {"name_th": name, "description": note})
    return code


def update_group(conn, code, **changes) -> dict:
    """Rename / annotate / (de)activate a group. The group ID (code) never changes."""
    g = get_group(conn, code)
    allowed = {"name_th", "description", "is_active"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError(f"ไม่รองรับการแก้ไขฟิลด์: {', '.join(sorted(unknown))}")
    new = {}
    if "name_th" in changes:
        new["name_th"] = _clean_text(changes["name_th"], "ชื่อกลุ่ม", required=True, max_len=100)
    if "description" in changes:
        new["description"] = _clean_text(changes["description"], "หมายเหตุกลุ่ม")
    if "is_active" in changes:
        if not isinstance(changes["is_active"], bool):
            raise ValidationError("สถานะกลุ่มไม่ถูกต้อง")
        new["is_active"] = changes["is_active"]
    new = {k: v for k, v in new.items() if g[k] != v}
    if not new:
        return g
    with transaction(conn):
        if new.get("is_active") is False:
            n = conn.execute("SELECT COUNT(*) FROM accounts WHERE group_code = ? AND is_active = 1",
                             (code,)).fetchone()[0]
            if n:
                raise ValidationError(f"ปิดใช้งานกลุ่มไม่ได้ เพราะยังมีบัญชีที่ใช้งานอยู่ {n} บัญชี"
                                      " — ย้ายไปกลุ่มอื่นหรือปิดใช้งานบัญชีก่อน")
        db = {k: (int(v) if k == "is_active" else v) for k, v in new.items()}
        sets = ", ".join(f"{k} = ?" for k in db)
        conn.execute(f"UPDATE account_groups SET {sets} WHERE code = ?", (*db.values(), code))
        _audit(conn, "group", code, "update", {k: g[k] for k in new}, new)
    return get_group(conn, code)


def move_group(conn, code, direction) -> None:
    if direction not in ("up", "down"):
        raise ValidationError("ทิศทางไม่ถูกต้อง")
    get_group(conn, code)
    with transaction(conn):
        codes = [r[0] for r in conn.execute("SELECT code FROM account_groups ORDER BY sort_order, code")]
        i = codes.index(code)
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(codes):
            codes[i], codes[j] = codes[j], codes[i]
        for n, c in enumerate(codes, start=1):
            conn.execute("UPDATE account_groups SET sort_order = ? WHERE code = ?", (n, c))


def _check_group(conn, code):
    r = conn.execute("SELECT is_active FROM account_groups WHERE code = ?", (code,)).fetchone()
    if not r:
        raise ValidationError(f"ไม่พบกลุ่มบัญชี: {code!r}")
    if not r["is_active"]:
        raise ValidationError("กลุ่มนี้ปิดใช้งานอยู่ — เปิดใช้งานกลุ่มก่อน")


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def _account_dict(r):
    d = dict(r)
    d["is_active"] = bool(d["is_active"])
    return d


def list_accounts(conn):
    rows = conn.execute(
        "SELECT a.* FROM accounts a JOIN account_groups g ON g.code = a.group_code"
        " ORDER BY g.sort_order, g.code, a.sort_order, a.created_at").fetchall()
    return [_account_dict(r) for r in rows]


def get_account(conn, account_id):
    r = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if not r:
        raise NotFoundError("ไม่พบบัญชี")
    return _account_dict(r)


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
    """Rename / regroup / annotate / (de)activate / assign role. The Account ID never changes.

    Assigning a role that another account holds moves the role to this account.
    """
    acc = get_account(conn, account_id)
    allowed = {"name", "group_code", "note", "is_active", "role"}
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
    if "role" in changes:
        role = changes["role"] or None
        if role is not None and role not in ROLES:
            raise ValidationError("บทบาทบัญชีไม่ถูกต้อง")
        new["role"] = role
    new = {k: v for k, v in new.items() if (int(acc[k]) if k == "is_active" else acc[k]) != v}
    if not new:
        return acc
    active_after = new.get("is_active", int(acc["is_active"]))
    role_after = new.get("role", acc["role"])
    if role_after and not active_after:
        raise ValidationError(f"บัญชีนี้เป็นบัญชี {ROLES[role_after]['label']} ในการคำนวณเงินโอน"
                              " — ยกเลิกบทบาทก่อนปิดใช้งาน")
    with transaction(conn):
        if new.get("role"):
            holder = conn.execute("SELECT id FROM accounts WHERE role = ? AND id != ?",
                                  (new["role"], account_id)).fetchone()
            if holder:
                conn.execute("UPDATE accounts SET role = NULL, updated_at = ? WHERE id = ?", (_now(), holder["id"]))
                _audit(conn, "account", holder["id"], "update", {"role": new["role"]}, {"role": None})
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


def role_accounts(conn) -> dict:
    return {r["role"]: _account_dict(r) for r in conn.execute("SELECT * FROM accounts WHERE role IS NOT NULL")}


# --------------------------------------------------------------------------
# Periods & balances
# --------------------------------------------------------------------------

def list_periods(conn):
    return [r[0] for r in conn.execute("SELECT period FROM periods ORDER BY period")]


def add_period(conn, period, carry_groups=()) -> dict:
    """Create a month. carry_groups: groups whose latest balance is carried into the new month."""
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
        if conn.execute("SELECT 1 FROM allocations WHERE period = ?", (period,)).fetchone():
            raise ValidationError(f"ลบเดือน {period} ไม่ได้ เพราะมีการจัดสรรเงินเดือนของเดือนนี้แล้ว")
        conn.execute("DELETE FROM periods WHERE period = ?", (period,))
        _audit(conn, "period", period, "delete")


def _get_balance(conn, account_id, period):
    r = conn.execute("SELECT amount_satang, source, note FROM balances WHERE account_id = ? AND period = ?",
                     (account_id, period)).fetchone()
    return dict(r) if r else None


def _latest_before(conn, account_id, period):
    """The account's latest recorded balance strictly before `period`: (period, satang) or None."""
    r = conn.execute("SELECT period, amount_satang FROM balances WHERE account_id = ? AND period < ?"
                     " ORDER BY period DESC LIMIT 1", (account_id, period)).fetchone()
    return (r["period"], r["amount_satang"]) if r else None


def _write_balance(conn, account_id, period, satang, source, note, action_old=None):
    """Upsert/delete one balance row and audit it. Caller holds the transaction."""
    old = action_old if action_old is not None else _get_balance(conn, account_id, period)
    key = f"{account_id}@{period}"
    if satang is None:
        if old:
            conn.execute("DELETE FROM balances WHERE account_id = ? AND period = ?", (account_id, period))
            _audit(conn, "balance", key, "clear", old, None)
        return None
    new = {"amount_satang": satang, "source": source, "note": note}
    if old == new:
        return new
    conn.execute(
        "INSERT INTO balances(account_id, period, amount_satang, source, note, updated_at)"
        " VALUES (?,?,?,?,?,?) ON CONFLICT(account_id, period) DO UPDATE SET"
        " amount_satang = excluded.amount_satang, source = excluded.source, note = excluded.note,"
        " updated_at = excluded.updated_at",
        (account_id, period, satang, source, note, _now()))
    _audit(conn, "balance", key, "update" if old else "create", old, new)
    return new


def _auto_value(conn, account_id, period, alloc_calc):
    """Automatic value of an account in `period`: (satang|None, source, explanation dict).

    With a confirmed allocation for the month, designated accounts get:
      A-2 = target, A-3 = target, เงินเดือน = amount kept in the salary account,
      A-1 = latest earlier balance + 27,000, LH = latest earlier balance + LH transfer.
    Every other account carries its latest earlier balance.
    """
    base = _latest_before(conn, account_id, period)
    base_period, base_val = base if base else (None, None)
    role = None
    if alloc_calc:
        role = next((r for r, aid in alloc_calc["accounts"].items() if aid == account_id), None)
    if role is None:
        return base_val, "carried", {"base_period": base_period, "base_satang": base_val}
    t = alloc_calc["transfers"]
    if role in ("A2", "A3"):
        val = alloc_calc["targets"][role]
    elif role == "SAL":
        val = alloc_calc["inputs_satang"]["keep"]
    else:  # A1, LH: previous balance + transfer
        val = None if base_val is None or t.get(role) is None else base_val + t[role]
    return val, "allocated", {"role": role, "base_period": base_period, "base_satang": base_val,
                              "transfer_satang": t.get(role)}


def _propagate(conn, account_id, period) -> list:
    """Carry-forward rule (spec v0.3 §3.3): after the balance of `period` changes, the account's next
    recorded balance is recalculated if it was filled automatically ('carried'/'allocated'); this
    continues month by month. Manual values stop the chain and are never overwritten."""
    changed = []
    cur = period
    while True:
        nxt = conn.execute("SELECT period, amount_satang, source, note FROM balances"
                           " WHERE account_id = ? AND period > ? ORDER BY period LIMIT 1",
                           (account_id, cur)).fetchone()
        if not nxt or nxt["source"] == "manual":
            break
        alloc = _get_allocation(conn, nxt["period"])
        val, source, _ = _auto_value(conn, account_id, nxt["period"], alloc and alloc["calc"])
        if val is None or (val == nxt["amount_satang"] and source == nxt["source"]):
            break
        _write_balance(conn, account_id, nxt["period"], val, source, nxt["note"],
                       action_old={"amount_satang": nxt["amount_satang"], "source": nxt["source"],
                                   "note": nxt["note"]})
        changed.append({"account_id": account_id, "period": nxt["period"], "amount_satang": val})
        cur = nxt["period"]
    return changed


def set_balance(conn, account_id, period, amount, note=None, keep_note=False) -> dict:
    """Create/update/clear one balance typed by the user (source='manual').

    Returns {"value": row-or-None, "propagated": [automatic later values that were updated]}.
    """
    period = parse_period(period)
    get_account(conn, account_id)
    satang = parse_amount(amount)
    note = _clean_text(note, "หมายเหตุ")
    with transaction(conn):
        _ensure_period(conn, period)
        old = _get_balance(conn, account_id, period)
        if keep_note and old:
            note = old["note"]
        value = _write_balance(conn, account_id, period, satang, "manual", note)
        propagated = _propagate(conn, account_id, period)
    return {"value": value, "propagated": propagated}


def dependents(conn, account_id, period) -> list:
    """Automatic later values that would be recalculated if this balance changed (for warnings)."""
    out = []
    cur = period
    while True:
        nxt = conn.execute("SELECT period, source FROM balances WHERE account_id = ? AND period > ?"
                           " ORDER BY period LIMIT 1", (account_id, cur)).fetchone()
        if not nxt:
            break
        out.append({"period": nxt["period"], "source": nxt["source"]})
        if nxt["source"] == "manual":
            break
        cur = nxt["period"]
    return out


def set_balance_note(conn, account_id, period, note) -> None:
    period = parse_period(period)
    note = _clean_text(note, "หมายเหตุ")
    with transaction(conn):
        old = _get_balance(conn, account_id, period)
        if not old:
            raise ValidationError("ต้องบันทึกยอดก่อนจึงจะใส่หมายเหตุได้")
        if old["note"] == note:
            return
        conn.execute("UPDATE balances SET note = ?, updated_at = ? WHERE account_id = ? AND period = ?",
                     (note, _now(), account_id, period))
        _audit(conn, "balance", f"{account_id}@{period}", "note", {"note": old["note"]}, {"note": note})


def carry_forward(conn, period, account_ids=None) -> int:
    """Fill EMPTY cells of active accounts with their latest earlier balance (marked 'carried')."""
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
        if _get_balance(conn, aid, period):
            continue
        prev = _latest_before(conn, aid, period)
        if not prev:
            continue
        conn.execute("INSERT INTO balances(account_id, period, amount_satang, source, note, updated_at)"
                     " VALUES (?,?,?,'carried',NULL,?)", (aid, period, prev[1], _now()))
        _audit(conn, "balance", f"{aid}@{period}", "carry", None, {"amount_satang": prev[1], "from_period": prev[0]})
        n += 1
    return n


def list_balances(conn):
    out = []
    for r in conn.execute("SELECT account_id, period, amount_satang, source, note, updated_at FROM balances"
                          " ORDER BY period, account_id"):
        d = dict(r)
        d["is_carried"] = d["source"] == "carried"
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Salary allocation — จัดสรรเงินเดือน (spec v0.3 §3)
# --------------------------------------------------------------------------

ALLOC_INPUTS = {
    "salary": "ยอดบัญชีเงินเดือน หลังเงินเดือนเข้า",
    "a2": "ยอด A-2 หลังจ่ายบัตรเครดิต",
    "a3": "ยอด A-3 หลังจ่ายบัตรเครดิต",
    "keep": "เงินที่ค้างไว้ในบัญชีเงินเดือน",
}


def _get_allocation(conn, period):
    r = conn.execute("SELECT * FROM allocations WHERE period = ?", (period,)).fetchone()
    if not r:
        return None
    return {"period": r["period"], "inputs": json.loads(r["inputs_json"]), "calc": json.loads(r["calc_json"]),
            "confirmed_at": r["confirmed_at"], "updated_at": r["updated_at"]}


def _parse_alloc_inputs(inputs) -> dict:
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise ValidationError("ข้อมูลการจัดสรรไม่ถูกต้อง")
    unknown = set(inputs) - set(ALLOC_INPUTS)
    if unknown:
        raise ValidationError(f"ไม่รู้จักข้อมูล: {', '.join(sorted(unknown))}")
    out = {k: parse_amount(inputs.get(k)) for k in ALLOC_INPUTS}
    if out["keep"] is None:
        out["keep"] = 0
    return out


def compute_allocation(conn, period, inputs) -> dict:
    """Transfers for the salary allocation. Never clamps or alters results; flags problems instead.

      A-2 = 36,600 − A-2 balance after paying the credit card
      A-3 = 24,000 − A-3 balance after paying the credit card
      A-1 = 27,000
      LH  = salary-account balance − A-2 − A-3 − A-1 − amount kept in the salary account
    """
    period = parse_period(period)
    v = _parse_alloc_inputs(inputs)
    roles = role_accounts(conn)
    problems = []
    for r in ROLE_ORDER:
        if r not in roles:
            problems.append(f"ยังไม่ได้กำหนดบัญชี {ROLES[r]['label']} ({ROLES[r]['desc']}) — กำหนดได้ที่แท็บจัดการบัญชี")
    for k in ("salary", "a2", "a3"):
        if v[k] is None:
            problems.append(f"ยังไม่ได้กรอก{ALLOC_INPUTS[k]}")
    targets = {"A2": ROLES["A2"]["target_satang"], "A3": ROLES["A3"]["target_satang"]}
    t = {
        "A2": None if v["a2"] is None else targets["A2"] - v["a2"],
        "A3": None if v["a3"] is None else targets["A3"] - v["a3"],
        "A1": ROLES["A1"]["fixed_satang"],
    }
    t["LH"] = None if v["salary"] is None or None in (t["A2"], t["A3"]) else \
        v["salary"] - t["A2"] - t["A3"] - t["A1"] - v["keep"]
    fx = lambda s: f"{s // 100:,}"  # noqa: E731
    formulas = {
        "A2": f"{fx(targets['A2'])} − ยอด A-2 หลังจ่ายบัตร",
        "A3": f"{fx(targets['A3'])} − ยอด A-3 หลังจ่ายบัตร",
        "A1": f"{fx(ROLES['A1']['fixed_satang'])} ทุกเดือน",
        "LH": "ยอดบัญชีเงินเดือน − A-2 − A-3 − A-1" + (" − เงินที่ค้างไว้" if v["keep"] else ""),
    }
    items = []
    for r in TRANSFER_ORDER:
        a = roles.get(r)
        amt = t[r]
        items.append({"role": r, "label": ROLES[r]["label"], "account_id": a and a["id"],
                      "account_name": a and a["name"], "formula": formulas[r], "amount_satang": amt,
                      "negative": amt is not None and amt < 0})
    negatives = [i["label"] for i in items if i["negative"]]
    complete = not problems and all(i["amount_satang"] is not None for i in items)
    total_out = None if not complete else sum(i["amount_satang"] for i in items)
    return {
        "period": period, "items": items, "problems": problems, "negatives": negatives, "complete": complete,
        "inputs": {k: format_amount(x) for k, x in v.items()},
        "inputs_satang": v, "transfers": t, "targets": targets,
        "accounts": {r: a["id"] for r, a in roles.items()},
        "account_names": {r: a["name"] for r, a in roles.items()},
        "total_out_satang": total_out,
    }


def preview_allocation(conn, period, inputs) -> dict:
    """Transfers plus the proposed balance of every active account for the month (spec v0.3 §3.3)."""
    period = parse_period(period)
    calc = compute_allocation(conn, period, inputs)
    rows = []
    for a in list_accounts(conn):
        if not a["is_active"]:
            continue
        existing = _get_balance(conn, a["id"], period)
        default, source, why = _auto_value(conn, a["id"], period, calc)
        keep_manual = bool(existing and existing["source"] == "manual" and existing["amount_satang"] != default)
        proposed = existing["amount_satang"] if keep_manual else default
        rows.append({"account_id": a["id"], "account_name": a["name"], "group_code": a["group_code"],
                     "role": why.get("role"), "default_satang": default, "default_source": source, "why": why,
                     "existing": existing, "proposed_satang": proposed, "keeps_manual": keep_manual})
    stored = _get_allocation(conn, period)
    return {"calc": calc, "rows": rows, "confirmed": stored is not None}


def confirm_allocation(conn, period, inputs, balances=None, accept_negative=False) -> dict:
    """Store the allocation (inputs + transfers) and write the reviewed balances of the month.

    balances: {account_id: amount|''|None} — the user's reviewed values; accounts not listed use the
    proposed value. A value equal to the automatic value keeps its automatic source; anything else
    is stored as 'manual'.
    """
    period = parse_period(period)
    balances = balances or {}
    if not isinstance(balances, dict):
        raise ValidationError("ข้อมูลยอดเงินไม่ถูกต้อง")
    parsed = {aid: parse_amount(v) for aid, v in balances.items()}
    with transaction(conn):
        _ensure_period(conn, period)
        pv = preview_allocation(conn, period, inputs)
        calc = pv["calc"]
        if not calc["complete"]:
            raise ValidationError("ยังคำนวณยอดโอนไม่ครบ: " + " · ".join(calc["problems"]))
        if calc["negatives"] and not accept_negative:
            raise ValidationError(f"ยอดโอนติดลบ ({', '.join(calc['negatives'])}) — ตรวจสอบตัวเลขแล้วยืนยันอีกครั้ง")
        known = {r["account_id"] for r in pv["rows"]}
        if set(parsed) - known:
            raise ValidationError("มีบัญชีที่ไม่ได้ใช้งานหรือไม่มีอยู่ในรายการ")
        stored = {k: calc[k] for k in ("inputs_satang", "transfers", "targets", "accounts", "account_names",
                                       "total_out_satang", "items")}
        stored["accepted_negative"] = bool(calc["negatives"])
        old = _get_allocation(conn, period)
        now = _now()
        conn.execute("INSERT INTO allocations(period, inputs_json, calc_json, confirmed_at, updated_at)"
                     " VALUES (?,?,?,?,?) ON CONFLICT(period) DO UPDATE SET inputs_json = excluded.inputs_json,"
                     " calc_json = excluded.calc_json, confirmed_at = excluded.confirmed_at,"
                     " updated_at = excluded.updated_at",
                     (period, json.dumps(calc["inputs"], ensure_ascii=False),
                      json.dumps(stored, ensure_ascii=False), now, now))
        _audit(conn, "allocation", period, "confirm",
               {"transfers": old["calc"]["transfers"]} if old else None,
               {"inputs": calc["inputs_satang"], "transfers": calc["transfers"]})
        written, propagated = [], []
        for r in pv["rows"]:
            aid = r["account_id"]
            value = parsed[aid] if aid in parsed else r["proposed_satang"]
            source = None if value is None else (r["default_source"] if value == r["default_satang"] else "manual")
            note = r["existing"]["note"] if r["existing"] else None
            res = _write_balance(conn, aid, period, value, source, note)
            written.append({"account_id": aid, "amount_satang": value, "source": source if res else None})
            propagated += _propagate(conn, aid, period)
    return {"period": period, "written": written, "propagated": propagated}


def delete_allocation(conn, period) -> None:
    """Remove the stored allocation of a month. Balances stay; automatic ones become manual."""
    period = parse_period(period)
    with transaction(conn):
        old = _get_allocation(conn, period)
        if not old:
            raise NotFoundError("เดือนนี้ยังไม่มีการจัดสรรเงินเดือน")
        conn.execute("UPDATE balances SET source = 'manual', updated_at = ? WHERE period = ? AND source = 'allocated'",
                     (_now(), period))
        conn.execute("DELETE FROM allocations WHERE period = ?", (period,))
        _audit(conn, "allocation", period, "delete", {"transfers": old["calc"]["transfers"]}, None)


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------

def cell_status(account, period, entry, first, last) -> str:
    """entered | carried | allocated | missing | not_yet | closed"""
    if entry is not None:
        return {"carried": "carried", "allocated": "allocated"}.get(entry["source"], "entered")
    if first is None or period < first:
        return "not_yet"
    if account["is_active"] or period < last:
        return "missing"
    return "closed"


def compute(conn) -> dict:
    """Totals, month-to-month changes and per-account metadata. Pure read.

    Monthly change = this month's total assets − previous recorded month's total assets (as in v0.1).
    """
    groups = list_groups(conn)
    accounts = list_accounts(conn)
    periods = list_periods(conn)
    balances = list_balances(conn)
    by_key = {(b["account_id"], b["period"]): b for b in balances}

    meta = {}
    for a in accounts:
        mine = [b for b in balances if b["account_id"] == a["id"]]
        verified = [b["period"] for b in mine if b["source"] != "carried"]
        meta[a["id"]] = {
            "first_period": mine[0]["period"] if mine else None,
            "last_period": mine[-1]["period"] if mine else None,
            "last_verified_period": verified[-1] if verified else None,
        }

    allocs = {p: _get_allocation(conn, p) for p in periods}
    summary = []
    prev = None
    for p in periods:
        total = 0
        group_totals = {g["code"]: 0 for g in groups}
        group_counts = {g["code"]: 0 for g in groups}
        entered = carried = auto = 0
        missing, carried_accounts = [], []
        for a in accounts:
            e = by_key.get((a["id"], p))
            m = meta[a["id"]]
            st = cell_status(a, p, e, m["first_period"], m["last_period"])
            if e is not None:
                total += e["amount_satang"]
                group_totals[a["group_code"]] += e["amount_satang"]
                group_counts[a["group_code"]] += 1
                if e["source"] == "carried":
                    carried += 1
                    carried_accounts.append(a["id"])
                elif e["source"] == "allocated":
                    auto += 1
                else:
                    entered += 1
            elif st == "missing":
                missing.append(a["id"])
        has_data = (entered + carried + auto) > 0
        row = {
            "period": p,
            "has_data": has_data,
            "total_satang": total if has_data else None,
            "group_totals_satang": {k: (v if group_counts[k] else None) for k, v in group_totals.items()},
            "entered_count": entered,
            "carried_count": carried,
            "allocated_count": auto,
            "carried_accounts": carried_accounts,
            "missing_accounts": missing,
            "prev_period": None,
            "change_satang": None,
            "allocation": allocs[p],
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
        "roles": {k: {**v} for k, v in ROLES.items()},
        "role_order": list(ROLE_ORDER),
        "alloc_inputs": ALLOC_INPUTS,
        "lh_reserve_range_satang": list(LH_RESERVE_RANGE_SATANG),
        **compute(conn),
    }


# --------------------------------------------------------------------------
# Export / backup / restore
# --------------------------------------------------------------------------

SOURCE_TH = {"manual": "", "carried": " (ยกมา)", "allocated": " (จัดสรร)"}


def export_wide_rows(conn) -> list[list[str]]:
    """Excel-like layout: accounts as rows, one column per month, plus totals and allocations."""
    st = get_state(conn)
    periods = st["periods"]
    by_key = {(b["account_id"], b["period"]): b for b in st["balances"]}
    summ = {s["period"]: s for s in st["summary"]}
    rows = [["กลุ่ม", "Account ID", "บัญชี", "สถานะ", *periods]]
    for g in st["groups"]:
        for a in [x for x in st["accounts"] if x["group_code"] == g["code"]]:
            cells = []
            for p in periods:
                e = by_key.get((a["id"], p))
                cells.append("" if e is None else format_amount(e["amount_satang"]) + SOURCE_TH[e["source"]])
            rows.append([g["name_th"], a["id"], a["name"], "ใช้งาน" if a["is_active"] else "ปิดใช้งาน", *cells])
        rows.append([g["name_th"], "", f'รวมกลุ่ม {g["name_th"]}', "",
                     *[format_amount(summ[p]["group_totals_satang"][g["code"]]) for p in periods]])
    rows.append(["", "", "รวมสินทรัพย์", "", *[format_amount(summ[p]["total_satang"]) for p in periods]])
    rows.append(["", "", "เปลี่ยนแปลงจากเดือนก่อนหน้า", "", *[format_amount(summ[p]["change_satang"]) for p in periods]])
    rows.append(["", "", "เทียบกับเดือน", "", *[summ[p]["prev_period"] or "" for p in periods]])

    def alloc_cell(p, fn):
        a = summ[p]["allocation"]
        return format_amount(fn(a["calc"])) if a else ""
    rows.append(["", "", "จัดสรร: ยอดบัญชีเงินเดือนหลังเงินเดือนเข้า", "",
                 *[alloc_cell(p, lambda c: c["inputs_satang"]["salary"]) for p in periods]])
    for r in TRANSFER_ORDER:
        rows.append(["", "", f"จัดสรร: โอนไป {ROLES[r]['label']}", "",
                     *[alloc_cell(p, lambda c, r=r: c["transfers"][r]) for p in periods]])
    return rows


def export_long_rows(conn) -> list[list[str]]:
    accounts = {a["id"]: a for a in list_accounts(conn)}
    rows = [["period", "account_id", "account_name", "group_code", "amount", "source", "note", "updated_at"]]
    for b in list_balances(conn):
        a = accounts[b["account_id"]]
        rows.append([b["period"], b["account_id"], a["name"], a["group_code"],
                     format_amount(b["amount_satang"]), b["source"], b["note"] or "", b["updated_at"]])
    return rows


def export_json(conn) -> dict:
    return {
        "format": "family-finance-dashboard/backup",
        "schema_version": SCHEMA_VERSION,
        "exported_at": _now(),
        "groups": [dict(r) for r in conn.execute("SELECT * FROM account_groups ORDER BY sort_order, code")],
        "accounts": [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY id")],
        "periods": [dict(r) for r in conn.execute("SELECT * FROM periods ORDER BY period")],
        "balances": [dict(r) for r in conn.execute("SELECT * FROM balances ORDER BY period, account_id")],
        "allocations": [dict(r) for r in conn.execute("SELECT * FROM allocations ORDER BY period")],
        "audit_log": [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id")],
    }


def restore_json(conn, data) -> dict:
    """Replace all data with a JSON backup (schema v1, v2 or v3). Validates everything before touching the DB.

    v2 backups: ปลายเดือน balances are restored; ต้นเดือน balances and income plans are not (spec v0.3)."""
    if not isinstance(data, dict) or data.get("format") != "family-finance-dashboard/backup":
        raise ValidationError("ไฟล์ไม่ใช่ไฟล์สำรองข้อมูลของโปรแกรมนี้")
    ver = data.get("schema_version")
    if ver not in (1, 2, 3):
        raise ValidationError(f"เวอร์ชันไฟล์สำรองไม่รองรับ: {ver}")
    try:
        groups = [(g["code"], g["name_th"], g.get("name_en") or "", int(g["sort_order"]), g.get("description"),
                   1 if g.get("is_active", 1) else 0) for g in data["groups"]]
        gcodes = {g[0] for g in groups}
        accounts, roles = [], set()
        for a in data["accounts"]:
            if a["group_code"] not in gcodes:
                raise ValidationError(f"บัญชี {a['id']} อ้างอิงกลุ่มที่ไม่มีอยู่")
            role = a.get("role") or None
            if role is not None and (role not in ROLES or role in roles):
                raise ValidationError("บทบาทบัญชีในไฟล์สำรองไม่ถูกต้อง")
            roles.add(role)
            accounts.append((str(a["id"]), _clean_text(a["name"], "ชื่อบัญชี", True, 100), a["group_code"],
                             int(a["sort_order"]), a.get("note"), 1 if a["is_active"] else 0,
                             a["created_at"], a["updated_at"], role))
        ids = {a[0] for a in accounts}
        periods = [(parse_period(p["period"]), p["created_at"]) for p in data["periods"]]
        pset = {p[0] for p in periods}
        balances = []
        for b in data["balances"]:
            if b["account_id"] not in ids or b["period"] not in pset:
                raise ValidationError("ยอดเงินอ้างอิงบัญชีหรือเดือนที่ไม่มีอยู่")
            if not isinstance(b["amount_satang"], int) or isinstance(b["amount_satang"], bool):
                raise ValidationError("ยอดเงินในไฟล์สำรองไม่ถูกต้อง")
            if ver == 1:
                source = "carried" if b["is_carried"] else "manual"
            elif ver == 2:
                if b["kind"] != "end":
                    continue
                source = "carried" if b["source"] == "carried" else "manual"
            else:
                source = b["source"]
                if source not in SOURCES:
                    raise ValidationError("ที่มาของยอดในไฟล์สำรองไม่ถูกต้อง")
            balances.append((b["account_id"], b["period"], b["amount_satang"], source, b.get("note"), b["updated_at"]))
        allocs = []
        for m in data.get("allocations", []) if ver == 3 else []:
            if m["period"] not in pset:
                raise ValidationError("ข้อมูลการจัดสรรในไฟล์สำรองไม่ถูกต้อง")
            json.loads(m["inputs_json"])
            json.loads(m["calc_json"])
            allocs.append((m["period"], m["inputs_json"], m["calc_json"], m["confirmed_at"], m["updated_at"]))
        audit = [(a["ts"], a["entity"], a["entity_id"], a["action"], a.get("old_value"), a.get("new_value"))
                 for a in data.get("audit_log", [])]
    except (KeyError, TypeError, ValueError) as e:
        raise ValidationError(f"ไฟล์สำรองข้อมูลไม่สมบูรณ์: {e}")
    with transaction(conn):
        for t in ("balances", "allocations", "periods", "accounts", "audit_log", "account_groups"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany("INSERT INTO account_groups(code, name_th, name_en, sort_order, description, is_active)"
                         " VALUES (?,?,?,?,?,?)", groups)
        conn.executemany("INSERT INTO accounts(id, name, group_code, sort_order, note, is_active, created_at,"
                         " updated_at, role) VALUES (?,?,?,?,?,?,?,?,?)", accounts)
        conn.executemany("INSERT INTO periods VALUES (?,?)", periods)
        conn.executemany("INSERT INTO balances(account_id, period, amount_satang, source, note, updated_at)"
                         " VALUES (?,?,?,?,?,?)", balances)
        conn.executemany("INSERT INTO allocations(period, inputs_json, calc_json, confirmed_at, updated_at)"
                         " VALUES (?,?,?,?,?)", allocs)
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


def backup_file_before_migration(db_path, backup_dir) -> str | None:
    """Copy an existing DB file before it is upgraded to a newer schema."""
    if db_path == ":memory:" or not os.path.exists(db_path):
        return None
    src = sqlite3.connect(db_path)
    try:
        if schema_version(src) >= SCHEMA_VERSION:
            return None
        return backup_db(src, backup_dir, f"before-migrate-v{SCHEMA_VERSION}")
    finally:
        src.close()


def list_audit(conn, limit=200):
    return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),))]
