"""利用者に見える出力が、すべて英語である。

README も、repository の topics も、この tool を見つけてもらう唯一の経路も
英語である。それなのに `--help`・中止の message・警告・`DRY RUN:` の行・
集計行が日本語だと、**英語の README を読んで `--help` を叩いた人が、最初に
受け取るのは日本語の画面になる。**

ここで確かめるのは**文言だけ**である。**option 名、CSV の列名、`action` と
`reason` の値、終了 code は 1 つも変わっていない**（それらは他の test が
そのまま確かめ続けている）。

comment と docstring は対象外である。利用者には見えないため。
"""

import os
import re
import tempfile
import unittest
from unittest import mock

import support

from phototime import cli, tzpolicy

EPOCH = 1683170096

# ひらがな・カタカナ・漢字と、全角の約物。
_JAPANESE = re.compile(
    "[　-〿぀-ゟ゠-ヿ一-鿿＀-￯]")


def _japanese_in(text):
    """見つかった日本語の文字を、重複なく並びを保って返す。"""
    seen = []
    for char in _JAPANESE.findall(text):
        if char not in seen:
            seen.append(char)
    return seen


class HelpIsEnglish(unittest.TestCase):
    """test 1: `--help` の全文に日本語が 1 文字も無い。"""

    def setUp(self):
        self.help_text = cli.build_parser().format_help()

    def test_help_has_no_japanese_characters(self):
        self.assertEqual(_japanese_in(self.help_text), [],
                         "--help に日本語が残っている")

    def test_help_still_lists_every_option(self):
        """文言を英語にしただけで、option 名を 1 つも落としていないこと。"""
        for option in ("--apply", "--dry-run", "--report", "--shift",
                       "--assume-tz", "--recursive", "--no-xmp", "--no-mtime",
                       "--rename", "--journal", "--undo", "--version"):
            self.assertIn(option, self.help_text)

    def test_help_still_states_that_offsets_are_not_guessed(self):
        """英語になっても、推定しないという事実を述べていること。"""
        lowered = self.help_text.lower()
        self.assertIn("never guessed", lowered)
        self.assertIn("dry run", lowered)


class AbortMessagesAreEnglish(unittest.TestCase):
    """test 2: 中止する 4 つの経路で、標準エラーに日本語が無い。

    **終了 code は変えない。** どれも 2 のままであることを、同じ test で確かめる。
    """

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

    def _assert_aborted_in_english(self, result):
        self.assertEqual(result.code, 2, result.err)
        self.assertEqual(_japanese_in(result.err), [],
                         "中止の message に日本語が残っている: %r" % result.err)
        self.assertIn("Aborted:", result.err)

    def test_malformed_shift(self):
        # 与える値も ASCII にしておく。日本語の値を渡すと、message がそれを
        # そのまま echo して、test が自分の入力を検出してしまう。
        result = support.run_cli([self.root, "--shift", "9h"])
        self._assert_aborted_in_english(result)
        self.assertIn("--shift", result.err)

    def test_unresolvable_assume_tz(self):
        def boom(name):
            raise tzpolicy.ZoneInfoNotFoundError(name)

        with mock.patch.object(tzpolicy, "load_timezone", boom):
            result = support.run_cli([self.root, "--assume-tz", "Asia/Tokyo"])
        self._assert_aborted_in_english(result)
        self.assertIn("--shift", result.err)

    def test_report_inside_the_target_directory(self):
        inside = os.path.join(self.root, "report.csv")
        result = support.run_cli([self.root, "--report", inside])
        self._assert_aborted_in_english(result)
        self.assertFalse(os.path.exists(inside))

    def test_journal_cannot_be_created(self):
        missing = os.path.join(self.out.name, "no-such-dir", "journal.json")
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", missing])
        self._assert_aborted_in_english(result)
        self.assertEqual(support.snapshot(self.root), before)

    def test_journal_inside_the_target_directory(self):
        inside = os.path.join(self.root, "journal.json")
        before = support.snapshot(self.root)
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", inside])
        self._assert_aborted_in_english(result)
        self.assertEqual(support.snapshot(self.root), before)

    def test_apply_and_dry_run_together(self):
        self._assert_aborted_in_english(
            support.run_cli([self.root, "--apply", "--dry-run"]))

    def test_shift_and_assume_tz_together(self):
        self._assert_aborted_in_english(
            support.run_cli([self.root, "--shift", "+09:00",
                             "--assume-tz", "Asia/Tokyo"]))

    def test_missing_directory_argument(self):
        self._assert_aborted_in_english(support.run_cli([]))

    def test_not_a_directory(self):
        self._assert_aborted_in_english(support.run_cli([self.jpeg]))

    def test_unreadable_journal_for_undo(self):
        missing = os.path.join(self.out.name, "no-such-journal.json")
        self._assert_aborted_in_english(support.run_cli(["--undo", missing]))


