"""tag が存在しない JPEG に `--apply` しても、EXIF を変えない。

`.xmp` が生成され、終了 code 0 と「tag は追加しない」旨の警告が出る。
tag の新規追加は行わない（IFD の再構築で file を壊さないため）。
"""

import os
import tempfile
import unittest

import support


class MissingTagFallsBackToSidecar(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)

        # file 名が壁時計の情報源になるため、オフセットの明示は要らない。
        self.jpeg = os.path.join(self.root, "20230504_121456.jpg")
        support.write_jpeg(self.jpeg, datetime_original=None,
                           offset_time_original=None)
        self.journal = os.path.join(self.out.name, "journal.json")

    def test_exif_untouched_xmp_created_and_warned(self):
        sha_before = support.sha256(self.jpeg)
        mtime_before = os.stat(self.jpeg).st_mtime_ns

        result = support.run_cli([self.root, "--apply", "--journal", self.journal])

        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(support.sha256(self.jpeg), sha_before,
                         "EXIF を変更している（tag を追加した疑い）")
        self.assertEqual(os.stat(self.jpeg).st_mtime_ns, mtime_before)
        self.assertTrue(os.path.exists(self.jpeg + ".xmp"),
                        "XMP sidecar が作られていない")
        self.assertIn("does not add tags", result.err)

    def test_sidecar_contains_the_decided_datetime(self):
        support.run_cli([self.root, "--apply", "--journal", self.journal])
        with open(self.jpeg + ".xmp", "r", encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("2023-05-04T12:14:56", body)
        self.assertIn("exif:DateTimeOriginal", body)

    def test_sidecar_records_the_offset_when_explicit(self):
        support.run_cli([self.root, "--apply", "--shift", "+09:00",
                         "--journal", self.journal])
        with open(self.jpeg + ".xmp", "r", encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("2023-05-04T12:14:56+09:00", body)

    def test_no_sidecar_in_dry_run(self):
        result = support.run_cli([self.root])
        self.assertEqual(result.code, 0, result.err)
        self.assertFalse(os.path.exists(self.jpeg + ".xmp"))
        self.assertIn("does not add tags", result.err)

    def test_no_xmp_option_suppresses_the_sidecar(self):
        result = support.run_cli([self.root, "--apply", "--no-xmp",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertFalse(os.path.exists(self.jpeg + ".xmp"))


if __name__ == "__main__":
    unittest.main()
