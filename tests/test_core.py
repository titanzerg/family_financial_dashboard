import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finance import core  # noqa: E402
from finance.core import ValidationError  # noqa: E402


def summary_for(conn, period):
    return next(s for s in core.compute(conn)["summary"] if s["period"] == period)


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = core.connect(":memory:")
        self.a = core.create_account(self.conn, "สำรองค่าใช้จ่ายรายปี", "A")
        self.b = core.create_account(self.conn, "ออมทรัพย์", "B")
        self.c = core.create_account(self.conn, "หุ้น", "C")
        self.d = core.create_account(self.conn, "LH", "D")

    def tearDown(self):
        self.conn.close()


class TestParsing(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(core.parse_amount("1,234.56"), 123456)
        self.assertEqual(core.parse_amount("-500"), -50000)
        self.assertEqual(core.parse_amount("0"), 0)
        self.assertEqual(core.parse_amount(12.3), 1230)
        self.assertIsNone(core.parse_amount(""))
        self.assertIsNone(core.parse_amount(None))
        for bad in ("abc", "1.234", "nan", "inf", True, [1]):
            with self.assertRaises(ValidationError, msg=bad):
                core.parse_amount(bad)

    def test_periods(self):
        self.assertEqual(core.parse_period("2026-01"), "2026-01")
        for bad in ("2026-13", "2026-00", "26-01", "2026/01", "2569-01x", 202601):
            with self.assertRaises(ValidationError, msg=bad):
                core.parse_period(bad)

    def test_format(self):
        self.assertEqual(core.format_amount(123456), "1234.56")
        self.assertEqual(core.format_amount(-5), "-0.05")
        self.assertEqual(core.format_amount(None), "")


class TestCalculations(Base):
    def test_total_and_change(self):
        for acc, amt in ((self.a, "1000"), (self.b, "2000"), (self.c, "3000"), (self.d, "4000")):
            core.set_balance(self.conn, acc, "2026-01", amt)
        for acc, amt in ((self.a, "1500"), (self.b, "2000"), (self.c, "3000"), (self.d, "3000")):
            core.set_balance(self.conn, acc, "2026-02", amt)
        jan, feb = summary_for(self.conn, "2026-01"), summary_for(self.conn, "2026-02")
        self.assertEqual(jan["total_satang"], 1000000)
        self.assertIsNone(jan["change_satang"])  # first month: no change
        self.assertEqual(feb["total_satang"], 950000)
        self.assertEqual(feb["change_satang"], -50000)
        self.assertEqual(feb["prev_period"], "2026-01")
        self.assertEqual(feb["group_totals_satang"]["D"], 300000)

    def test_edit_older_month_recalculates_following_change(self):
        core.set_balance(self.conn, self.b, "2026-01", "100")
        core.set_balance(self.conn, self.b, "2026-02", "150")
        core.set_balance(self.conn, self.b, "2026-03", "170")
        self.assertEqual(summary_for(self.conn, "2026-02")["change_satang"], 5000)
        core.set_balance(self.conn, self.b, "2026-02", "120")
        self.assertEqual(summary_for(self.conn, "2026-02")["change_satang"], 2000)
        self.assertEqual(summary_for(self.conn, "2026-03")["change_satang"], 5000)
        self.assertEqual(summary_for(self.conn, "2026-01")["total_satang"], 10000)  # untouched

    def test_missing_is_not_zero(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        core.set_balance(self.conn, self.b, "2026-01", "0")
        core.set_balance(self.conn, self.a, "2026-02", "100")
        feb = summary_for(self.conn, "2026-02")
        self.assertIn(self.b, feb["missing_accounts"])  # explicit 0 last month, nothing this month
        self.assertNotIn(self.c, feb["missing_accounts"])  # never used -> "not yet", not missing
        jan = summary_for(self.conn, "2026-01")
        self.assertEqual(jan["entered_count"], 2)

    def test_clear_balance(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        core.set_balance(self.conn, self.a, "2026-01", "")
        self.assertEqual(core.list_balances(self.conn), [])
        self.assertIsNone(summary_for(self.conn, "2026-01")["total_satang"])

    def test_empty_month_is_skipped_for_comparison(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        core.add_period(self.conn, "2026-02")
        core.set_balance(self.conn, self.a, "2026-03", "130")
        self.assertIsNone(summary_for(self.conn, "2026-02")["change_satang"])
        mar = summary_for(self.conn, "2026-03")
        self.assertEqual(mar["prev_period"], "2026-01")
        self.assertEqual(mar["change_satang"], 3000)


class TestCarryForward(Base):
    def test_carry_marks_and_does_not_overwrite(self):
        core.set_balance(self.conn, self.c, "2026-01", "5000")
        core.set_balance(self.conn, self.b, "2026-01", "100")
        res = core.add_period(self.conn, "2026-02", carry_groups=["C"])
        self.assertEqual(res["carried"], 1)
        feb = summary_for(self.conn, "2026-02")
        self.assertEqual(feb["carried_accounts"], [self.c])
        self.assertIn(self.b, feb["missing_accounts"])
        meta = core.compute(self.conn)["account_meta"][self.c]
        self.assertEqual(meta["last_verified_period"], "2026-01")
        # entering a value confirms it
        core.set_balance(self.conn, self.c, "2026-02", "5200")
        self.assertEqual(core.compute(self.conn)["account_meta"][self.c]["last_verified_period"], "2026-02")
        # carrying again does not overwrite existing values
        self.assertEqual(core.carry_forward(self.conn, "2026-02"), 1)  # only b gets filled
        self.assertEqual(summary_for(self.conn, "2026-02")["total_satang"], 530000)

    def test_inactive_not_carried(self):
        core.set_balance(self.conn, self.c, "2026-01", "5000")
        core.update_account(self.conn, self.c, is_active=False)
        self.assertEqual(core.add_period(self.conn, "2026-02", carry_groups=["C"])["carried"], 0)


class TestAccounts(Base):
    def test_rename_preserves_id_and_history(self):
        core.set_balance(self.conn, self.b, "2026-01", "100")
        core.update_account(self.conn, self.b, name="ออมทรัพย์ KBank")
        accs = core.list_accounts(self.conn)
        self.assertEqual(len(accs), 4)
        renamed = next(a for a in accs if a["id"] == self.b)
        self.assertEqual(renamed["name"], "ออมทรัพย์ KBank")
        self.assertEqual(core.list_balances(self.conn)[0]["account_id"], self.b)
        self.assertEqual(summary_for(self.conn, "2026-01")["total_satang"], 10000)

    def test_move_group_preserves_history(self):
        core.set_balance(self.conn, self.b, "2026-01", "100")
        core.update_account(self.conn, self.b, group_code="D")
        s = summary_for(self.conn, "2026-01")
        self.assertEqual(s["group_totals_satang"]["D"], 10000)
        self.assertIsNone(s["group_totals_satang"]["B"])

    def test_deactivate_preserves_history(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        core.set_balance(self.conn, self.b, "2026-01", "200")
        core.set_balance(self.conn, self.a, "2026-02", "100")
        core.update_account(self.conn, self.b, is_active=False)
        self.assertEqual(summary_for(self.conn, "2026-01")["total_satang"], 30000)
        self.assertNotIn(self.b, summary_for(self.conn, "2026-02")["missing_accounts"])
        self.assertEqual(len(core.list_balances(self.conn)), 3)

    def test_ordering(self):
        e = core.create_account(self.conn, "ออม 2", "B")
        core.move_account(self.conn, e, "up")
        names = [a["name"] for a in core.list_accounts(self.conn) if a["group_code"] == "B"]
        self.assertEqual(names, ["ออม 2", "ออมทรัพย์"])
        core.move_account(self.conn, e, "up")  # already first: no-op
        self.assertEqual(names, [a["name"] for a in core.list_accounts(self.conn) if a["group_code"] == "B"])

    def test_validation(self):
        with self.assertRaises(ValidationError):
            core.create_account(self.conn, "  ", "A")
        with self.assertRaises(ValidationError):
            core.create_account(self.conn, "x", "Z")
        with self.assertRaises(ValidationError):
            core.update_account(self.conn, self.a, id="hack")
        with self.assertRaises(ValidationError):
            core.set_balance(self.conn, "acc_nope", "2026-01", "1")


class TestPeriods(Base):
    def test_cannot_delete_month_with_data(self):
        core.set_balance(self.conn, self.a, "2026-01", "1")
        with self.assertRaises(ValidationError):
            core.delete_period(self.conn, "2026-01")
        core.add_period(self.conn, "2026-02")
        core.delete_period(self.conn, "2026-02")
        self.assertEqual(core.list_periods(self.conn), ["2026-01"])

    def test_duplicate_month(self):
        core.add_period(self.conn, "2026-01")
        with self.assertRaises(ValidationError):
            core.add_period(self.conn, "2026-01")


class TestAuditBackupRestore(Base):
    def test_audit_records_old_value(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        core.set_balance(self.conn, self.a, "2026-01", "150")
        last = core.list_audit(self.conn, 1)[0]
        self.assertEqual(last["action"], "update")
        self.assertIn("10000", last["old_value"])

    def test_json_roundtrip(self):
        core.set_balance(self.conn, self.a, "2026-01", "100.25", note="ทดสอบ")
        core.add_period(self.conn, "2026-02", carry_groups=["A"])
        data = core.export_json(self.conn)
        other = core.connect(":memory:")
        core.restore_json(other, data)
        self.assertEqual(core.list_balances(other), core.list_balances(self.conn))
        self.assertEqual(core.list_accounts(other), core.list_accounts(self.conn))
        other.close()

    def test_restore_rejects_bad_file_without_changes(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        data = core.export_json(self.conn)
        data["balances"][0]["amount_satang"] = "lots"
        with self.assertRaises(ValidationError):
            core.restore_json(self.conn, data)
        self.assertEqual(len(core.list_balances(self.conn)), 1)

    def test_backup_file(self):
        with tempfile.TemporaryDirectory() as d:
            conn = core.connect(os.path.join(d, "f.sqlite"))
            core.create_account(conn, "x", "A")
            path = core.backup_db(conn, os.path.join(d, "bk"), "test")
            copy = sqlite3.connect(path)
            self.assertEqual(copy.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
            copy.close()
            conn.close()

    def test_exports(self):
        core.set_balance(self.conn, self.a, "2026-01", "100")
        core.set_balance(self.conn, self.a, "2026-02", "90")
        wide = core.export_wide_rows(self.conn)
        self.assertEqual(wide[0][-2:], ["2026-01", "2026-02"])
        change_row = next(r for r in wide if r[2].startswith("เปลี่ยนแปลงจากเดือนก่อนหน้า"))
        self.assertEqual(change_row[-2:], ["", "-10.00"])
        self.assertEqual(len(core.export_long_rows(self.conn)), 3)


class TestGroups(Base):
    def test_add_rename_reorder_preserves_history(self):
        core.set_balance(self.conn, self.b, "2026-01", "100")
        core.update_group(self.conn, "B", name_th="เงินฝาก (ชื่อใหม่)", description="โน้ต")
        self.assertEqual(core.get_group(self.conn, "B")["name_th"], "เงินฝาก (ชื่อใหม่)")
        self.assertEqual(summary_for(self.conn, "2026-01")["group_totals_satang"]["B"], 10000)
        g = core.create_group(self.conn, "กลุ่มใหม่")
        core.move_group(self.conn, g, "up")
        codes = [x["code"] for x in core.list_groups(self.conn)]
        self.assertEqual(codes, ["A", "B", "C", g, "D"])
        e = core.create_account(self.conn, "บัญชีใหม่", g)
        self.assertEqual(core.get_account(self.conn, e)["group_code"], g)

    def test_deactivate_requires_no_active_accounts(self):
        core.set_balance(self.conn, self.b, "2026-01", "100")
        with self.assertRaises(ValidationError):
            core.update_group(self.conn, "B", is_active=False)
        core.update_account(self.conn, self.b, is_active=False)
        core.update_group(self.conn, "B", is_active=False)
        self.assertEqual(summary_for(self.conn, "2026-01")["group_totals_satang"]["B"], 10000)
        with self.assertRaises(ValidationError):
            core.create_account(self.conn, "x", "B")


class AllocBase(unittest.TestCase):
    """Accounts as in the user's setup; roles assigned by ID."""

    def setUp(self):
        c = self.conn = core.connect(":memory:")
        self.sal = core.create_account(c, "กสิกร พี่สัก เงินเดือน", "A")
        self.a1 = core.create_account(c, "กรุงเทพ พี่สัก", "A")
        self.a2 = core.create_account(c, "กสิกร พี่สัก ไว้ใช้", "A")
        self.a3 = core.create_account(c, "กสิกร แวร์ ไว้ใช้", "A")
        self.save = core.create_account(c, "เงินเก็บ", "B")
        self.gold = core.create_account(c, "gold now", "C")
        self.lh = core.create_account(c, "LH", "D")
        for aid, role in ((self.sal, "SAL"), (self.a1, "A1"), (self.a2, "A2"), (self.a3, "A3"), (self.lh, "LH")):
            core.update_account(c, aid, role=role)
        # October (after the end-of-September allocation), as in the v0.1 data
        for aid, amt in ((self.sal, "1000"), (self.a1, "147000"), (self.a2, "36600"), (self.a3, "24000"),
                         (self.save, "114000"), (self.gold, "212500"), (self.lh, "317000")):
            core.set_balance(c, aid, "2026-10", amt)
        self.inputs = {"salary": "135000", "a2": "5600", "a3": "4000"}

    def tearDown(self):
        self.conn.close()

    def bal(self, aid, period):
        return core._get_balance(self.conn, aid, period)


class TestAllocationFormulas(AllocBase):
    def test_formulas(self):
        c = core.compute_allocation(self.conn, "2026-11", self.inputs)
        amounts = {i["role"]: i["amount_satang"] for i in c["items"]}
        self.assertEqual([i["role"] for i in c["items"]], ["A2", "A3", "A1", "LH"])
        self.assertEqual(amounts, {"A2": 3100000, "A3": 2000000, "A1": 2700000, "LH": 135000_00 - 7800000})
        self.assertTrue(c["complete"])
        self.assertEqual(c["total_out_satang"], 13500000)  # everything leaves the salary account

    def test_keep_in_salary_account_reduces_lh(self):
        c = core.compute_allocation(self.conn, "2026-11", {**self.inputs, "keep": "1000"})
        self.assertEqual(c["transfers"]["LH"], 5700000 - 100000)

    def test_negative_not_clamped(self):
        c = core.compute_allocation(self.conn, "2026-11", {"salary": "50000", "a2": "40000", "a3": "0"})
        self.assertEqual(c["transfers"]["A2"], -340000)
        self.assertEqual(c["transfers"]["LH"], 5000000 + 340000 - 2400000 - 2700000)
        self.assertEqual(c["negatives"], ["A-2"])
        with self.assertRaises(ValidationError):
            core.confirm_allocation(self.conn, "2026-11", {"salary": "50000", "a2": "40000", "a3": "0"})
        core.confirm_allocation(self.conn, "2026-11", {"salary": "50000", "a2": "40000", "a3": "0"},
                                accept_negative=True)

    def test_missing_inputs_block(self):
        c = core.compute_allocation(self.conn, "2026-11", {"salary": "135000"})
        self.assertFalse(c["complete"])
        self.assertIsNone(c["transfers"]["LH"])
        with self.assertRaises(ValidationError):
            core.confirm_allocation(self.conn, "2026-11", {"salary": "135000"})

    def test_role_unassigned_blocks(self):
        core.update_account(self.conn, self.sal, role=None)
        c = core.compute_allocation(self.conn, "2026-11", self.inputs)
        self.assertFalse(c["complete"])

    def test_uses_role_not_name(self):
        core.update_account(self.conn, self.a2, name="ชื่อใหม่")
        c = core.compute_allocation(self.conn, "2026-11", self.inputs)
        self.assertEqual(c["accounts"]["A2"], self.a2)


class TestAllocationBalances(AllocBase):
    def test_confirm_fills_month(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        exp = {self.a2: (3660000, "allocated"), self.a3: (2400000, "allocated"), self.sal: (0, "allocated"),
               self.a1: (14700000 + 2700000, "allocated"), self.lh: (31700000 + 5700000, "allocated"),
               self.save: (11400000, "carried"), self.gold: (21250000, "carried")}
        for aid, (amt, src) in exp.items():
            b = self.bal(aid, "2026-11")
            self.assertEqual((b["amount_satang"], b["source"]), (amt, src), aid)
        s = next(x for x in core.compute(self.conn)["summary"] if x["period"] == "2026-11")
        self.assertEqual(s["allocation"]["calc"]["transfers"]["LH"], 5700000)
        # total change = salary that came in − money spent from A-2/A-3 before the allocation
        self.assertEqual(s["change_satang"], 13500000 - 100000 - (3660000 - 560000) - (2400000 - 400000))

    def test_reviewed_values_become_manual(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs, balances={self.lh: "300000", self.gold: ""})
        self.assertEqual(self.bal(self.lh, "2026-11"), {"amount_satang": 30000000, "source": "manual", "note": None})
        self.assertIsNone(self.bal(self.gold, "2026-11"))

    def test_existing_manual_kept_by_default(self):
        core.set_balance(self.conn, self.lh, "2026-11", "296000")
        pv = core.preview_allocation(self.conn, "2026-11", self.inputs)
        row = next(r for r in pv["rows"] if r["account_id"] == self.lh)
        self.assertTrue(row["keeps_manual"])
        self.assertEqual(row["default_satang"], 37400000)
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        self.assertEqual(self.bal(self.lh, "2026-11")["amount_satang"], 29600000)

    def test_edit_previous_month_updates_automatic_values_only(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        core.set_balance(self.conn, self.save, "2026-11", "120000")  # manual now
        self.assertEqual(core.dependents(self.conn, self.a1, "2026-10"), [{"period": "2026-11", "source": "allocated"}])
        r = core.set_balance(self.conn, self.a1, "2026-10", "150000")
        self.assertEqual(self.bal(self.a1, "2026-11")["amount_satang"], 15000000 + 2700000)
        self.assertEqual(r["propagated"][0]["period"], "2026-11")
        core.set_balance(self.conn, self.gold, "2026-10", "220000")
        self.assertEqual(self.bal(self.gold, "2026-11")["amount_satang"], 22000000)
        core.set_balance(self.conn, self.save, "2026-10", "1")
        self.assertEqual(self.bal(self.save, "2026-11")["amount_satang"], 12000000)  # manual untouched
        core.set_balance(self.conn, self.a2, "2026-10", "1")
        self.assertEqual(self.bal(self.a2, "2026-11")["amount_satang"], 3660000)  # target, not prev-based

    def test_chain_through_months(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        core.confirm_allocation(self.conn, "2026-12", self.inputs)
        self.assertEqual(self.bal(self.lh, "2026-12")["amount_satang"], 31700000 + 2 * 5700000)
        core.set_balance(self.conn, self.lh, "2026-10", "300000")
        self.assertEqual(self.bal(self.lh, "2026-12")["amount_satang"], 30000000 + 2 * 5700000)

    def test_reconfirm_with_new_inputs(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        core.confirm_allocation(self.conn, "2026-11", {**self.inputs, "salary": "140000"})
        self.assertEqual(self.bal(self.lh, "2026-11")["amount_satang"], 31700000 + 6200000)
        self.assertEqual(len(core.list_periods(self.conn)), 2)

    def test_delete_allocation_keeps_balances(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        with self.assertRaises(ValidationError):
            core.delete_period(self.conn, "2026-11")
        core.delete_allocation(self.conn, "2026-11")
        self.assertEqual(self.bal(self.lh, "2026-11")["source"], "manual")
        self.assertEqual(self.bal(self.gold, "2026-11")["source"], "carried")

    def test_json_roundtrip_v3(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        other = core.connect(":memory:")
        core.restore_json(other, core.export_json(self.conn))
        self.assertEqual(core.list_balances(other), core.list_balances(self.conn))
        self.assertEqual(core._get_allocation(other, "2026-11"), core._get_allocation(self.conn, "2026-11"))
        other.close()

    def test_export_has_allocation_rows(self):
        core.confirm_allocation(self.conn, "2026-11", self.inputs)
        wide = core.export_wide_rows(self.conn)
        lh = next(r for r in wide if r[2] == "จัดสรร: โอนไป LH")
        self.assertEqual(lh[-2:], ["", "57000.00"])


def _make_v1_db(path):
    raw = sqlite3.connect(path, isolation_level=None)
    for stmt in core._SCHEMA_V1:
        raw.execute(stmt)
    raw.executemany("INSERT INTO account_groups(code, name_th, name_en, sort_order, description)"
                    " VALUES (?,?,?,?,?)", core.DEFAULT_GROUPS)
    raw.execute("INSERT INTO accounts VALUES ('acc_1','LH','D',1,NULL,1,'t','t')")
    raw.execute("INSERT INTO periods VALUES ('2026-10','t')")
    raw.execute("INSERT INTO balances VALUES ('acc_1','2026-10',31700000,0,'n','t')")
    raw.execute("INSERT INTO periods VALUES ('2026-11','t')")
    raw.execute("INSERT INTO balances VALUES ('acc_1','2026-11',100,1,NULL,'t')")
    raw.execute("PRAGMA user_version = 1")
    return raw


class TestMigrations(unittest.TestCase):
    def test_v1_to_v3_keeps_balances(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.sqlite")
            _make_v1_db(path).close()
            bk = core.backup_file_before_migration(path, os.path.join(d, "bk"))
            self.assertTrue(bk and os.path.exists(bk))
            conn = core.connect(path)
            rows = core.list_balances(conn)
            self.assertEqual([(r["period"], r["amount_satang"], r["source"], r["note"]) for r in rows],
                             [("2026-10", 31700000, "manual", "n"), ("2026-11", 100, "carried", None)])
            self.assertEqual(core.schema_version(conn), 3)
            self.assertIsNone(core.backup_file_before_migration(path, os.path.join(d, "bk")))
            conn.close()

    def test_v2_to_v3_keeps_end_and_archives_begin(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "v2.sqlite")
            raw = _make_v1_db(path)
            for stmt in core._MIGRATE_V2:
                raw.execute(stmt)
            raw.execute("INSERT INTO balances VALUES ('acc_1','2026-11','begin',5,'transfer',NULL,'t')")
            raw.execute("INSERT INTO month_plans(period, income_satang, status, updated_at)"
                        " VALUES ('2026-11', 9, 'draft', 't')")
            raw.execute("PRAGMA user_version = 2")
            raw.close()
            conn = core.connect(path)
            self.assertEqual([(r["period"], r["amount_satang"]) for r in core.list_balances(conn)],
                             [("2026-10", 31700000), ("2026-11", 100)])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM legacy_v2_balances WHERE kind='begin'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM legacy_v2_month_plans").fetchone()[0], 1)
            core.restore_json(conn, core.export_json(conn))  # legacy tables do not block a restore
            conn.close()

    def test_restore_v1_and_v2_backups(self):
        base = {"format": "family-finance-dashboard/backup",
                "groups": [{"code": "A", "name_th": "ก", "name_en": "", "sort_order": 1, "description": None}],
                "accounts": [{"id": "acc_1", "name": "x", "group_code": "A", "sort_order": 1, "note": None,
                              "is_active": 1, "created_at": "t", "updated_at": "t"}],
                "periods": [{"period": "2026-01", "created_at": "t"}]}
        v1 = {**base, "schema_version": 1,
              "balances": [{"account_id": "acc_1", "period": "2026-01", "amount_satang": 5, "is_carried": 0,
                            "note": None, "updated_at": "t"}]}
        v2 = {**base, "schema_version": 2,
              "balances": [{"account_id": "acc_1", "period": "2026-01", "kind": k, "amount_satang": n,
                            "source": "manual", "note": None, "updated_at": "t"} for k, n in (("begin", 1), ("end", 7))],
              "month_plans": []}
        conn = core.connect(":memory:")
        core.restore_json(conn, v1)
        self.assertEqual(core.list_balances(conn)[0]["amount_satang"], 5)
        core.restore_json(conn, v2)
        self.assertEqual([b["amount_satang"] for b in core.list_balances(conn)], [7])
        conn.close()


if __name__ == "__main__":
    unittest.main()
