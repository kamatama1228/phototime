"""`--report` に対象 directory の内側の path を与えたら、中止する。

file を 1 つも作らず、終了 code 2 で終わる。
出力を対象の中に置くと、「既定では対象 directory の file 数が変わらない」が
守れなくなり、次回以降の実行の対象にも入ってしまうため。

`--journal` にも同じ guard をかけている（`--apply` の記録を対象の中に
置かないため）。
"""

import os
import tempfile
import unittest

import support


class OutputPathsStayOutsideTheTarget(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"))

    def test_report_inside_target_is_rejected(self):
        inside = os.path.join(self.root, "report.csv")
        before = support.snapshot(self.root)

        result = support.run_cli([self.root, "--report", inside])

        self.assertEqual(result.code, 2)
        self.assertFalse(os.path.exists(inside))
        self.assertEqual(support.snapshot(self.root), before)

    def test_report_in_a_subdirectory_of_the_target_is_rejected(self):
        subdir = os.path.join(self.root, "out")
        os.makedirs(subdir)
        inside = os.path.join(subdir, "report.csv")

        result = support.run_cli([self.root, "--report", inside])

        self.assertEqual(result.code, 2)
        self.assertFalse(os.path.exists(inside))

    def test_journal_inside_target_is_rejected(self):
        inside = os.path.join(self.root, "journal.json")
        before = support.snapshot(self.root)

        result = support.run_cli([self.root, "--apply", "--shift", "+09:00",
                                  "--journal", inside])

        self.assertEqual(result.code, 2)
        self.assertFalse(os.path.exists(inside))
        self.assertEqual(support.snapshot(self.root), before,
                         "中止したのに file を変更している")

    def test_report_outside_target_is_accepted(self):
        outside = os.path.join(self.out.name, "report.csv")
        result = support.run_cli([self.root, "--report", outside])
        self.assertEqual(result.code, 0, result.err)
        self.assertTrue(os.path.exists(outside))

    def test_target_must_be_a_directory(self):
        result = support.run_cli([os.path.join(self.root, "does-not-exist")])
        self.assertEqual(result.code, 2)


if __name__ == "__main__":
    unittest.main()
