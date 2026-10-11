"""CSV の列が固定である（名前・順序・列数）。"""

import os
import tempfile
import unittest

import qasupport as qa

EXPECTED = [
    "path", "source", "source_kind", "before_datetime", "after_datetime",
    "before_offset", "after_offset", "action", "reason",
]


class CsvColumns(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.report = os.path.join(self.outside, "plan.csv")

        good = os.path.join(self.root, "good.jpg")
        qa.write(good, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(good, qa.EPOCH_20230504)
        qa.write(os.path.join(self.root, "20230504_123456.jpg"),
                 qa.plain_jpeg(with_datetime=False, with_offset=False),
                 mtime=1000000001)
        qa.write(os.path.join(self.root, "empty.jpg"), b"", mtime=1000000002)

    def _header_and_rows(self, *extra):
        code, _out, _err = qa.run_cli(
            [self.root, "--report", self.report] + list(extra))
        self.assertEqual(code, 0)
        rows = qa.read_csv_rows(self.report)
        return rows[0], rows[1:]

    def test_header_is_exact(self):
        header, _rows = self._header_and_rows()
        self.assertEqual(header, EXPECTED)

    def test_header_is_the_same_with_apply(self):
        journal = os.path.join(self.outside, "undo.json")
        header, _rows = self._header_and_rows(
            "--shift", "+09:00", "--apply", "--journal", journal)
        self.assertEqual(header, EXPECTED)

    def test_every_row_has_the_same_width(self):
        header, rows = self._header_and_rows("--shift", "+09:00")
        self.assertEqual(len(rows), 3, "対象 file の数だけ行があるはず")
        for row in rows:
            self.assertEqual(len(row), len(EXPECTED), row)

    def test_source_kind_is_always_one_of_three(self):
        """`source_kind` は instant / wallclock / 空（扱えない file）のみ。"""
        _header, rows = self._header_and_rows("--shift", "+09:00")
        index = EXPECTED.index("source_kind")
        for row in rows:
            self.assertIn(row[index], ("instant", "wallclock", ""), row)

    def test_source_kind_is_present_for_every_processed_file(self):
        """扱えた file には必ず種別が出る（区別が出力に現れること）。"""
        _header, rows = self._header_and_rows("--shift", "+09:00")
        kind = EXPECTED.index("source_kind")
        action = EXPECTED.index("action")
        for row in rows:
            if row[action] == "skipped" and row[kind] == "":
                continue  # 読めなかった file
            self.assertIn(row[kind], ("instant", "wallclock"), row)

    def test_dry_run_does_not_write_csv_without_report(self):
        code, _out, _err = qa.run_cli([self.root])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(self.report))

    def test_stdout_table_contains_kind_column(self):
        code, out, _err = qa.run_cli([self.root, "--shift", "+09:00"])
        self.assertEqual(code, 0)
        self.assertIn("kind", out.splitlines()[1])


if __name__ == "__main__":
    unittest.main()
