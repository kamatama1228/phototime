"""既定では file が 1 byte も変わらず、新しい file も作られない。

`--apply` 無し・`--report` 無しで実行したとき、対象 directory 内の全 file の
SHA256 と mtime が実行前と一致し、**file の総数も一致する**。
"""

import os
import tempfile
import unittest

import support

EPOCH = 1683170096  # UTC 2023-05-04 03:14:56


class DefaultRunIsReadOnly(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

        support.write_jpeg(os.path.join(self.root, "IMG_0001.jpg"))
        support.write_sidecar(os.path.join(self.root, "IMG_0001.jpg"), EPOCH)
        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"),
                           datetime_original=None, offset_time_original=None)
        support.write_bytes(os.path.join(self.root, "notes.txt"), b"hello")

    def test_no_change_without_apply(self):
        before = support.snapshot(self.root)
        result = support.run_cli([self.root])
        after = support.snapshot(self.root)

        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(sorted(before), sorted(after), "file の総数が変わった")
        self.assertEqual(before, after, "SHA256 か mtime が変わった")

    def test_no_change_even_when_changes_are_planned(self):
        """オフセットを明示して「変える計画が立つ」場合でも、file は変わらない。"""
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00"])
        after = support.snapshot(self.root)

        self.assertEqual(result.code, 0, result.err)
        self.assertIn("would_update", result.out,
                      "変更の計画が立っていること自体を先に確かめる")
        self.assertEqual(before, after)

    def test_dry_run_is_announced(self):
        result = support.run_cli([self.root])
        self.assertIn("DRY RUN", result.out)


if __name__ == "__main__":
    unittest.main()
