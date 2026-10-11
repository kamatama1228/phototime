"""扱えない file を与えても、例外で停止しない。

(1) 壊れた JPEG、(2) 空 file、(3) 画像でない file、(4) 読めるが想定した構造でない
JPEG の 4 種類について、その file を skip して CSV に理由を書き、終了 code 0 で
終わる。**(4) の reason は `unsupported_structure` とし、書き換えは行わない。**

**(4) に当たるのは、EXIF の APP1 が 2 つ以上ある JPEG だけである。** 「APP1 が
複数ある」（XMP など EXIF 以外の APP1 を含む場合）と「EOI の後ろに独自 data が
ある」は、実機の写真によくある構造であり、**受け入れて処理する**側に移した。
受け入れる側の検証は `test_ac14_real_world_structures.py` にある。
"""

import os
import tempfile
import unittest

import support


class MalformedInputsAreSkipped(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.report = os.path.join(self.out.name, "report.csv")
        self.journal = os.path.join(self.out.name, "journal.json")

        # (1) 壊れた JPEG（SOI の後ろが marker になっていない）
        support.write_bytes(os.path.join(self.root, "broken.jpg"),
                            b"\xff\xd8" + bytes(range(16)))
        # (2) 空 file
        support.write_bytes(os.path.join(self.root, "empty.jpg"), b"")
        # (3) 画像でない file
        support.write_bytes(os.path.join(self.root, "notes.txt"),
                            "ただの文章です\n".encode("utf-8"))
        # (4) EXIF の APP1 が 2 つある JPEG
        support.write_jpeg(os.path.join(self.root, "two_app1.jpg"), app1_count=2)
        # (1-b) 画像が EOI で閉じていない（途中で切り詰められた）JPEG
        support.write_bytes(os.path.join(self.root, "truncated.jpg"),
                            support.jpeg_bytes()[:-2])

    def _rows(self, argv):
        result = support.run_cli(argv + ["--report", self.report])
        header, rows = support.read_csv(self.report)
        return result, header, rows

    def test_all_four_kinds_are_skipped_with_exit_zero(self):
        before = support.snapshot(self.root)
        result, header, rows = self._rows([self.root, "--shift", "+09:00"])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(support.snapshot(self.root), before)

        expected = {
            "broken.jpg": "unreadable_jpeg",
            "empty.jpg": "empty_file",
            "notes.txt": "not_a_jpeg",
            "two_app1.jpg": "unsupported_structure",
            "truncated.jpg": "unreadable_jpeg",
        }
        for name, reason in expected.items():
            row = support.csv_row_for(rows, header, name)
            self.assertEqual(row["action"], "skipped", name)
            self.assertEqual(row["reason"], reason, name)

    def test_apply_does_not_modify_malformed_files(self):
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(support.snapshot(self.root), before,
                         "扱えない file を書き換えている")

    def test_a_healthy_file_still_works_alongside_malformed_ones(self):
        """1 枚でも壊れていると全体が止まる、という作りになっていないこと。"""
        healthy = os.path.join(self.root, "20230504_121456.jpg")
        support.write_jpeg(healthy)
        result, header, rows = self._rows([self.root, "--shift", "+09:00"])
        self.assertEqual(result.code, 0, result.err)
        row = support.csv_row_for(rows, header, "20230504_121456.jpg")
        self.assertEqual(row["action"], "would_update")


if __name__ == "__main__":
    unittest.main()
