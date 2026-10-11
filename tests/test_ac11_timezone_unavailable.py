"""`zoneinfo` が時刻帯を解決できないとき、例外で停止しない。

`--shift` を使うよう案内して終了 code 2 で終わる。
`--assume-tz` は **OS の時刻帯 database** に依存するため、使えない環境がある。
`--shift` を主、`--assume-tz` を補助に置いているのは、このためである。
"""

import os
import tempfile
import unittest
from unittest import mock

import support
from phototime import tzpolicy


class TimezoneUnavailableIsHandled(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"))

    def test_zoneinfo_not_found_exits_with_two_and_points_at_shift(self):
        def raise_not_found(name):
            raise tzpolicy.ZoneInfoNotFoundError(name)

        before = support.snapshot(self.root)
        with mock.patch.object(tzpolicy, "load_timezone", raise_not_found):
            result = support.run_cli([self.root, "--assume-tz", "Asia/Tokyo",
                                      "--apply"])

        self.assertEqual(result.code, 2)
        self.assertIn("--shift", result.err)
        self.assertEqual(support.snapshot(self.root), before,
                         "中止したのに file を変更している")

    def test_other_zoneinfo_failures_are_also_contained(self):
        """database の破損など、別の例外でも落ちない。"""
        def raise_oserror(name):
            raise OSError("time zone database is unreadable")

        with mock.patch.object(tzpolicy, "load_timezone", raise_oserror):
            result = support.run_cli([self.root, "--assume-tz", "Asia/Tokyo"])
        self.assertEqual(result.code, 2)
        self.assertIn("--shift", result.err)

    def test_unknown_timezone_name_exits_with_two(self):
        result = support.run_cli([self.root, "--assume-tz", "Not/AZone"])
        self.assertEqual(result.code, 2)

    def test_malformed_shift_exits_with_two(self):
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "9", "--apply"])
        self.assertEqual(result.code, 2)
        self.assertEqual(support.snapshot(self.root), before)

    def test_shift_does_not_depend_on_the_timezone_database(self):
        """`--shift` は load_timezone を 1 度も呼ばない。"""
        with mock.patch.object(tzpolicy, "load_timezone") as loader:
            result = support.run_cli([self.root, "--shift", "+09:00"])
        self.assertEqual(result.code, 0, result.err)
        loader.assert_not_called()


class ShiftParsing(unittest.TestCase):

    def test_accepted_forms(self):
        for text, expected in (("+09:00", "+09:00"), ("-07:00", "-07:00"),
                               ("+0530", "+05:30"), ("+00:00", "+00:00")):
            tzinfo = tzpolicy.parse_shift(text)
            self.assertIsNotNone(tzinfo, text)
            self.assertEqual(tzpolicy.format_offset(tzinfo.utcoffset(None)),
                             expected)

    def test_rejected_forms(self):
        for text in ("09:00", "+9:00", "+25:00", "+09:60", "JST", ""):
            self.assertIsNone(tzpolicy.parse_shift(text), text)


if __name__ == "__main__":
    unittest.main()
