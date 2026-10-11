"""情報源が「瞬間」のときの扱い。

- JSON sidecar がある JPEG に `--shift +09:00` を与えたとき、決定した
  `DateTimeOriginal` は sidecar の epoch 秒を +09:00 で変換した壁時計と秒単位で
  一致し、`OffsetTimeOriginal` が `+09:00` になる。
- 同じ file に `--shift` も `--assume-tz` も与えないとき、その file は
  skip され、CSV の `action` が `skipped`、`reason` が `offset_required` になり、
  file は 1 byte も変わらない。

**この 2 本が、「`--apply` が全 file を利用者のオフセット分だけ静かにずらす」
という最も危険な経路をふさいでいる。**
"""

import datetime
import os
import tempfile
import unittest

import support

EPOCH = 1683170096                        # UTC 2023-05-04 03:14:56
EXPECTED_JST = "2023:05:04 12:14:56"      # +09:00 に直した壁時計


class InstantSourceNeedsExplicitOffset(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)

        self.jpeg = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(self.jpeg)
        support.write_sidecar(self.jpeg, EPOCH)
        self.report = os.path.join(self.out.name, "report.csv")

    def _row(self, argv):
        result = support.run_cli(argv + ["--report", self.report])
        self.assertEqual(result.code, 0, result.err)
        header, rows = support.read_csv(self.report)
        return result, support.csv_row_for(rows, header, "IMG_0001.jpg")

    def test_expected_value_matches_an_independent_calculation(self):
        """期待値そのものが正しいことを、literal と計算の両方で確かめる。"""
        jst = datetime.timezone(datetime.timedelta(hours=9))
        computed = datetime.datetime.fromtimestamp(EPOCH, jst)
        self.assertEqual(computed.strftime("%Y:%m:%d %H:%M:%S"), EXPECTED_JST)

    def test_ac2a_with_explicit_shift(self):
        _result, row = self._row([self.root, "--shift", "+09:00"])

        self.assertEqual(row["source"], "json_sidecar")
        self.assertEqual(row["source_kind"], "instant")
        self.assertEqual(row["after_datetime"], EXPECTED_JST)
        self.assertEqual(row["after_offset"], "+09:00")

    def test_ac2a_value_reaches_the_file_after_apply(self):
        journal = os.path.join(self.out.name, "journal.json")
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", journal])
        self.assertEqual(result.code, 0, result.err)

        written_datetime, written_offset = support.read_exif(self.jpeg)
        self.assertEqual(written_datetime, EXPECTED_JST)
        self.assertEqual(written_offset, "+09:00")

    def test_ac2b_without_explicit_offset_the_file_is_skipped(self):
        before = support.snapshot(self.root)
        _result, row = self._row([self.root])
        after = support.snapshot(self.root)

        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "offset_required")
        self.assertEqual(row["source_kind"], "instant")
        self.assertEqual(before, after, "skip したのに file が変わった")

    def test_ac2b_holds_under_apply_as_well(self):
        """`--apply` を付けても、明示が無ければ 1 byte も変えない。"""
        journal = os.path.join(self.out.name, "journal.json")
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--apply", "--journal", journal,
                                  "--report", self.report])
        after = support.snapshot(self.root)

        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(before, after)
        header, rows = support.read_csv(self.report)
        row = support.csv_row_for(rows, header, "IMG_0001.jpg")
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "offset_required")

    def test_mtime_source_is_also_an_instant(self):
        """情報源が mtime だけの file も「瞬間」であり、明示が無ければ skip する。"""
        plain = os.path.join(self.root, "plain.jpg")
        support.write_jpeg(plain, datetime_original=None,
                           offset_time_original=None)
        _result, _row = self._row([self.root])
        header, rows = support.read_csv(self.report)
        row = support.csv_row_for(rows, header, "plain.jpg")
        self.assertEqual(row["source"], "mtime")
        self.assertEqual(row["source_kind"], "instant")
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "offset_required")


class WallclockSourceKeepsItsValue(unittest.TestCase):
    """壁時計の情報源は、明示が無くてもオフセットを書かない（推定しない）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.report = os.path.join(self.out.name, "report.csv")

    def test_filename_source_is_wallclock_and_offset_stays_empty(self):
        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"),
                           datetime_original="2001:01:01 00:00:00",
                           offset_time_original=None)
        result = support.run_cli([self.root, "--report", self.report])
        self.assertEqual(result.code, 0, result.err)

        header, rows = support.read_csv(self.report)
        row = support.csv_row_for(rows, header, "20230504_121456.jpg")
        self.assertEqual(row["source"], "filename")
        self.assertEqual(row["source_kind"], "wallclock")
        self.assertEqual(row["after_datetime"], "2023:05:04 12:14:56")
        self.assertEqual(row["after_offset"], "",
                         "明示が無いのにオフセットを書いている（推定している）")


if __name__ == "__main__":
    unittest.main()
