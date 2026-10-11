"""実機の写真によくある 2 つの構造を、`unsupported_structure` にしない。

- **(a) APP1 が 2 つ以上ある JPEG**（EXIF の APP1 と XMP の APP1 が両方ある等）
  - payload の先頭が `Exif\\x00\\x00` の APP1 だけを EXIF として扱う。
  - それ以外の APP1（XMP など）は読み飛ばし、1 byte も書き換えない。
  - **`Exif\\x00\\x00` で始まる APP1 が 2 つ以上あるときだけ** `unsupported_structure`。
- **(b) EOI の後ろに data がある JPEG**（motion photo、端末メーカーの独自 data）
  - その data を 1 byte も変えずに残したまま、通常どおり処理する。

(a)(b) そのものの検証に加え、**新しく受け入れる 2 種類の file に対しても、
「既定では 1 byte も変わらない」「`--apply` が画像 data 部を変えない」
「`--undo` で完全に戻る」が成り立つこと**を確かめる。受け入れる入力が増えた
ぶん、これらの要求は厳しくなっている。
"""

import os
import tempfile
import unittest

import support

EPOCH = 1683170096                        # UTC 2023-05-04 03:14:56
EXPECTED_JST = "2023:05:04 12:14:56"      # +09:00 に直した壁時計
TRAILING = b"MOTION-PHOTO-PAYLOAD\xff\xd9\x00\x01\x02"


