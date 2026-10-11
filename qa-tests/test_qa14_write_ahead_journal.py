"""`--apply` が途中で中断されても `--undo` で戻せる（QA 側の独立検証）。

**実装側が用意した seam（`exifio.write_patches` / `xmp.render` の n 回目の
呼び出し）は使わない。** それを使うと「実装が write-ahead だと考えている
場所」しか検証できず、別の経路で file が先に変わっていても気づけないためである。

QA は、製品の内部名に依存しない 3 つの境界で中断させる。

- `builtins.open`（対象 directory の内側を、書き込み可能な mode で開くとき）
- `os.utime`（mtime の変更）
- `os.replace`（rename）

**どの経路で file が変わるにせよ、この 3 つのいずれかを必ず通る。**
中断には `Interrupted`（`OSError` でも `JpegError` でもない例外）を使う。
製品は 1 枚ごとの `OSError` を握りつぶして次へ進むため、`OSError` では
「process が落ちた」ことにならないからである。

検証の形:
**中断 → 残った journal で `--undo` → 全 file の SHA256・mtime_ns・file 名の
集合が `--apply` 直前と一致すること。**
"""

import builtins
import json
import os
import tempfile
import unittest

import qasupport as qa


class Interrupted(Exception):
    """中断の合図。製品が握りつぶす例外の型を避けてある。"""


def read_journal_lines(path):
    """journal を disk から読み、**書き切れた行だけ**を JSON にして返す。

    `phototime.journal.load` は使わない（製品の読み取りが甘くても
    気づけるように、QA 側で別に読む）。
    """
    if not os.path.exists(path):
        return []
    with open(path, "rb") as handle:
        raw = handle.read()
    records = []
    for line in raw.split(b"\n"):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            break  # 途中までしか書けていない行。ここで終わり。
        else:
            continue
    return records


def entry_paths(records, kind):
    return {os.path.realpath(item["path"]) for item in records
            if item.get("kind") == kind and "path" in item}


class WriteHook:
    """対象 directory の内側への「書き込みの開始」を捕まえる。

    `builtins.open`（書き込み可能な mode）・`os.utime`・`os.replace` を
    包む。`stop_at` を与えると、その回数目の直前で `Interrupted` を出す。
    `watcher` を与えると、変更が起きる直前に `(種別, path)` で呼ばれる。
    """

    def __init__(self, root, stop_at=None, watcher=None,
                 kinds=("open", "utime", "replace")):
        self.root = os.path.realpath(root)
        self.stop_at = stop_at
        self.watcher = watcher
        self.kinds = kinds
        self.events = []
        self._saved = {}

    def _inside(self, path):
        try:
            target = os.path.realpath(path)
        except (TypeError, ValueError):
            return False
        return (target == self.root
                or target.startswith(self.root + os.sep))

    def _notice(self, kind, path):
        self.events.append((kind, path))
        if self.watcher is not None:
            self.watcher(kind, path)
        if self.stop_at is not None and len(self.events) == self.stop_at:
            raise Interrupted("%d 件目（%s %s）の直前で中断" %
                              (self.stop_at, kind, path))

    def __enter__(self):
        real_open = builtins.open
        real_utime = os.utime
        real_replace = os.replace
        self._saved = {"open": real_open, "utime": real_utime,
                       "replace": real_replace}

        def hooked_open(file, mode="r", *args, **kwargs):
            if ("open" in self.kinds and isinstance(file, (str, bytes, os.PathLike))
                    and any(ch in mode for ch in "wa+")
                    and self._inside(file)):
                self._notice("open", os.fspath(file))
            return real_open(file, mode, *args, **kwargs)

        def hooked_utime(path, *args, **kwargs):
            if "utime" in self.kinds and self._inside(path):
                self._notice("utime", os.fspath(path))
            return real_utime(path, *args, **kwargs)

        def hooked_replace(src, dst, *args, **kwargs):
            if "replace" in self.kinds and self._inside(src):
                self._notice("replace", os.fspath(src))
            return real_replace(src, dst, *args, **kwargs)

        builtins.open = hooked_open
        os.utime = hooked_utime
        os.replace = hooked_replace
        return self

    def __exit__(self, *exc_info):
        builtins.open = self._saved["open"]
        os.utime = self._saved["utime"]
        os.replace = self._saved["replace"]
        return False


