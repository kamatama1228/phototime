"""`--undo` の後、全 file の SHA256 と mtime が `--apply` 直前の値と一致する。

rename と sidecar の作成も含めて元に戻せることを確かめる。
"""

import os
import tempfile
import unittest

import support

EPOCH = 1683170096


class UndoRestoresEverything(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.journal = os.path.join(self.out.name, "journal.json")

        # EXIF を上書きする file
        patched = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(patched)
        support.write_sidecar(patched, EPOCH)
        # sidecar に逃がす file（EXIF に日時 tag が無い）
        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"),
                           datetime_original=None, offset_time_original=None)
        # 触らない file
        support.write_bytes(os.path.join(self.root, "notes.txt"), b"hello")

    def test_undo_after_apply(self):
        before = support.snapshot(self.root)
        applied = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                   "--journal", self.journal])
        self.assertEqual(applied.code, 0, applied.err)
        self.assertNotEqual(support.snapshot(self.root), before,
                            "--apply が何も変えていない（test が無意味になる）")

        undone = support.run_cli(["--undo", self.journal])
        self.assertEqual(undone.code, 0, undone.err)
        self.assertEqual(support.snapshot(self.root), before)

    def test_undo_after_apply_with_rename(self):
        before = support.snapshot(self.root)
        applied = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                   "--rename", "--journal", self.journal])
        self.assertEqual(applied.code, 0, applied.err)
        self.assertTrue(
            os.path.exists(os.path.join(self.root,
                                        "2023-05-04_121456_IMG_0001.jpg")),
            "rename が行われていない（test が無意味になる）")

        undone = support.run_cli(["--undo", self.journal])
        self.assertEqual(undone.code, 0, undone.err)
        self.assertEqual(support.snapshot(self.root), before)

    def test_undo_removes_created_sidecars(self):
        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])
        sidecar = os.path.join(self.root, "20230504_121456.jpg.xmp")
        self.assertTrue(os.path.exists(sidecar))

        support.run_cli(["--undo", self.journal])
        self.assertFalse(os.path.exists(sidecar), "作った sidecar が残っている")

    def test_undo_rejects_a_foreign_journal(self):
        foreign = os.path.join(self.out.name, "foreign.json")
        with open(foreign, "w", encoding="utf-8") as handle:
            handle.write('{"tool": "something-else"}')
        result = support.run_cli(["--undo", foreign])
        self.assertEqual(result.code, 2)


if __name__ == "__main__":
    unittest.main()
