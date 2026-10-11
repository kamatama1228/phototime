"""--report に対象 directory の内側を指定したら、何も作らず終了 code 2。

あわせて、実装が安全策として足した `--journal` 側の同じ guard も確かめる
（要求されてはいないが、記録のために検証する）。
"""

import os
import tempfile
import unittest

import qasupport as qa


class OutputPathGuard(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()

        photo = os.path.join(self.root, "photo.jpg")
        qa.write(photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(photo, qa.EPOCH_20230504)
        os.makedirs(os.path.join(self.root, "sub"))
        self.before = qa.snapshot(self.root)

    def assert_aborted(self, argv):
        code, out, err = qa.run_cli(argv)
        self.assertEqual(code, 2, "終了 code 2 で中止するはず: %r" % (argv,))
        self.assertEqual(qa.snapshot(self.root), self.before,
                         "中止したのに対象 directory が変わった: %r" % (argv,))
        # 出力は英語になった。語ではなく「中止したと述べていること」で確かめる。
        self.assertIn("aborted", err.lower(),
                      "中止したことが標準エラーに出ていない: %r" % (err,))
        return out, err

    def test_report_directly_inside_target(self):
        self.assert_aborted([self.root, "--report",
                             os.path.join(self.root, "plan.csv")])

    def test_report_in_subdirectory_of_target(self):
        self.assert_aborted([self.root, "--report",
                             os.path.join(self.root, "sub", "plan.csv")])

    def test_report_reaching_inside_via_relative_path(self):
        """`..` を含む path でも、対象の内側なら中止する。"""
        sneaky = os.path.join(self.root, "sub", "..", "plan.csv")
        self.assert_aborted([self.root, "--report", sneaky])

    def test_report_guard_applies_with_apply_too(self):
        self.assert_aborted(
            [self.root, "--shift", "+09:00", "--apply",
             "--journal", os.path.join(self.outside, "undo.json"),
             "--report", os.path.join(self.root, "plan.csv")])

    def test_report_outside_target_is_allowed(self):
        outside_report = os.path.join(self.outside, "plan.csv")
        code, _out, _err = qa.run_cli([self.root, "--report", outside_report])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(outside_report))
        self.assertEqual(qa.snapshot(self.root), self.before,
                         "既定の実行で対象 directory に file が増えた")

    def test_journal_inside_target_is_also_refused(self):
        """実装が足した追加の guard（要求されてはいない）。"""
        self.assert_aborted(
            [self.root, "--shift", "+09:00", "--apply",
             "--journal", os.path.join(self.root, "undo.json")])

    def test_target_must_be_a_directory(self):
        code, _out, _err = qa.run_cli([os.path.join(self.root, "photo.jpg")])
        self.assertEqual(code, 2)

    def test_missing_directory_is_refused(self):
        code, _out, _err = qa.run_cli([os.path.join(self.outside, "nope")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