class WriteAheadBase(unittest.TestCase):

    PHOTOS = 5

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.TemporaryDirectory()
        self.addCleanup(self.outside.cleanup)
        self.journal = os.path.join(self.outside.name, "undo.jsonl")

    def make_photos(self, count=None, with_tags=True):
        """EXIF の tag を持つ（または持たない）JPEG と JSON sidecar を並べる。"""
        count = self.PHOTOS if count is None else count
        for index in range(count):
            path = os.path.join(self.root, "photo%02d.jpg" % index)
            qa.write(path,
                     qa.plain_jpeg("2001:01:01 00:00:00", "+00:00",
                                   with_datetime=with_tags,
                                   with_offset=with_tags),
                     mtime=1000000000 + index)
            qa.write_sidecar(path, qa.EPOCH_20230504 + index)

    def apply_argv(self, *extra):
        return [self.root, "--shift", "+09:00", "--apply",
                "--journal", self.journal] + list(extra)

    def assert_restored(self, before, note=""):
        after = qa.snapshot(self.root)
        self.assertEqual(sorted(after), sorted(before),
                         "file の集合が元に戻っていない " + note)
        for name in before:
            self.assertEqual(after[name], before[name],
                             "%s が元に戻っていない %s" % (name, note))

    def run_undo(self):
        code, out, err = qa.run_cli(["--undo", self.journal])
        self.assertEqual(code, 0, "--undo が失敗した: %s" % err)
        return out, err


