"""情報源の種別ごとの規則と、「静かにずらす」経路が閉じていることの確認。

**情報源が「瞬間」（JSON sidecar の epoch、file の mtime）のときだけ、
明示されたオフセットで壁時計に直す。明示が無ければ skip する。**
**情報源が「壁時計」（file 名、既存の EXIF）のときは、その値をそのまま
使い、`--shift` でずらさない。** ここが崩れると `--apply` が全 file を
静かにずらすため、この製品で最も重い要求である。
"""

import os
import tempfile
import unittest

import qasupport as qa


class InstantSource(unittest.TestCase):
    """情報源が「瞬間」（JSON sidecar の epoch 秒・mtime）のとき。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.photo = os.path.join(self.root, "photo.jpg")
        qa.write(self.photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(self.photo, qa.EPOCH_20230504)
        self.report = os.path.join(tempfile.mkdtemp(), "plan.csv")

    def test_ac2a_sidecar_epoch_with_shift(self):
        """epoch を +09:00 で変換した壁時計と秒単位で一致する。"""
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["photo.jpg"]
        self.assertEqual(row["source"], "json_sidecar")
        self.assertEqual(row["source_kind"], "instant")
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(row["after_offset"], "+09:00")

    def test_ac2a_written_value_matches_after_apply(self):
        """実際に書いた byte を QA 側の parser で読み直して一致を確かめる。"""
        journal = os.path.join(tempfile.mkdtemp(), "undo.json")
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--journal", journal])
        self.assertEqual(code, 0)
        values = qa.exif_of(self.photo)
        self.assertEqual(values[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(values[qa.TAG_OFFSET_TIME_ORIGINAL], "+09:00")

    def test_ac2a_other_offset_gives_other_wallclock(self):
        """オフセットを変えれば壁時計も変わる（UTC での確認）。"""
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+00:00", "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["photo.jpg"]
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_UTC)
        self.assertEqual(row["after_offset"], "+00:00")

    def test_ac2b_no_explicit_offset_skips(self):
        """明示が無ければ skip / offset_required。"""
        code, _out, _err = qa.run_cli([self.root, "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["photo.jpg"]
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "offset_required")
        self.assertEqual(row["source_kind"], "instant")

    def test_ac2b_apply_without_offset_does_not_touch_file(self):
        """明示が無いとき、--apply を付けても 1 byte も変わらない。"""
        before = qa.snapshot(self.root)
        journal = os.path.join(tempfile.mkdtemp(), "undo.json")
        code, _out, _err = qa.run_cli([self.root, "--apply", "--journal", journal])
        self.assertEqual(code, 0)
        self.assertEqual(qa.snapshot(self.root), before)

    def test_mtime_source_also_requires_explicit_offset(self):
        """(d) mtime も「瞬間」である。明示が無ければ skip する。"""
        other = os.path.join(self.root, "nohint.jpg")
        qa.write(other, qa.plain_jpeg(with_datetime=False, with_offset=False),
                 mtime=qa.EPOCH_20230504)
        code, _out, _err = qa.run_cli([self.root, "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["nohint.jpg"]
        self.assertEqual(row["source"], "mtime")
        self.assertEqual(row["source_kind"], "instant")
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "offset_required")


class WallclockSource(unittest.TestCase):
    """情報源が「壁時計」（file 名・既存 EXIF）のとき。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.report = os.path.join(tempfile.mkdtemp(), "plan.csv")
        self.exif_photo = os.path.join(self.root, "trip.jpg")
        qa.write(self.exif_photo,
                 qa.plain_jpeg(qa.WALLCLOCK_AT_PLUS0900, "+00:00"),
                 mtime=1000000000)
        self.named_photo = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(self.named_photo,
                 qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000001)

    def test_shift_does_not_move_wallclock_from_exif(self):
        """**最重要**: --shift は既存 EXIF の壁時計をずらしてはいけない。"""
        journal = os.path.join(tempfile.mkdtemp(), "undo.json")
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--journal", journal,
             "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["trip.jpg"]
        self.assertEqual(row["source_kind"], "wallclock")
        self.assertEqual(row["before_datetime"], qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900,
                         "壁時計の情報源が --shift の分だけずらされている")
        values = qa.exif_of(self.exif_photo)
        self.assertEqual(values[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(values[qa.TAG_OFFSET_TIME_ORIGINAL], "+09:00",
                         "オフセットは明示があるので書かれるはず")

    def test_filename_wallclock_is_used_verbatim(self):
        """file 名の日時は、そのまま DateTimeOriginal になる。"""
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["20230504_123456.jpg"]
        self.assertEqual(row["source"], "filename")
        self.assertEqual(row["source_kind"], "wallclock")
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900)

    def test_no_offset_written_without_explicit_offset(self):
        """明示が無ければ、オフセットを書かない（既存の挙動を変えない側）。"""
        before = qa.snapshot(self.root)
        journal = os.path.join(tempfile.mkdtemp(), "undo.json")
        code, _out, _err = qa.run_cli(
            [self.root, "--apply", "--journal", journal, "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["trip.jpg"]
        self.assertEqual(row["after_offset"], "",
                         "明示が無いのにオフセットを書いている")
        self.assertEqual(row["action"], "unchanged")
        self.assertEqual(
            qa.snapshot(self.root)[os.path.basename(self.exif_photo)],
            before[os.path.basename(self.exif_photo)],
            "明示が無いのに file が変わっている")

    def test_sidecar_wins_over_filename(self):
        """優先順 (a) → (b)。sidecar があれば「瞬間」として扱う。"""
        qa.write_sidecar(self.named_photo, qa.EPOCH_20230504)
        code, _out, _err = qa.run_cli([self.root, "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["20230504_123456.jpg"]
        self.assertEqual(row["source"], "json_sidecar")
        self.assertEqual(row["source_kind"], "instant")
        self.assertEqual(row["reason"], "offset_required")


if __name__ == "__main__":
    unittest.main()
