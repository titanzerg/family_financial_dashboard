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
        change_row = next(r for r in wide if r[2] == "เปลี่ยนแปลงจากเดือนก่อนหน้า")
        self.assertEqual(change_row[-2:], ["", "-10.00"])
        self.assertEqual(len(core.export_long_rows(self.conn)), 3)


if __name__ == "__main__":
    unittest.main()
