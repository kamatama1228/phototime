"""--apply の後も画像 data 部が byte 単位で変わらない。"""

import os
import tempfile
import unittest

import qasupport as qa


class ApplyPreservesImage(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")

    def _apply(self, *extra):
        code, _out, err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--journal", self.journal]
            + list(extra))
        return code, err

    def _check(self, path, expected_datetime, expected_offset="+09:00"):
        before = qa.read_file(path)
        code, _err = self._apply()
        self.assertEqual(code, 0)
        after = qa.read_file(path)

        self.assertEqual(len(after), len(before), "file の大きさが変わった")
        self.assertEqual(qa.image_part(after), qa.image_part(before),
                         "SOS 以降の画像 data 部が変わった")
        values = qa.read_exif_values(after)
        self.assertEqual(values.get(qa.TAG_DATETIME_ORIGINAL), expected_datetime)
        if expected_offset is not None:
            self.assertEqual(values.get(qa.TAG_OFFSET_TIME_ORIGINAL),
                             expected_offset)
        self.assertNotEqual(after, before, "この fixture は書き換わるはず")

    def test_big_endian_jpeg(self):
        path = os.path.join(self.root, "photo.jpg")
        qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00",
                                     endian="MM"), mtime=1000000000)
        qa.write_sidecar(path, qa.EPOCH_20230504)
        self._check(path, qa.WALLCLOCK_AT_PLUS0900)

    def test_little_endian_jpeg(self):
        """byte order が II の file でも、画像 data 部を壊さない。"""
        path = os.path.join(self.root, "photo.jpg")
        qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00",
                                     endian="II"), mtime=1000000000)
        qa.write_sidecar(path, qa.EPOCH_20230504)
        self._check(path, qa.WALLCLOCK_AT_PLUS0900)

    def test_tag_without_nul_terminator(self):
        """ASCII 19 / 6 byte（NUL 終端なし）の tag でも、長さを変えずに書けるか。"""
        tiff = qa.build_exif_tiff("2001:01:01 00:00:00", "+00:00",
                                  datetime_length=19, offset_length=6)
        path = os.path.join(self.root, "photo.jpg")
        qa.write(path, qa.build_jpeg(tiff), mtime=1000000000)
        qa.write_sidecar(path, qa.EPOCH_20230504)
        self._check(path, qa.WALLCLOCK_AT_PLUS0900)

    def test_image_bytes_are_not_touched_for_many_files(self):
        """複数 file をまとめて書き換えても、どの file も画像部が一致する。"""
        paths = []
        # 1 分刻みにする（秒の繰り上がりを test 側で計算しないため）。
        for index in range(5):
            path = os.path.join(self.root, "p%d.jpg" % index)
            qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00",
                                         endian="II" if index % 2 else "MM"),
                     mtime=1000000000 + index)
            qa.write_sidecar(path, qa.EPOCH_20230504 + index * 60)
            paths.append((path, qa.read_file(path)))

        code, _err = self._apply()
        self.assertEqual(code, 0)
        for index, (path, before) in enumerate(paths):
            after = qa.read_file(path)
            self.assertEqual(qa.image_part(after), qa.image_part(before), path)
            self.assertEqual(len(after), len(before), path)
            # epoch を index 分ずらしたので、壁時計の分も index 分だけ進む。
            expected = "2023:05:04 12:%02d:56" % (34 + index)
            self.assertEqual(
                qa.read_exif_values(after)[qa.TAG_DATETIME_ORIGINAL],
                expected, path)

    def test_second_run_is_idempotent(self):
        """同じ条件で 2 回実行しても、2 回目は何も変えない。"""
        path = os.path.join(self.root, "photo.jpg")
        qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(path, qa.EPOCH_20230504)
        self._apply()
        snapshot = qa.snapshot(self.root)
        self._apply("--no-mtime")
        self.assertEqual(qa.snapshot(self.root), snapshot,
                         "2 回目の実行で file が変わった")


if __name__ == "__main__":
    unittest.main()