class RealWorldStructuresBase(unittest.TestCase):
    """対象 directory と、報告先・journal の置き場所を用意する。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.report = os.path.join(self.out.name, "report.csv")
        self.journal = os.path.join(self.out.name, "journal.json")

    def _row(self, name, argv):
        result = support.run_cli(argv + ["--report", self.report])
        self.assertEqual(result.code, 0, result.err)
        header, rows = support.read_csv(self.report)
        return result, support.csv_row_for(rows, header, name)


class ExifAndXmpApp1(RealWorldStructuresBase):
    """(a)：EXIF と XMP の APP1 を両方持つ JPEG。"""

    def setUp(self):
        super().setUp()
        self.jpeg = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(self.jpeg, xmp_app1=True)
        support.write_sidecar(self.jpeg, EPOCH)

    def test_the_file_is_not_skipped(self):
        _result, row = self._row("IMG_0001.jpg", [self.root, "--shift", "+09:00"])

        self.assertNotEqual(row["reason"], "unsupported_structure",
                            "XMP の APP1 があるだけで skip している")
        self.assertEqual(row["action"], "would_update")
        self.assertEqual(row["after_datetime"], EXPECTED_JST)
        self.assertEqual(row["after_offset"], "+09:00")

    def test_apply_writes_the_datetime(self):
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        written_datetime, written_offset = support.read_exif(self.jpeg)
        self.assertEqual(written_datetime, EXPECTED_JST)
        self.assertEqual(written_offset, "+09:00")

    def test_apply_does_not_touch_the_xmp_app1(self):
        """XMP の APP1 が、位置も中身も 1 byte も変わっていないこと。"""
        before_offset, before_bytes = support.xmp_app1_region(self.jpeg)

        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        after_offset, after_bytes = support.xmp_app1_region(self.jpeg)
        self.assertEqual(after_offset, before_offset, "XMP の APP1 の位置が動いた")
        self.assertEqual(after_bytes, before_bytes, "XMP の APP1 が書き換わった")

    def test_ac3_still_holds(self):
        """画像 data 部（SOS 以降）が完全に一致し、file の大きさも変わらない。"""
        before = support.image_data_after_sos(self.jpeg)
        before_size = os.path.getsize(self.jpeg)

        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])

        self.assertEqual(support.image_data_after_sos(self.jpeg), before)
        self.assertEqual(os.path.getsize(self.jpeg), before_size)

    def test_ac1_still_holds(self):
        """既定（`--apply` 無し）では 1 byte も変わらない。"""
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00"])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(support.snapshot(self.root), before)

    def test_ac5_still_holds(self):
        """`--undo` で file 全体の byte 列と mtime が戻る。"""
        before = support.snapshot(self.root)
        applied = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                   "--journal", self.journal])
        self.assertEqual(applied.code, 0, applied.err)
        self.assertNotEqual(support.snapshot(self.root), before,
                            "そもそも書き換えが起きていない")

        undone = support.run_cli(["--undo", self.journal])
        self.assertEqual(undone.code, 0, undone.err)
        self.assertEqual(support.snapshot(self.root), before)


class TwoExifApp1s(RealWorldStructuresBase):
    """(a)：EXIF の APP1 が 2 つある JPEG は、従来どおり skip。"""

    def setUp(self):
        super().setUp()
        self.jpeg = os.path.join(self.root, "two_exif.jpg")
        support.write_jpeg(self.jpeg, app1_count=2)
        support.write_sidecar(self.jpeg, EPOCH)

    def test_still_unsupported_structure(self):
        _result, row = self._row("two_exif.jpg", [self.root, "--shift", "+09:00"])

        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "unsupported_structure")

    def test_apply_does_not_modify_it(self):
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(support.snapshot(self.root), before)

    def test_an_xmp_app1_does_not_rescue_two_exif_app1s(self):
        """XMP が混ざっていても、EXIF の APP1 が 2 つなら skip のままである。"""
        other = os.path.join(self.root, "two_exif_plus_xmp.jpg")
        support.write_jpeg(other, app1_count=2, xmp_app1=True)
        support.write_sidecar(other, EPOCH)

        _result, row = self._row("two_exif_plus_xmp.jpg",
                                 [self.root, "--shift", "+09:00"])
        self.assertEqual(row["reason"], "unsupported_structure")


class DataAfterEoi(RealWorldStructuresBase):
    """(b)：EOI の後ろに data がある JPEG。"""

    def setUp(self):
        super().setUp()
        self.jpeg = os.path.join(self.root, "MVIMG_0002.jpg")
        support.write_jpeg(self.jpeg, trailing=TRAILING)
        support.write_sidecar(self.jpeg, EPOCH)

    def test_the_file_is_not_skipped(self):
        _result, row = self._row("MVIMG_0002.jpg", [self.root, "--shift", "+09:00"])

        self.assertNotEqual(row["reason"], "unsupported_structure",
                            "EOI の後ろに data があるだけで skip している")
        self.assertEqual(row["action"], "would_update")
        self.assertEqual(row["after_datetime"], EXPECTED_JST)

    def test_apply_writes_the_datetime(self):
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        written_datetime, written_offset = support.read_exif(self.jpeg)
        self.assertEqual(written_datetime, EXPECTED_JST)
        self.assertEqual(written_offset, "+09:00")

    def test_apply_does_not_touch_the_trailing_data(self):
        """EOI の後ろの data が 1 byte も変わっていないこと。

        `TRAILING` には `\\xff\\xd9` が含まれている。後ろから EOI を探す実装だと、
        画像本体の終わりをここだと誤認する（CEO が State に書いた注意点）。
        """
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        self.assertEqual(support.trailing_region(self.jpeg, len(TRAILING)),
                         TRAILING, "EOI の後ろの data が書き換わった")

    def test_ac3_still_holds(self):
        before = support.image_data_after_sos(self.jpeg)
        before_size = os.path.getsize(self.jpeg)

        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])

        self.assertEqual(support.image_data_after_sos(self.jpeg), before)
        self.assertEqual(os.path.getsize(self.jpeg), before_size)

    def test_ac1_still_holds(self):
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00"])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(support.snapshot(self.root), before)

    def test_ac5_undo_restores_the_whole_file(self):
        """`--undo` で file 全体の byte 列が元に戻る。"""
        before_bytes = support.file_bytes(self.jpeg)
        before = support.snapshot(self.root)

        applied = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                   "--journal", self.journal])
        self.assertEqual(applied.code, 0, applied.err)
        self.assertNotEqual(support.file_bytes(self.jpeg), before_bytes,
                            "そもそも書き換えが起きていない")

        undone = support.run_cli(["--undo", self.journal])
        self.assertEqual(undone.code, 0, undone.err)
        self.assertEqual(support.file_bytes(self.jpeg), before_bytes)
        self.assertEqual(support.snapshot(self.root), before)


class BothStructuresAtOnce(RealWorldStructuresBase):
    """XMP の APP1 と EOI 後ろの data が同じ file にある場合（実機では普通）。"""

    def setUp(self):
        super().setUp()
        self.jpeg = os.path.join(self.root, "MVIMG_0003.jpg")
        support.write_jpeg(self.jpeg, xmp_app1=True, trailing=TRAILING)
        support.write_sidecar(self.jpeg, EPOCH)

    def test_processed_and_both_regions_are_untouched(self):
        before_xmp_offset, before_xmp = support.xmp_app1_region(self.jpeg)

        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        written_datetime, _offset = support.read_exif(self.jpeg)
        self.assertEqual(written_datetime, EXPECTED_JST)
        self.assertEqual(support.xmp_app1_region(self.jpeg),
                         (before_xmp_offset, before_xmp))
        self.assertEqual(support.trailing_region(self.jpeg, len(TRAILING)),
                         TRAILING)


class XmpApp1WithoutExif(RealWorldStructuresBase):
    """APP1 が XMP しか無い JPEG は「EXIF が無い」扱いになり、sidecar に逃げる。"""

    def setUp(self):
        super().setUp()
        self.jpeg = os.path.join(self.root, "IMG_0004.jpg")
        support.write_jpeg(self.jpeg, app1_count=0, xmp_app1=True)
        support.write_sidecar(self.jpeg, EPOCH)

    def test_goes_to_the_xmp_sidecar_path_not_unsupported(self):
        _result, row = self._row("IMG_0004.jpg", [self.root, "--shift", "+09:00"])

        self.assertNotEqual(row["reason"], "unsupported_structure")
        self.assertEqual(row["reason"], "exif_tag_absent")

    def test_apply_does_not_change_the_jpeg_itself(self):
        before_bytes = support.file_bytes(self.jpeg)

        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        self.assertEqual(support.file_bytes(self.jpeg), before_bytes,
                         "EXIF が無いのに JPEG を書き換えている")
        self.assertTrue(os.path.exists(self.jpeg + ".xmp"))


if __name__ == "__main__":
    unittest.main()