class JournalIsWrittenBeforeTheChange(WriteAheadBase):
    """**記録が先、変更が後**（要求されている規則そのもの）。"""

    def test_journal_file_exists_at_the_first_change(self):
        """最初の書き込みが始まる時点で、journal の file は既にある。

        **以前に記録した欠陥（journal は最後に 1 回だけ保存される）が、
        無くなったことの確認である。** 当時の観測は、ここが False だった。
        """
        self.make_photos()
        seen = []

        def watcher(_kind, _path):
            seen.append(os.path.exists(self.journal))

        with WriteHook(self.root, watcher=watcher):
            code, _out, _err = qa.run_cli(self.apply_argv())
        self.assertEqual(code, 0)
        self.assertTrue(seen, "変更が 1 件も起きていない（test が無意味）")
        self.assertTrue(all(seen),
                        "journal が存在しないまま file を変えている: %r" % seen)

    def test_each_record_is_on_disk_before_its_change(self):
        """1 枚を変える前に、**その 1 枚の記録が disk に載っている。**

        変更の直前に、QA 側で journal を読み直して確かめる。
        """
        self.make_photos()
        missing = []

        def watcher(kind, path):
            records = read_journal_lines(self.journal)
            target = os.path.realpath(path)
            if path.endswith(".xmp"):
                ok = target in entry_paths(records, "write")
            else:
                ok = target in entry_paths(records, "file")
            if not ok:
                missing.append((kind, path))

        with WriteHook(self.root, watcher=watcher) as hook:
            code, _out, _err = qa.run_cli(self.apply_argv())
        self.assertEqual(code, 0)
        self.assertGreaterEqual(len(hook.events), self.PHOTOS,
                                "変更の回数が少なすぎる: %r" % hook.events)
        self.assertEqual(missing, [],
                         "記録より先に file を変えている: %r" % missing)

    def test_rename_is_recorded_before_it_happens(self):
        """rename も「記録してから動かす」。"""
        self.make_photos(count=2)
        missing = []

        def watcher(kind, path):
            if kind != "replace":
                return
            records = read_journal_lines(self.journal)
            froms = {os.path.realpath(item["from"]) for item in records
                     if item.get("kind") == "rename"}
            if os.path.realpath(path) not in froms:
                missing.append(path)

        with WriteHook(self.root, watcher=watcher) as hook:
            code, _out, _err = qa.run_cli(self.apply_argv("--rename"))
        self.assertEqual(code, 0)
        self.assertTrue([e for e in hook.events if e[0] == "replace"],
                        "rename が 1 件も起きていない（test が無意味）")
        self.assertEqual(missing, [], "記録より先に rename している: %r" % missing)

    def test_sidecar_is_recorded_before_it_is_written(self):
        """tag の無い JPEG（XMP sidecar に逃げる経路）でも順序は同じ。"""
        self.make_photos(count=3, with_tags=False)
        missing = []

        def watcher(_kind, path):
            if not path.endswith(".xmp"):
                return
            records = read_journal_lines(self.journal)
            if os.path.realpath(path) not in entry_paths(records, "write"):
                missing.append(path)

        with WriteHook(self.root, watcher=watcher) as hook:
            code, _out, _err = qa.run_cli(self.apply_argv())
        self.assertEqual(code, 0)
        self.assertTrue([e for e in hook.events if e[1].endswith(".xmp")],
                        "sidecar が 1 件も書かれていない（test が無意味）")
        self.assertEqual(missing, [], "記録より先に sidecar を書いている: %r" % missing)

    def test_each_record_is_fsynced_before_its_change(self):
        """要求の後半: 記録は **disk へ送られて**いること。

        `os.fsync` を数え、**変更が 1 件起きるたびに、その前に新しい
        `fsync` が 1 回以上あった**ことを確かめる。file system や drive の
        cache の先までは検証していない。
        """
        self.make_photos()
        real_fsync = os.fsync
        synced = []
        shortfalls = []

        def counting_fsync(fd):
            synced.append(fd)
            return real_fsync(fd)

        def watcher(kind, path):
            # disk に見えている記録の数より、fsync の回数が少なければ、
            # 「書いたが disk へ送っていない」記録がある。
            on_disk = len(read_journal_lines(self.journal))
            if not synced or len(synced) < on_disk:
                shortfalls.append((kind, path, len(synced), on_disk))

        os.fsync = counting_fsync
        self.addCleanup(setattr, os, "fsync", real_fsync)
        with WriteHook(self.root, watcher=watcher) as hook:
            code, _out, _err = qa.run_cli(self.apply_argv())
        self.assertEqual(code, 0)
        self.assertTrue(hook.events, "変更が 1 件も起きていない（test が無意味）")
        self.assertEqual(shortfalls, [],
                         "disk へ送っていない記録のまま file を変えている: %r"
                         % shortfalls)

    def test_journal_version_was_raised(self):
        """journal の header の version が 1 より大きい（形式を変えたため）。"""
        self.make_photos(count=1)
        code, _out, _err = qa.run_cli(self.apply_argv())
        self.assertEqual(code, 0)
        records = read_journal_lines(self.journal)
        self.assertTrue(records, "journal が空")
        header = records[0]
        self.assertEqual(header.get("tool"), "phototime")
        self.assertIsInstance(header.get("version"), int)
        self.assertGreater(header["version"], 1,
                           "JOURNAL_VERSION が上がっていない")


