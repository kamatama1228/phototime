"""--undo の後、全 file の SHA256 と mtime が --apply 直前と一致する。"""

import os
import tempfile
import unittest

import qasupport as qa


class UndoRestores(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")

        # 書き換え方の違う file を 1 つずつ置く。
        # (1) EXIF の上書き（瞬間 + 明示）
        a = os.path.join(self.root, "a.jpg")
        qa.write(a, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(a, qa.EPOCH_20230504)
        # (2) EXIF の上書き（壁時計、file 名）
        qa.write(os.path.join(self.root, "20230504_123456.jpg"),
                 qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000001)
        # (3) tag が無く XMP sidecar に逃げる file
        qa.write(os.path.join(self.root, "20190801_070000.jpg"),
                 qa.build_jpeg(exif=None), mtime=1000000002)
        # (4) EXIF は既に正しく、mtime だけが揃っていない file
        qa.write(os.path.join(self.root, "wallclock_only.jpg"),
                 qa.plain_jpeg(qa.WALLCLOCK_AT_PLUS0900, "+09:00"),
                 mtime=1000000003)
        # (5) 扱えない file
        qa.write(os.path.join(self.root, "broken.jpg"), b"\xff\xd8\x00",
                 mtime=1000000004)

    def _apply_then_undo(self, *extra):
        before = qa.snapshot(self.root)
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--journal", self.journal]
            + list(extra))
        self.assertEqual(code, 0)
        after_apply = qa.snapshot(self.root)
        self.assertNotEqual(after_apply, before, "--apply が何も変えていない")

        code, _out, err = qa.run_cli(["--undo", self.journal])
        self.assertEqual(code, 0, err)
        return before, after_apply, qa.snapshot(self.root)

    def test_undo_restores_sha256_and_mtime(self):
        before, _after, restored = self._apply_then_undo()
        self.assertEqual(sorted(restored), sorted(before),
                         "undo の後に file が増減している（%s）"
                         % sorted(set(restored) ^ set(before)))
        for name in before:
            self.assertEqual(restored[name], before[name],
                             "%s の SHA256 / mtime が戻っていない" % name)

    def test_undo_with_rename(self):
        """--rename を伴う --apply も、file 名まで元に戻る。"""
        before, after_apply, restored = self._apply_then_undo("--rename")
        self.assertNotEqual(sorted(after_apply), sorted(before),
                            "--rename が file 名を変えていない")
        self.assertEqual(restored, before)

    def test_undo_removes_created_sidecars(self):
        before, after_apply, restored = self._apply_then_undo()
        created = set(after_apply) - set(before)
        self.assertTrue(any(name.endswith(".xmp") for name in created),
                        "この fixture では .xmp が作られるはず")
        self.assertEqual(set(restored), set(before),
                         "undo が作った sidecar を消していない")

    def test_undo_twice_is_safe(self):
        """2 回 undo しても例外にならず、状態も変わらない。"""
        before, _after, restored = self._apply_then_undo()
        code, _out, _err = qa.run_cli(["--undo", self.journal])
        self.assertEqual(code, 0)
        self.assertEqual(qa.snapshot(self.root), restored)
        self.assertEqual(qa.snapshot(self.root), before)

    def test_undo_rejects_foreign_journal(self):
        """phototime の journal でない file は、終了 code 2 で断る。"""
        bogus = os.path.join(self.outside, "bogus.json")
        with open(bogus, "w", encoding="utf-8") as handle:
            handle.write('{"tool": "something-else"}')
        code, _out, err = qa.run_cli(["--undo", bogus])
        self.assertEqual(code, 2)
        self.assertIn("journal", err)

    def test_undo_rejects_missing_journal(self):
        code, _out, _err = qa.run_cli(
            ["--undo", os.path.join(self.outside, "nope.json")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