class MissingTagWarningIsEnglish(unittest.TestCase):
    """test 3: tag が無い JPEG への警告が英語で、かつ同じ事実を述べている。

    **述べるべき事実は 2 つである**——**tag を追加しないこと**と、
    **XMP sidecar に書くこと**。文言が英語になっても、どちらも落とさない。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.jpeg = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(self.jpeg, datetime_original=None,
                           offset_time_original=None)
        support.write_sidecar(self.jpeg, EPOCH)
        self.journal = os.path.join(self.out.name, "journal.json")

    def test_warning_is_english_and_keeps_both_facts(self):
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.err), [],
                         "警告に日本語が残っている: %r" % result.err)
        self.assertIn("does not add tags", result.err)
        self.assertIn("XMP sidecar", result.err)
        self.assertIn("DateTimeOriginal", result.err)
        self.assertTrue(os.path.exists(self.jpeg + ".xmp"))

    def test_offset_warning_is_english_too(self):
        """日時 tag はあるが offset tag が無い file の警告も、英語である。"""
        other_root = tempfile.TemporaryDirectory()
        self.addCleanup(other_root.cleanup)
        path = os.path.join(other_root.name, "IMG_0002.jpg")
        support.write_bytes(path, support.jpeg_bytes(
            datetime_original="2023:05:04 12:14:56",
            offset_time_original=None))
        journal = os.path.join(self.out.name, "journal2.json")

        result = support.run_cli([other_root.name, "--shift", "+09:00",
                                  "--apply", "--journal", journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.err), [])
        self.assertIn("OffsetTimeOriginal", result.err)
        self.assertIn("does not add tags", result.err)


class DryRunOutputIsEnglish(unittest.TestCase):
    """test 4: 既定の実行（dry-run）の標準出力の全文に日本語が無い。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        # 1 枚ごとに違う経路を通る 4 枚を置く。集計行と表の両方を広く通す。
        self.with_sidecar = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(self.with_sidecar)
        support.write_sidecar(self.with_sidecar, EPOCH)

        self.no_tag = os.path.join(self.root, "20230504_121456.jpg")
        support.write_jpeg(self.no_tag, datetime_original=None,
                           offset_time_original=None)

        self.broken = os.path.join(self.root, "broken.jpg")
        support.write_bytes(self.broken, b"\xff\xd8not-a-jpeg")

        self.two_exif = os.path.join(self.root, "two_exif.jpg")
        support.write_bytes(self.two_exif, support.jpeg_bytes(app1_count=2))

    def test_dry_run_stdout_has_no_japanese(self):
        result = support.run_cli([self.root])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.out), [],
                         "dry-run の標準出力に日本語が残っている: %r" % result.out)

    def test_dry_run_stderr_has_no_japanese(self):
        result = support.run_cli([self.root])
        self.assertEqual(_japanese_in(result.err), [],
                         "dry-run の標準エラーに日本語が残っている: %r" % result.err)

    def test_dry_run_still_announces_itself_and_the_summary(self):
        """英語にしても、「変更しない」ことと件数を述べ続けていること。"""
        result = support.run_cli([self.root])
        self.assertIn("DRY RUN", result.out)
        self.assertIn("4 files", result.out)

    def test_reason_and_action_values_are_unchanged(self):
        """**文言だけを英語にした。** reason と action の値は変えていない。"""
        report_path = os.path.join(self.out.name, "report.csv")
        result = support.run_cli([self.root, "--report", report_path])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.out), [])
        header, rows = support.read_csv(report_path)
        self.assertEqual(header, [
            "path", "source", "source_kind", "before_datetime",
            "after_datetime", "before_offset", "after_offset", "action",
            "reason"])
        reasons = {row[8] for row in rows}
        self.assertIn("offset_required", reasons)
        self.assertIn("unsupported_structure", reasons)


class ApplyAndUndoOutputIsEnglish(unittest.TestCase):
    """`--apply` と `--undo` の出力にも日本語が無い。"""

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

    def test_apply_output_has_no_japanese(self):
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.out), [],
                         "--apply の標準出力に日本語が残っている: %r" % result.out)
        self.assertEqual(_japanese_in(result.err), [])
        self.assertIn("--undo", result.out)

    def test_undo_output_has_no_japanese(self):
        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])
        result = support.run_cli(["--undo", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.out), [],
                         "--undo の標準出力に日本語が残っている: %r" % result.out)
        self.assertEqual(_japanese_in(result.err), [])
        self.assertIn("Reverted", result.out)

    def test_incomplete_journal_warning_has_no_japanese(self):
        before = support.snapshot(self.root)
        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])
        with open(self.journal, "a", encoding="utf-8") as handle:
            handle.write('{"kind": "file", "path": "/tmp/x", "patc')
        result = support.run_cli(["--undo", self.journal])
        self.assertEqual(result.code, 0, result.err)
        self.assertEqual(_japanese_in(result.err), [],
                         "途中で終わった journal の警告に日本語が残っている")
        self.assertIn("Warning", result.err)
        self.assertEqual(support.snapshot(self.root), before)


class TheDetectorItselfWorks(unittest.TestCase):
    """**日本語の検出そのものが空振りでないこと**を先に確かめる。

    これが無いと、上の test は「何も検出できない正規表現」でも全部通る。
    """

    def test_it_finds_each_kind_of_japanese_character(self):
        for sample in ("ひらがな", "カタカナ", "漢字", "です。", "（例）"):
            self.assertNotEqual(_japanese_in(sample), [], sample)

    def test_it_passes_ascii_and_the_characters_the_tool_actually_prints(self):
        for sample in ("DRY RUN: no file is changed (pass --apply to write)",
                       "Aborted: not a directory: /tmp/x",
                       "4 files / skipped 2 / would_update 1",
                       "+09:00", "2023:05:04 12:14:56", "IMG_0001.jpg"):
            self.assertEqual(_japanese_in(sample), [], sample)


if __name__ == "__main__":
    unittest.main()