class UndoAfterInterruption(WriteAheadBase):
    """**中断 → `--undo` → 完全に元どおり**。"""

    def test_interruption_really_changes_files_first(self):
        """前提の確認: 中断の時点で、既に変わった file がある。

        **これが無いと、以下の「戻せた」は何も検証していないことになる。**
        """
        self.make_photos()
        before = qa.snapshot(self.root)
        with WriteHook(self.root, stop_at=4):
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv())
        self.assertNotEqual(qa.snapshot(self.root), before,
                            "中断しても file が 1 つも変わっていない")

    def test_undo_restores_everything_at_each_interruption_point(self):
        """1 件目から順に、どの変更の直前で落ちても完全に戻る。"""
        for stop_at in range(1, self.PHOTOS * 2 + 1):
            with self.subTest(stop_at=stop_at):
                self.setUp()
                self.make_photos()
                before = qa.snapshot(self.root)
                with WriteHook(self.root, stop_at=stop_at) as hook:
                    try:
                        qa.run_cli(self.apply_argv())
                    except Interrupted:
                        pass
                    else:
                        if len(hook.events) < stop_at:
                            self.skipTest("変更の回数が %d 未満" % stop_at)
                self.run_undo()
                self.assert_restored(before, "(stop_at=%d)" % stop_at)

    def test_undo_restores_everything_when_rename_is_interrupted(self):
        """rename の途中で落ちても、file 名まで含めて戻る。"""
        self.make_photos()
        before = qa.snapshot(self.root)
        with WriteHook(self.root, stop_at=6):
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv("--rename"))
        self.run_undo()
        self.assert_restored(before)

    def test_undo_restores_everything_when_mtime_is_interrupted(self):
        """`os.utime` の直前（＝EXIF を書いた直後）で落ちても戻る。"""
        self.make_photos()
        before = qa.snapshot(self.root)
        with WriteHook(self.root, stop_at=2, kinds=("utime",)):
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv())
        self.run_undo()
        self.assert_restored(before)

    def test_undo_removes_sidecars_created_before_interruption(self):
        """中断前に作られた sidecar も消え、余分な file が残らない。"""
        self.make_photos(with_tags=False)
        before = qa.snapshot(self.root)
        with WriteHook(self.root, stop_at=3) as hook:
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv())
        self.assertTrue([e for e in hook.events if e[1].endswith(".xmp")],
                        "sidecar が 1 件も作られていない（test が無意味）")
        self.run_undo()
        self.assert_restored(before)

    def test_undo_works_on_the_journal_as_it_was_at_the_moment_of_interruption(self):
        """**close される前の journal の中身だけで戻せる。**

        中断の瞬間に journal を別 path へ写し取り、その写しで `--undo` する。
        `--apply` の process が `close()` に辿り着かずに死んだ場合に当たる。
        """
        self.make_photos()
        before = qa.snapshot(self.root)
        copy_path = os.path.join(self.outside.name, "snapshot.jsonl")
        captured = {}

        def watcher(_kind, _path):
            if os.path.exists(self.journal):
                with open(self.journal, "rb") as handle:
                    captured["raw"] = handle.read()

        with WriteHook(self.root, stop_at=4, watcher=watcher):
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv())

        self.assertIn("raw", captured, "journal を写し取れていない")
        with open(copy_path, "wb") as handle:
            handle.write(captured["raw"])
        code, _out, _err = qa.run_cli(["--undo", copy_path])
        self.assertEqual(code, 0)
        self.assert_restored(before, "(close 前の journal の写し)")

    def test_undo_tolerates_a_torn_last_line(self):
        """最後の行が途中までしか書けていなくても、そこまでは戻せる。

        **write-ahead なので、書き切れなかった記録に対応する変更は、まだ
        起きていない。** その行を捨てても戻せなければならない。

        中断点は **3 枚目の最初の変更の直前**に取る（`kinds=("open",)`）。
        **最後の行は 3 枚目の記録であり、3 枚目はまだ 1 byte も変わって
        いない。** ここを切り落とすのが、torn write に当たる。
        """
        self.make_photos()
        before = qa.snapshot(self.root)
        with WriteHook(self.root, stop_at=3, kinds=("open",)):
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv())

        with open(self.journal, "rb") as handle:
            raw = handle.read()
        torn = raw[:-1] if raw.endswith(b"\n") else raw
        cut = torn[: len(torn) - max(1, len(torn.split(b"\n")[-1]) // 2)]
        with open(self.journal, "wb") as handle:
            handle.write(cut)

        _out, err = self.run_undo()
        # 出力は英語になった。語ではなく「警告として、途中までしか記録が
        # 無いことを述べていること」で確かめる。
        low = err.lower()
        self.assertIn("warning", low,
                      "途中で終わった journal の警告が出ていない: %r" % (err,))
        self.assertIn("journal", low,
                      "警告が journal について述べていない: %r" % (err,))
        self.assert_restored(before, "(末尾が欠けた journal)")


class LateJournal:
    """**わざと write-ahead を壊した journal**（negative control 専用）。

    `record_*` は、その場では書かず、**次の `record_*` が来たとき**に書く。
    ＝「変更してから記録する」実装に相当する。**製品の code は変更しない。**
    `runner.new_journal` を test の中だけ差し替えて使う。
    """

    def __init__(self, inner):
        self._inner = inner
        self._pending = None
        self.path = inner.path

    def _later(self, name, args):
        if self._pending is not None:
            method, pending_args = self._pending
            getattr(self._inner, method)(*pending_args)
        self._pending = (name, args)

    def record_file(self, *args):
        self._later("record_file", args)

    def record_write(self, *args):
        self._later("record_write", args)

    def record_rename(self, *args):
        self._later("record_rename", args)

    def close(self):
        if self._pending is not None:
            method, args = self._pending
            getattr(self._inner, method)(*args)
            self._pending = None
        self._inner.close()


class NegativeControl(WriteAheadBase):
    """**この file の test に歯があることの確認。**

    記録の順序を 1 件ぶん遅らせただけで、上の検証が落ちることを示す。
    落ちなければ、上の test が通ったことには意味が無い。
    """

    def setUp(self):
        super().setUp()
        from phototime import runner

        real_new_journal = runner.new_journal
        runner.new_journal = lambda root, path: LateJournal(
            real_new_journal(root, path))
        self.addCleanup(setattr, runner, "new_journal", real_new_journal)

    def test_ordering_check_catches_a_late_record(self):
        self.make_photos()
        missing = []

        def watcher(kind, path):
            records = read_journal_lines(self.journal)
            if os.path.realpath(path) not in entry_paths(records, "file"):
                missing.append((kind, path))

        with WriteHook(self.root, watcher=watcher, kinds=("open",)):
            qa.run_cli(self.apply_argv())
        self.assertNotEqual(missing, [],
                            "順序の検証が、遅れた記録を見逃している")

    def test_undo_check_catches_a_late_record(self):
        """**中断の瞬間の journal** で見ると、遅れた記録は戻せない。

        `cli.main` は `finally` で `journal.close()` を呼ぶため、**この Run の
        中で中断を模しただけでは、遅れた記録もそこで書き出されてしまう。**
        process が本当に死ねば `close()` は走らない。そのため、中断の瞬間に
        写し取った journal で確かめる（守るべき場面はこちらである）。
        """
        self.make_photos()
        before = qa.snapshot(self.root)
        captured = {}

        def watcher(_kind, _path):
            if os.path.exists(self.journal):
                with open(self.journal, "rb") as handle:
                    captured["raw"] = handle.read()

        # 1 件目を書き換えた**直後**（mtime を変える直前）で落とす。
        # 記録が遅れていれば、この瞬間の journal には 1 枚目が入っていない。
        with WriteHook(self.root, stop_at=2, watcher=watcher,
                       kinds=("open", "utime")):
            with self.assertRaises(Interrupted):
                qa.run_cli(self.apply_argv())

        copy_path = os.path.join(self.outside.name, "crash.jsonl")
        with open(copy_path, "wb") as handle:
            handle.write(captured.get("raw", b""))
        qa.run_cli(["--undo", copy_path])
        self.assertNotEqual(qa.snapshot(self.root), before,
                            "復元の検証が、戻せない状態を見逃している")


class JournalFailureDoesNotTouchFiles(WriteAheadBase):
    """journal を開けないなら、**1 byte も変えずに**中止する。"""

    def test_unopenable_journal_aborts_before_any_change(self):
        self.make_photos()
        before = qa.snapshot(self.root)
        self.journal = os.path.join(self.outside.name, "no-such-dir", "u.jsonl")
        with WriteHook(self.root) as hook:
            code, _out, err = qa.run_cli(self.apply_argv())
        self.assertEqual(code, 2, "中止していない: %s" % err)
        self.assertEqual(hook.events, [], "中止と言いながら file に触れている")
        self.assert_restored(before)


if __name__ == "__main__":
    unittest.main()
