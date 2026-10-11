"""時刻帯を解決できないとき、落ちずに --shift を案内し、終了 code 2。"""

import os
import tempfile
import unittest

import qasupport as qa
from phototime import tzpolicy


class TimezoneUnavailable(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")
        self.report = os.path.join(self.outside, "plan.csv")

        photo = os.path.join(self.root, "photo.jpg")
        qa.write(photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(photo, qa.EPOCH_20230504)
        self.before = qa.snapshot(self.root)

        self.original = tzpolicy.load_timezone
        self.addCleanup(setattr, tzpolicy, "load_timezone", self.original)

    def _break_zoneinfo(self, exception):
        def raising(name):
            raise exception
        tzpolicy.load_timezone = raising

    def test_zoneinfo_not_found_exits_two(self):
        self._break_zoneinfo(tzpolicy.ZoneInfoNotFoundError("Asia/Tokyo"))
        code, _out, err = qa.run_cli([self.root, "--assume-tz", "Asia/Tokyo"])
        self.assertEqual(code, 2)
        self.assertIn("--shift", err, "--shift を使うよう案内していない")

    def test_other_zoneinfo_failure_also_exits_two(self):
        """database が壊れている等、別の例外でも落ちない。"""
        self._break_zoneinfo(OSError("tzdata が読めません"))
        code, _out, err = qa.run_cli([self.root, "--assume-tz", "Asia/Tokyo"])
        self.assertEqual(code, 2)
        self.assertIn("--shift", err)

    def test_apply_does_not_touch_files_when_timezone_fails(self):
        self._break_zoneinfo(tzpolicy.ZoneInfoNotFoundError("Asia/Tokyo"))
        code, _out, _err = qa.run_cli(
            [self.root, "--assume-tz", "Asia/Tokyo", "--apply",
             "--journal", self.journal])
        self.assertEqual(code, 2)
        self.assertEqual(qa.snapshot(self.root), self.before,
                         "失敗したのに file が変わっている")
        self.assertFalse(os.path.exists(self.journal),
                         "中止したのに journal が作られている")
        self.assertFalse(os.path.exists(self.report))

    def test_unknown_zone_name_exits_two_without_patching(self):
        """実環境でも、知らない時刻帯名なら終了 code 2 になる。"""
        code, _out, err = qa.run_cli([self.root, "--assume-tz", "Not/AZone"])
        self.assertEqual(code, 2)
        self.assertIn("--shift", err)

    def test_shift_still_works_when_zoneinfo_is_broken(self):
        """`--shift` は OS の時刻帯 database に依存しない。"""
        self._break_zoneinfo(tzpolicy.ZoneInfoNotFoundError("Asia/Tokyo"))
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["photo.jpg"]
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900)

    def test_malformed_shift_is_rejected(self):
        code, _out, err = qa.run_cli([self.root, "--shift", "9時間"])
        self.assertEqual(code, 2)
        self.assertIn("--shift", err)

    def test_shift_and_assume_tz_together_is_rejected(self):
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--assume-tz", "Asia/Tokyo"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
