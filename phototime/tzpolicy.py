"""利用者が明示したオフセットの扱い。

- **主: `--shift +09:00`**。固定オフセット。`datetime.timezone` だけで足りるため、
  OS の時刻帯 database に依存しない。
- **補助: `--assume-tz Asia/Tokyo`**。`zoneinfo` を使う。**OS の時刻帯 database を
  読むため、環境によっては使えない。** 使えないときは例外で落とさず、
  `--shift` を使うよう案内して終了 code 2 で終わる。

**どちらも明示されなかったときは、オフセットを推定しない。** その判断は
`phototime.plan` が行う。この module は「明示されたもの」だけを表す。
"""

import datetime
import re

try:  # pragma: no cover - 環境による分岐
    import zoneinfo

    ZoneInfoNotFoundError = zoneinfo.ZoneInfoNotFoundError
    _ZONEINFO_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - 環境による分岐
    zoneinfo = None

    class ZoneInfoNotFoundError(Exception):
        """`zoneinfo` 自体が無い環境のための代替。"""

    _ZONEINFO_IMPORT_ERROR = exc


_SHIFT_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")

SHIFT_HINT = (
    "The time zone could not be resolved (the time zone database of the "
    "operating system is not readable). Give a fixed offset instead, "
    "for example: --shift +09:00"
)


class TimezoneUnavailable(Exception):
    """`--assume-tz` を解決できなかった。CLI は終了 code 2 で終わる。"""


def load_timezone(name):
    """IANA の時刻帯名を解決する。test はこの関数を差し替える。"""
    if zoneinfo is None:
        raise ZoneInfoNotFoundError(name)
    return zoneinfo.ZoneInfo(name)


def parse_shift(text):
    """"+09:00" / "-0730" を `datetime.timezone` にする。形が違えば None。"""
    match = _SHIFT_RE.match(text.strip())
    if not match:
        return None
    sign, hours, minutes = match.group(1), int(match.group(2)), int(match.group(3))
    if hours > 23 or minutes > 59:
        return None
    delta = datetime.timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        delta = -delta
    return datetime.timezone(delta)


def format_offset(delta):
    """`timedelta` を EXIF の OffsetTimeOriginal の書式にする。"""
    total = int(delta.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total) // 60
    return "%s%02d:%02d" % (sign, total // 60, total % 60)


class OffsetPolicy:
    """利用者が明示したオフセット。明示が無いときは `explicit` が False。"""

    def __init__(self, tzinfo=None, label=None):
        self._tzinfo = tzinfo
        self.label = label

    @property
    def explicit(self):
        return self._tzinfo is not None

    def instant_to_wallclock(self, epoch):
        """瞬間（epoch 秒）を、明示されたオフセットの壁時計に直す。

        戻り値は (naive な datetime, "+09:00")。
        """
        if not self.explicit:
            raise ValueError("offset is not explicit")
        moment = datetime.datetime.fromtimestamp(epoch, self._tzinfo)
        return moment.replace(tzinfo=None), format_offset(moment.utcoffset())

    def offset_for_wallclock(self, naive):
        """壁時計に対応するオフセット文字列。明示が無ければ None。"""
        if not self.explicit:
            return None
        aware = naive.replace(tzinfo=self._tzinfo)
        return format_offset(aware.utcoffset())

    def wallclock_to_epoch(self, naive):
        """壁時計を epoch 秒に直す（mtime の設定に使う）。明示が無ければ None。"""
        if not self.explicit:
            return None
        return naive.replace(tzinfo=self._tzinfo).timestamp()


NO_OFFSET = OffsetPolicy()


def build_policy(shift_text, assume_tz_name):
    """CLI の引数から `OffsetPolicy` を作る。

    解決できないときは `TimezoneUnavailable` を投げる（CLI が終了 code 2 にする）。
    """
    if shift_text is not None:
        tzinfo = parse_shift(shift_text)
        if tzinfo is None:
            raise TimezoneUnavailable(
                "the value of --shift is malformed: %r (for example: +09:00)"
                % shift_text)
        return OffsetPolicy(tzinfo, label="--shift %s" % shift_text)

    if assume_tz_name is not None:
        try:
            tzinfo = load_timezone(assume_tz_name)
        except ZoneInfoNotFoundError:
            raise TimezoneUnavailable(
                "cannot resolve --assume-tz %s. %s"
                % (assume_tz_name, SHIFT_HINT))
        except Exception as exc:  # zoneinfo が投げ得る他の失敗もここで受ける
            raise TimezoneUnavailable(
                "cannot resolve --assume-tz %s (%s). %s"
                % (assume_tz_name, type(exc).__name__, SHIFT_HINT))
        return OffsetPolicy(tzinfo, label="--assume-tz %s" % assume_tz_name)

    return NO_OFFSET
