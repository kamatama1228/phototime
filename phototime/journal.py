"""やり直し（`--undo`）のための journal。

`--apply` で行った変更を、元に戻せるだけの情報と一緒に記録する。

**記録は write-ahead である。** **1 件の変更を行う前に、その変更を戻す
ための記録を file へ書き、`flush` と `os.fsync` で disk へ送る。** そのため
`--apply` の途中で process が落ちても、**そこまでに起きた変更は `--undo` で
戻せる。** 順序を逆にしてはいけない。

形式は **1 行 1 JSON**（JSON Lines）である。最初の行が header、以降の行が
entry である。**最後まで書き切れなかった行は、読み込み時に捨てる**
（途中で落ちた場合、その行に対応する変更は、まだ始まっていない）。

記録する entry は 3 種類。**undo は記録と逆順に処理する。**

- `file`   : EXIF の上書き（書き換える前の byte 列）と、元の mtime
- `write`  : 作った／上書きした sidecar（元の内容があれば一緒に）
- `rename` : 変更前後の path

`--undo` の後に、`--apply` の直前の SHA256 と mtime に戻ることを、test が機械的に
確かめる。

> **version 2 で、version 1（単一の JSON object。全 file の処理後に 1 回だけ
> 保存していた）との互換性を切った。** version 1 の journal は、まだ誰も使って
> いない時期にしか存在せず、読む必要がないため。
"""

import base64
import datetime
import json
import os

JOURNAL_VERSION = 2

_ENTRY_KINDS = ("file", "write", "rename")


class Journal:
    """1 回の `--apply` で起きたことの、write-ahead の記録。

    **構築した時点で file を作り、header を disk へ書く。** つまり
    「journal を開けない」場合は、**1 byte も書き換える前に**失敗する。
    """

    def __init__(self, root, path):
        self.root = root
        self.path = path
        self.records = 0
        self._handle = open(path, "w", encoding="utf-8")
        self._emit({
            "tool": "phototime",
            "version": JOURNAL_VERSION,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "root": root,
        })

    def _emit(self, record):
        """1 行書き、disk へ送る。**ここから戻った後でなければ変更を始めない。**"""
        line = json.dumps(record, ensure_ascii=False)
        self._handle.write(line + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self.records += 1

    def record_file(self, path, originals, atime_ns, mtime_ns):
        """EXIF の上書きと、元の時刻を記録する。**上書きする前に呼ぶ。**

        `originals` は `exifio.read_patch_originals` の戻り値
        （[(offset, before, after)]）である。**`before` は、まだ file に
        残っている値である。**

        時刻は **nanosecond 整数**で持つ。float の epoch 秒では桁が足りず、
        `--undo` の後に mtime が元の値と一致しないことがあるため。
        """
        self._emit({
            "kind": "file",
            "path": path,
            "atime_ns": atime_ns,
            "mtime_ns": mtime_ns,
            "patches": [
                {"offset": offset, "before": _b64(before)}
                for offset, before, _after in originals
            ],
        })

    def record_write(self, path, previous_bytes):
        """sidecar の作成（`previous_bytes` が None なら新規作成）。**書く前に呼ぶ。**"""
        self._emit({
            "kind": "write",
            "path": path,
            "existed": previous_bytes is not None,
            "before": _b64(previous_bytes) if previous_bytes is not None else None,
        })

    def record_rename(self, src, dst):
        """**rename する前に呼ぶ。**"""
        self._emit({"kind": "rename", "from": src, "to": dst})

    def close(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def _b64(raw):
    return base64.b64encode(raw).decode("ascii")


class UndoError(Exception):
    pass


def load(path):
    """journal を読む。**書き切れていない末尾の行は捨てる。**

    戻り値は header に `entries`（entry の list）と `incomplete`
    （捨てた行があれば True）を足した dict。
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        raise UndoError("cannot read the journal: %s" % exc)
    except ValueError as exc:
        raise UndoError("the journal is malformed: %s" % exc)

    if not lines:
        raise UndoError("the journal is empty: %s" % path)
    try:
        header = json.loads(lines[0])
    except ValueError as exc:
        raise UndoError("the journal is malformed: %s" % exc)
    if not isinstance(header, dict) or header.get("tool") != "phototime":
        raise UndoError("not a phototime journal: %s" % path)
    if header.get("version") != JOURNAL_VERSION:
        raise UndoError("unsupported journal version: %r"
                        % header.get("version"))

    entries = []
    incomplete = False
    for line in lines[1:]:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            # 書き切れていない行。**その行の変更は、まだ始まっていない**
            # （write-ahead のため）。ここで読むのをやめる。
            incomplete = True
            break
        if not isinstance(record, dict) or record.get("kind") not in _ENTRY_KINDS:
            incomplete = True
            break
        entries.append(record)

    payload = dict(header)
    payload["entries"] = entries
    payload["incomplete"] = incomplete
    return payload


def undo(payload):
    """journal を逆順に適用して元に戻す。戻した件数と、失敗の一覧を返す。"""
    from phototime import exifio

    restored = 0
    failures = []
    for entry in reversed(payload.get("entries", [])):
        kind = entry.get("kind")
        try:
            if kind == "rename":
                if os.path.exists(entry["to"]):
                    os.replace(entry["to"], entry["from"])
            elif kind == "write":
                if entry.get("existed"):
                    with open(entry["path"], "wb") as handle:
                        handle.write(base64.b64decode(entry["before"]))
                elif os.path.exists(entry["path"]):
                    os.remove(entry["path"])
            elif kind == "file":
                patches = [
                    (item["offset"], base64.b64decode(item["before"]))
                    for item in entry.get("patches", [])
                ]
                if patches:
                    exifio.restore_patches(entry["path"], patches)
                mtime_ns = entry.get("mtime_ns")
                if mtime_ns is not None:
                    atime_ns = entry.get("atime_ns", mtime_ns)
                    os.utime(entry["path"], ns=(atime_ns, mtime_ns))
            else:
                failures.append((entry.get("path", "?"),
                                 "unknown entry kind: %r" % kind))
                continue
            restored += 1
        except OSError as exc:
            failures.append((entry.get("path", entry.get("to", "?")), str(exc)))
    return restored, failures
