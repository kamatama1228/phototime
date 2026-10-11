"""CSV の列が固定である。

`path, source, source_kind, before_datetime, after_datetime, before_offset,
after_offset, action, reason`

`source_kind`（`instant` / `wallclock`）は、**この列が出力に現れない限り、
利用者も「瞬間と壁時計の取り違え」を見つけられない**ために置いてある。
列名も順序も変えてはいけない。
"""

import os
import tempfile
import unittest

import support

EXPECTED_COLUMNS = [
    "path",
    "source",
    "source_kind",
    "before_datetime",
    "after_datetime",
    "before_offset",
    "after_offset",
    "action",
    "reason",
]


class CsvColumnsAreFixed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.report = os.path.join(self.out.name, "report.csv")

        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"))
        support.write_bytes(os.path.join(self.root, "notes.txt"), b"x")

    def test_header_matches_exactly(self):
        result = support.run_cli([self.root, "--report", self.report])
        self.assertEqual(result.code, 0, result.err)
        header, rows = support.read_csv(self.report)
        self.assertEqual(header, EXPECTED_COLUMNS)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row), len(EXPECTED_COLUMNS))

    def test_source_kind_is_always_one_of_the_two_or_empty(self):
        support.run_cli([self.root, "--report", self.report])
        header, rows = support.read_csv(self.report)
        index = header.index("source_kind")
        for row in rows:
            self.assertIn(row[index], ("instant", "wallclock", ""))

    def test_csv_is_not_written_without_the_report_option(self):
        result = support.run_cli([self.root])
        self.assertEqual(result.code, 0, result.err)
        self.assertFalse(os.path.exists(self.report))


if __name__ == "__main__":
    unittest.main()
