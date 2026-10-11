"""日時の情報源と、その **種別** を決める。

情報源を「瞬間」と「壁時計」に分けることが、この module の存在理由である。

| 情報源 | 種別 | 足りないもの |
|---|---|---|
| (a) 同名の JSON sidecar の epoch 秒 | instant（瞬間） | 現地のオフセット |
| (b) file 名の日時 | wallclock（壁時計） | その瞬間がいつか |
| (c) 既存の EXIF DateTimeOriginal | wallclock（壁時計） | 同上 |
| (d) file の mtime | instant（瞬間） | 現地のオフセット |

優先順は (a) → (b) → (c) → (d)。
**この 2 種別を混ぜて実装すると、`--apply` が全 file を利用者のオフセット分だけ
静かにずらす。** そのため、種別は値と必ず一緒に持ち回り、CSV にも出す。
"""

import datetime
import json
import os
import re

KIND_INSTANT = "instant"
KIND_WALLCLOCK = "wallclock"

SOURCE_JSON_SIDECAR = "json_sidecar"
SOURCE_FILENAME = "filename"
SOURCE_EXIF = "exif"
SOURCE_MTIME = "mtime"

# 壁時計を EXIF に書くときの書式。
EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"

_MIN_YEAR = 1970
_MAX_YEAR = 2099

# file 名から日時を読み取る pattern。曖昧な形（数字の羅列だけ）は入れない。
_FILENAME_PATTERNS = (
    # 20230504_123456 / IMG_20230504_123456 / PXL_20230504_123456789
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_\-](\d{2})(\d{2})(\d{2})(?!\d)"),
    # 2023-05-04_12-34-56 / 2023-05-04 12.34.56 / 2023-05-04T12:34:56
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[ _T]"
               r"(\d{2})[\-.:](\d{2})[\-.:](\d{2})(?!\d)"),
    # Signal-2023-05-04-123456
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})(?!\d)"),
)

# JSON sidecar の中で epoch 秒が入っている場所。先に見つかったものを使う。
_JSON_EPOCH_PATHS = (
    ("photoTakenTime", "timestamp"),
    ("creationTime", "timestamp"),
    ("photoLastModifiedTime", "timestamp"),
)


class Resolved:
    """1 枚について決まった「日時の素」。まだ EXIF に書く値ではない。"""

    def __init__(self, source, kind, instant=None, wallclock=None):
        self.source = source
        self.kind = kind
        # kind == instant のとき: tz を持たない「UTC の瞬間」を表す epoch 秒
        self.instant = instant
        # kind == wallclock のとき: tz を持たない naive な datetime
        self.wallclock = wallclock


def _valid_datetime(year, month, day, hour, minute, second):
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return None
    try:
        return datetime.datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def sidecar_candidates(path):
    """JSON sidecar として探す path を、優先順に返す。"""
    base, _ext = os.path.splitext(path)
    return (path + ".json", base + ".json")


def _dig(obj, keys):
    for key in keys:
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


def read_json_sidecar_epoch(path):
    """同名の JSON sidecar から epoch 秒を読む。無ければ None。"""
    for candidate in sidecar_candidates(path):
        if not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, UnicodeDecodeError):
            # 壊れた sidecar は「無い」ものとして扱う。例外で止めない。
            continue
        for keys in _JSON_EPOCH_PATHS:
            raw = _dig(payload, keys)
            if raw is None:
                continue
            try:
                epoch = int(str(raw).strip())
            except (TypeError, ValueError):
                continue
            if _is_plausible_epoch(epoch):
                return epoch
    return None


def _is_plausible_epoch(epoch):
    try:
        moment = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return False
    return _MIN_YEAR <= moment.year <= _MAX_YEAR


def read_filename_datetime(path):
    """file 名から壁時計の日時を読む。読めなければ None。"""
    name = os.path.basename(path)
    for pattern in _FILENAME_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        parsed = _valid_datetime(*(int(part) for part in match.groups()))
        if parsed is not None:
            return parsed
    return None


def parse_exif_datetime(text):
    """EXIF の "YYYY:MM:DD HH:MM:SS" を naive な datetime にする。"""
    if not text:
        return None
    try:
        return datetime.datetime.strptime(text.strip(), EXIF_DATETIME_FORMAT)
    except ValueError:
        return None


def resolve(path, exif_datetime_text, stat_result):
    """優先順 (a) → (b) → (c) → (d) で情報源を 1 つ選ぶ。

    mtime は必ず存在するため、戻り値が None になることはない。
    """
    epoch = read_json_sidecar_epoch(path)
    if epoch is not None:
        return Resolved(SOURCE_JSON_SIDECAR, KIND_INSTANT, instant=epoch)

    from_name = read_filename_datetime(path)
    if from_name is not None:
        return Resolved(SOURCE_FILENAME, KIND_WALLCLOCK, wallclock=from_name)

    from_exif = parse_exif_datetime(exif_datetime_text)
    if from_exif is not None:
        return Resolved(SOURCE_EXIF, KIND_WALLCLOCK, wallclock=from_exif)

    return Resolved(SOURCE_MTIME, KIND_INSTANT, instant=stat_result.st_mtime)
