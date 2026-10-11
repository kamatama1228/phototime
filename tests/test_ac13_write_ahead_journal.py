"""`--apply` が途中で中断されても、それまでの変更を `--undo` で戻せる。

規則は 1 つだけである——**1 file を書き換える前に、その file を復元するために
必要な記録が journal の file に書き出され、disk へ flush されていること**
（write-ahead）。

中断は、**n 件目の書き換えの直前で例外を送出させて**作る。例外は `cli.main`
から外へ出る（＝process が落ちた場合に相当する）。そのとき disk に残っている
journal だけを使って `--undo` し、**全 file の SHA256 と mtime_ns が `--apply`
直前と一致する**ことを確かめる。

seam は `phototime.exifio.write_patches` と `phototime.xmp.render` である。
どちらも「記録の後、変更の直前」に呼ばれる。
"""

import json
import os
import tempfile
import unittest

import support

from phototime import exifio, journal as journal_mod, xmp

EPOCH = 1683170096


class Interrupted(RuntimeError):
    """process が落ちたことの代わり。"""


def _raise_on_nth(module, name, nth, calls=None):
    """`module.name` の n 回目の呼び出しの**直前**で例外を送出させる。

    n-1 回目までは本来の処理を行う。戻り値は、元に戻すための後始末関数。
    """
    original = getattr(module, name)
    counter = {"n": 0}

    def wrapper(*args, **kwargs):
        counter["n"] += 1
        if calls is not None:
            calls.append(args)
        if counter["n"] == nth:
            raise Interrupted("%s の %d 回目で中断した" % (name, nth))
        return original(*args, **kwargs)

    setattr(module, name, wrapper)
    return lambda: setattr(module, name, original)


class JournalVersionWasRaised(unittest.TestCase):
    """形式を変えたので `JOURNAL_VERSION` を上げる。"""

    def test_version_is_above_one(self):
        self.assertGreater(journal_mod.JOURNAL_VERSION, 1)


class InterruptedApplyCanBeUndone(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.journal = os.path.join(self.out.name, "journal.json")

        # EXIF を上書きする file を 5 枚（sidecar の epoch ＝ 瞬間、--shift 明示）。
        self.names = ["IMG_000%d.jpg" % index for index in range(1, 6)]
        for index, name in enumerate(self.names):
            path = os.path.join(self.root, name)
            support.write_jpeg(path)
            support.write_sidecar(path, EPOCH + index)

    def _apply(self, extra=()):
        return support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                "--journal", self.journal] + list(extra))

    def test_apply_changes_something(self):
        """前提の確認。何も変わらないなら、以下の test は無意味になる。"""
        before = support.snapshot(self.root)
        self.assertEqual(self._apply().code, 0)
        self.assertNotEqual(support.snapshot(self.root), before)

    def test_undo_after_interruption_at_each_position(self):
        """1〜5 枚目それぞれの直前で落としても、完全に元へ戻る。"""
        for nth in range(1, 6):
            with self.subTest(nth=nth):
                self.setUp()
                before = support.snapshot(self.root)

                restore = _raise_on_nth(exifio, "write_patches", nth)
                self.addCleanup(restore)
                with self.assertRaises(Interrupted):
                    self._apply()
                restore()

                self.assertTrue(os.path.isfile(self.journal),
                                "中断したのに journal が残っていない")
                undone = support.run_cli(["--undo", self.journal])
                self.assertEqual(undone.code, 0, undone.err)
                self.assertEqual(support.snapshot(self.root), before)

    def test_interruption_leaves_a_changed_file_before_undo(self):
        """3 枚目で落とせば、1〜2 枚目は実際に書き換わっている。

        「中断時点で何も変わっていないから戻せた」のではないことを示す。
        """
        before = support.snapshot(self.root)
        restore = _raise_on_nth(exifio, "write_patches", 3)
        self.addCleanup(restore)
        with self.assertRaises(Interrupted):
            self._apply()
        restore()

        after = support.snapshot(self.root)
        changed = [name for name in before if after[name] != before[name]]
        self.assertEqual(sorted(changed), self.names[:2])

        self.assertEqual(support.run_cli(["--undo", self.journal]).code, 0)
        self.assertEqual(support.snapshot(self.root), before)

    def test_undo_after_interruption_with_rename(self):
        """rename を伴う中断でも、file 名まで含めて元へ戻る。"""
        before = support.snapshot(self.root)
        restore = _raise_on_nth(exifio, "write_patches", 3)
        self.addCleanup(restore)
        with self.assertRaises(Interrupted):
            self._apply(["--rename"])
        restore()

        self.assertEqual(support.run_cli(["--undo", self.journal]).code, 0)
        self.assertEqual(support.snapshot(self.root), before)

    def test_file_count_is_restored(self):
        """中断と undo の後、file の数が元に戻る（余分な file を残さない）。"""
        before = sorted(os.listdir(self.root))
        restore = _raise_on_nth(exifio, "write_patches", 4)
        self.addCleanup(restore)
        with self.assertRaises(Interrupted):
            self._apply()
        restore()

        support.run_cli(["--undo", self.journal])
        self.assertEqual(sorted(os.listdir(self.root)), before)


