"""`--apply` 後、書いた値が読み戻せ、画像 data 部が byte 単位で変わらない。

「静かに壊す」ことがないことを byte で示すための基準である。
"""

import os
import tempfile
import unittest

import support

EPOCH = 1683170096
EXPECTED_JST = "2023:05:04 12:14:56"


class ApplyWritesExifWithoutTouchingImageData(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)

        self.jpeg = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(self.jpeg)
        support.write_sidecar(self.jpeg, EPOCH)
        self.journal = os.path.join(self.out.name, "journal.json")

    def test_reread_matches_and_image_data_is_identical(self):
        image_before = support.image_data_after_sos(self.jpeg)
        size_before = os.path.getsize(self.jpeg)

        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        written_datetime, written_offset = support.read_exif(self.jpeg)
        self.assertEqual(written_datetime, EXPECTED_JST)
        self.assertEqual(written_offset, "+09:00")

        self.assertEqual(support.image_data_after_sos(self.jpeg), image_before,
                         "画像 data 部（SOS 以降）が変わった")
        self.assertEqual(os.path.getsize(self.jpeg), size_before,
                         "file の大きさが変わった")

    def test_value_is_present_in_the_raw_bytes(self):
        """実装の reader を通さずに、byte 列の中の値を確かめる。"""
        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])
        self.assertIn(EXPECTED_JST, support.raw_datetime_strings(self.jpeg))
        self.assertIn("+09:00", support.raw_offset_strings(self.jpeg))
        self.assertNotIn("2001:01:01 00:00:00",
                         support.raw_datetime_strings(self.jpeg),
                         "古い値が残っている")

    def test_no_xmp_is_written_when_exif_could_hold_the_values(self):
        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])
        self.assertFalse(os.path.exists(self.jpeg + ".xmp"),
                         "EXIF に書けたのに sidecar を作っている")


if __name__ == "__main__":
    unittest.main()
