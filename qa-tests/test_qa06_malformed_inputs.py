"""壊れた入力 4 種類で停止せず、skip して理由を書き、終了 code 0。

4 種類とは、**(1) 壊れた JPEG、(2) 空 file、(3) 画像でない file、
(4) 読めるが想定した構造でない JPEG** である。

**(4) の範囲は、途中で狭まった。期待値を直したが、合格条件は緩めていない。**

- **以前は (4) の例として「APP1 が複数ある」「EOI の後ろに独自 data が
  ある」の 2 つを挙げており**、この 2 つの file が `unsupported_structure`
  になることを合格として確認していた。
- **しかしこの 2 つは、実機の写真によくある構造である。** そのため
  **「受け入れて処理する側」に移った。** **いま `unsupported_structure`
  にする実装は、逆に誤りである。**
- そこで、**この 2 つを「skip される側」から「skip されない側」へ移した**
  （test を消していない。**逆向きの確認として残してある**）。
- **代わりに、現在の (4) が指す構造**——**`Exif\\x00\\x00` で始まる APP1 が
  2 つ以上ある JPEG**——**の fixture を新しく置いた**（`two_exif.jpg`）。
  **`two_app1.jpg` は、名前に反して「EXIF の APP1 ＋ XMP の APP1」であり、
  現在の (4) の例ではない。**

受け入れる側の検証は `test_qa15_real_world_structures.py` にある。
"""

import os
import tempfile
import unittest

import qasupport as qa
import qastructures as qs

# 「skip される」ことが求められている file。
SKIPPED = ("broken.jpg", "truncated.jpg", "empty.jpg", "note.txt",
           "archive.zip", "two_exif.jpg")

# 受け入れる側に移り、**skip されてはいけなくなった** file。
ACCEPTED = ("trailing.jpg", "two_app1.jpg")


class MalformedInputs(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.report = os.path.join(self.outside, "plan.csv")
        self.journal = os.path.join(self.outside, "undo.json")

        # (1) 壊れた JPEG
        qa.write(os.path.join(self.root, "broken.jpg"),
                 b"\xff\xd8\x11\x22\x33\x44\x55", mtime=1000000000)
        qa.write(os.path.join(self.root, "truncated.jpg"),
                 qa.plain_jpeg()[:20], mtime=1000000001)
        # (2) 空 file
        qa.write(os.path.join(self.root, "empty.jpg"), b"", mtime=1000000002)
        # (3) 画像でない file
        qa.write(os.path.join(self.root, "note.txt"),
                 "これは画像ではありません\n".encode("utf-8"), mtime=1000000003)
        qa.write(os.path.join(self.root, "archive.zip"),
                 b"PK\x03\x04" + b"\x00" * 40, mtime=1000000004)
        # (4) 読めるが想定した構造でない JPEG
        #     ＝ **EXIF の APP1 が 2 つ以上ある**（この範囲まで狭まった）
        qa.write(os.path.join(self.root, "two_exif.jpg"),
                 qs.jpeg([qs.exif_app1(), qs.exif_app1()]),
                 mtime=1000000009)
        # **受け入れる側に移った 2 つ。** skip されてはいけない。
        qa.write(os.path.join(self.root, "trailing.jpg"),
                 qa.build_jpeg(qa.build_exif_tiff(), trailing=b"MY-OWN-DATA"),
                 mtime=1000000005)
        qa.write(os.path.join(self.root, "two_app1.jpg"),
                 qa.build_jpeg(qa.build_exif_tiff(), extra_app1=True),
                 mtime=1000000006)
        # 正常な file も混ぜる（1 枚の失敗で全体が止まらないことの確認）
        good = os.path.join(self.root, "good.jpg")
        qa.write(good, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000007)
        qa.write_sidecar(good, qa.EPOCH_20230504)

    def _rows(self, *extra):
        code, _out, _err = qa.run_cli(
            [self.root, "--report", self.report] + list(extra))
        self.assertEqual(code, 0, "壊れた入力で終了 code が 0 でない")
        return qa.rows_by_name(self.report)

    def test_all_kinds_are_skipped_with_a_reason(self):
        rows = self._rows()
        for name in SKIPPED:
            with self.subTest(name=name):
                self.assertIn(name, rows, "CSV に行が無い")
                self.assertEqual(rows[name]["action"], "skipped")
                self.assertTrue(rows[name]["reason"],
                                "reason が空（理由が書かれていない）")

    def test_unsupported_structure_reason_code(self):
        """(4) の reason は `unsupported_structure` でなければならない。"""
        rows = self._rows()
        self.assertEqual(rows["two_exif.jpg"]["reason"], "unsupported_structure")

    def test_structures_moved_to_ac14_are_not_skipped(self):
        """**受け入れる側に移った 2 つは、skip されてはいけない**（向きが逆転した）。"""
        rows = self._rows("--shift", "+09:00")
        for name in ACCEPTED:
            with self.subTest(name=name):
                self.assertNotEqual(rows[name]["reason"], "unsupported_structure",
                                    "受け入れるはずの file を skip している")
                self.assertNotEqual(rows[name]["action"], "skipped")

    def test_empty_file_has_own_reason(self):
        rows = self._rows()
        self.assertEqual(rows["empty.jpg"]["reason"], "empty_file")

    def test_non_image_has_own_reason(self):
        rows = self._rows()
        self.assertEqual(rows["note.txt"]["reason"], "not_a_jpeg")
        self.assertEqual(rows["archive.zip"]["reason"], "not_a_jpeg")

    def test_good_file_still_processed(self):
        rows = self._rows("--shift", "+09:00")
        self.assertEqual(rows["good.jpg"]["after_datetime"],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(rows["good.jpg"]["action"], "would_update")

    def test_apply_does_not_write_to_malformed_files(self):
        """--apply でも、扱えない file は 1 byte も変わらない。"""
        before = qa.snapshot(self.root)
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--journal", self.journal])
        self.assertEqual(code, 0)
        after = qa.snapshot(self.root)
        for name in SKIPPED:
            with self.subTest(name=name):
                self.assertEqual(after[name], before[name],
                                 "扱えない file が書き換わっている")

    def test_recursive_run_also_survives(self):
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        qa.write(os.path.join(sub, "weird.jpg"), b"\x00" * 100, mtime=1000000008)
        code, _out, _err = qa.run_cli(
            [self.root, "--recursive", "--report", self.report])
        self.assertEqual(code, 0)
        self.assertEqual(qa.rows_by_name(self.report)["weird.jpg"]["action"],
                         "skipped")


if __name__ == "__main__":
    unittest.main()