class JournalIsWrittenBeforeTheChange(unittest.TestCase):
    """順序そのものを見る。記録が先、変更が後。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.journal = os.path.join(self.out.name, "journal.json")
        for index in range(1, 4):
            path = os.path.join(self.root, "IMG_000%d.jpg" % index)
            support.write_jpeg(path)
            support.write_sidecar(path, EPOCH + index)

    def _journal_paths_on_disk(self):
        """いま disk にある journal から、記録済みの path を読む。"""
        if not os.path.exists(self.journal):
            return None
        with open(self.journal, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        found = []
        for line in lines[1:]:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("kind") == "file":
                found.append(record["path"])
        return found

    def test_the_record_is_on_disk_before_the_file_is_written(self):
        observed = []
        original = exifio.write_patches

        def watching(path, originals):
            observed.append((path, self._journal_paths_on_disk()))
            return original(path, originals)

        exifio.write_patches = watching
        self.addCleanup(setattr, exifio, "write_patches", original)
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", self.journal])
        self.assertEqual(result.code, 0, result.err)

        self.assertEqual(len(observed), 3)
        for path, recorded in observed:
            self.assertIsNotNone(recorded,
                                 "書き換えの時点で journal の file が無い")
            self.assertIn(path, recorded,
                          "この file の記録が、書き換えより後になっている")

    def test_journal_exists_before_the_first_change(self):
        """1 件目の書き換えの時点で、journal の file は既にある。"""
        seen = []
        original = exifio.write_patches

        def watching(path, originals):
            seen.append(os.path.exists(self.journal))
            return original(path, originals)

        exifio.write_patches = watching
        self.addCleanup(setattr, exifio, "write_patches", original)
        support.run_cli([self.root, "--shift", "+09:00", "--apply",
                         "--journal", self.journal])
        self.assertEqual(seen, [True, True, True])


class InterruptedSidecarWrite(unittest.TestCase):
    """XMP sidecar の作成と mtime の変更も write-ahead である。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.journal = os.path.join(self.out.name, "journal.json")
        # EXIF に日時 tag が無く、file 名に日時がある ＝ sidecar に逃がす file。
        support.write_jpeg(os.path.join(self.root, "20230504_121456.jpg"),
                           datetime_original=None, offset_time_original=None)
        support.write_jpeg(os.path.join(self.root, "20230505_121456.jpg"),
                           datetime_original=None, offset_time_original=None)

    def test_undo_restores_mtime_when_sidecar_write_is_interrupted(self):
        before = support.snapshot(self.root)
        restore = _raise_on_nth(xmp, "render", 2)
        self.addCleanup(restore)
        with self.assertRaises(Interrupted):
            support.run_cli([self.root, "--apply", "--journal", self.journal])
        restore()

        # 1 枚目は sidecar が作られ、mtime も変わっている。
        self.assertTrue(
            os.path.exists(os.path.join(self.root, "20230504_121456.jpg.xmp")))
        self.assertNotEqual(support.snapshot(self.root), before)

        undone = support.run_cli(["--undo", self.journal])
        self.assertEqual(undone.code, 0, undone.err)
        self.assertEqual(support.snapshot(self.root), before)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "20230504_121456.jpg.xmp")),
            "作った sidecar が残っている")


class TruncatedJournalIsTolerated(unittest.TestCase):
    """落ちた拍子に最後の行が書き切れていなくても、そこまでは戻せる。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.out = tempfile.TemporaryDirectory()
        self.addCleanup(self.out.cleanup)
        self.journal = os.path.join(self.out.name, "journal.json")
        for index in range(1, 4):
            path = os.path.join(self.root, "IMG_000%d.jpg" % index)
            support.write_jpeg(path)
            support.write_sidecar(path, EPOCH + index)

    def test_partial_last_line_does_not_stop_undo(self):
        before = support.snapshot(self.root)
        self.assertEqual(
            support.run_cli([self.root, "--shift", "+09:00", "--apply",
                             "--journal", self.journal]).code, 0)
        with open(self.journal, "a", encoding="utf-8") as handle:
            handle.write('{"kind": "file", "path": "/tmp/x", "patc')

        undone = support.run_cli(["--undo", self.journal])
        self.assertEqual(undone.code, 0, undone.err)
        self.assertIn("Warning", undone.err)
        self.assertEqual(support.snapshot(self.root), before)

    def test_empty_journal_is_refused(self):
        empty = os.path.join(self.out.name, "empty.json")
        support.write_bytes(empty, b"")
        self.assertEqual(support.run_cli(["--undo", empty]).code, 2)


class JournalIsOpenedBeforeAnyChange(unittest.TestCase):
    """journal を作れないなら、file を 1 byte も変えずに中止する。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        path = os.path.join(self.root, "IMG_0001.jpg")
        support.write_jpeg(path)
        support.write_sidecar(path, EPOCH)

    def test_unwritable_journal_aborts_without_touching_files(self):
        before = support.snapshot(self.root)
        missing_dir = os.path.join(tempfile.mkdtemp(), "no-such-dir",
                                   "journal.json")
        result = support.run_cli([self.root, "--shift", "+09:00", "--apply",
                                  "--journal", missing_dir])
        self.assertEqual(result.code, 2, result.err)
        self.assertEqual(support.snapshot(self.root), before)


if __name__ == "__main__":
    unittest.main()
