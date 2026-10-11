"""1 枚ごとに「何をするか」を決める（file には触れない）。

ここは **「日時の決定」の規則の中心**である。

- 情報源が **瞬間（instant）** のとき: 利用者の明示があるときだけ壁時計に直す。
  明示が無ければ `skipped` / `offset_required` にして、**file を 1 byte も変えない**。
- 情報源が **壁時計（wallclock）** のとき: その値をそのまま `DateTimeOriginal` に使う。
  `OffsetTimeOriginal` は、明示があるときだけ書く。
- **オフセットを推定しない。**

この module は判断だけを行い、実際の書き換えは `phototime.runner` が行う。
"""

import datetime
import os

from phototime import sources

# action（CSV の action 列）
ACTION_SKIPPED = "skipped"
ACTION_UNCHANGED = "unchanged"
ACTION_UPDATED = "updated"
ACTION_XMP_ONLY = "xmp_only"
ACTION_WOULD_UPDATE = "would_update"
ACTION_WOULD_WRITE_XMP = "would_write_xmp"

# reason（CSV の reason 列）
REASON_OFFSET_REQUIRED = "offset_required"
REASON_EXIF_TAG_ABSENT = "exif_tag_absent"
REASON_OFFSET_TAG_ABSENT = "offset_tag_absent"
REASON_NO_CHANGE = "no_change"
REASON_VALUE_TOO_LONG = "value_too_long"

RENAME_PREFIX_FORMAT = "%Y-%m-%d_%H%M%S"


class FilePlan:
    """1 枚について決まったこと。CSV の 1 行に 1 対 1 で対応する。"""

    def __init__(self, path):
        self.path = path
        self.source = ""
        self.source_kind = ""
        self.before_datetime = ""
        self.after_datetime = ""
        self.before_offset = ""
        self.after_offset = ""
        self.action = ACTION_SKIPPED
        self.reason = ""
        # 実行に必要な内部情報（CSV には出ない）
        self.patches = []          # [(offset, 新しい byte 列)]
        self.xmp_needed = False
        self.target_mtime = None   # epoch 秒。None なら mtime を変えない
        self.rename_to = None      # 変更後の file 名（basename）

    @property
    def changes_file(self):
        return bool(self.patches) or self.xmp_needed or \
            self.target_mtime is not None or self.rename_to is not None

    def as_row(self):
        return [
            self.path,
            self.source,
            self.source_kind,
            self.before_datetime,
            self.after_datetime,
            self.before_offset,
            self.after_offset,
            self.action,
            self.reason,
        ]


def skipped(path, reason, source="", source_kind=""):
    plan = FilePlan(path)
    plan.source = source
    plan.source_kind = source_kind
    plan.action = ACTION_SKIPPED
    plan.reason = reason
    return plan


def build_plan(path, jpeg, stat_result, policy, options):
    """1 枚の JPEG について `FilePlan` を作る。

    `jpeg` は `exifio.JpegExif`、`policy` は `tzpolicy.OffsetPolicy`。
    `options` は `rename` / `write_xmp` / `set_mtime` を持つ。
    """
    plan = FilePlan(path)
    plan.before_datetime = jpeg.datetime_original or ""
    plan.before_offset = jpeg.offset_time_original or ""

    resolved = sources.resolve(path, jpeg.datetime_original, stat_result)
    plan.source = resolved.source
    plan.source_kind = resolved.kind

    # --- ここが「瞬間」と「壁時計」を分ける唯一の場所である ---
    if resolved.kind == sources.KIND_INSTANT:
        if not policy.explicit:
            # オフセットを推定しない。明示が無ければ何もしない。
            plan.action = ACTION_SKIPPED
            plan.reason = REASON_OFFSET_REQUIRED
            return plan
        wallclock, offset_text = policy.instant_to_wallclock(resolved.instant)
        epoch = resolved.instant
    else:
        wallclock = resolved.wallclock
        offset_text = policy.offset_for_wallclock(wallclock)
        epoch = policy.wallclock_to_epoch(wallclock)

    plan.after_datetime = wallclock.strftime(sources.EXIF_DATETIME_FORMAT)
    plan.after_offset = offset_text or ""

    _fill_actions(plan, jpeg, wallclock, offset_text, epoch, stat_result, options)
    return plan


def _fill_actions(plan, jpeg, wallclock, offset_text, epoch, stat_result, options):
    """決めた値を、どの手段で記録するかを割り当てる。"""
    missing_in_exif = []

    if jpeg.has_datetime_tag:
        if jpeg.datetime_original != plan.after_datetime:
            encoded = jpeg.datetime_slot.encode(plan.after_datetime)
            if encoded is None:
                plan.action = ACTION_SKIPPED
                plan.reason = REASON_VALUE_TOO_LONG
                return
            plan.patches.append((jpeg.datetime_slot.offset, encoded))
    else:
        # tag の新規追加はしない（file を壊す危険が高い）。sidecar に逃がす。
        missing_in_exif.append("datetime")

    if offset_text:
        if jpeg.has_offset_tag:
            if jpeg.offset_time_original != offset_text:
                encoded = jpeg.offset_slot.encode(offset_text)
                if encoded is None:
                    plan.action = ACTION_SKIPPED
                    plan.reason = REASON_VALUE_TOO_LONG
                    return
                plan.patches.append((jpeg.offset_slot.offset, encoded))
        else:
            missing_in_exif.append("offset")

    if missing_in_exif and options.write_xmp:
        plan.xmp_needed = True

    # mtime は「瞬間が確定したとき」だけ設定する。
    # 壁時計しか無く、オフセットの明示も無い file では、瞬間が決まらないため
    # mtime を推定して書き換えることはしない。
    if options.set_mtime and epoch is not None:
        if abs(stat_result.st_mtime - epoch) >= 1.0:
            plan.target_mtime = epoch

    if options.rename:
        new_name = _rename_target(plan.path, wallclock)
        if new_name is not None:
            plan.rename_to = new_name

    if not plan.changes_file:
        plan.action = ACTION_UNCHANGED
        plan.reason = REASON_NO_CHANGE
        return

    if "datetime" in missing_in_exif:
        plan.action = ACTION_XMP_ONLY
        plan.reason = REASON_EXIF_TAG_ABSENT
    elif "offset" in missing_in_exif:
        plan.action = ACTION_UPDATED
        plan.reason = REASON_OFFSET_TAG_ABSENT
    else:
        plan.action = ACTION_UPDATED
        plan.reason = ""


def _rename_target(path, wallclock):
    """`YYYY-MM-DD_HHMMSS` を前置した file 名。既に前置済みなら None。"""
    name = os.path.basename(path)
    prefix = wallclock.strftime(RENAME_PREFIX_FORMAT)
    if name.startswith(prefix + "_"):
        return None
    return "%s_%s" % (prefix, name)


def to_dry_run(plan):
    """`--apply` を付けなかったときの表示に合わせて action を言い換える。"""
    if plan.action == ACTION_UPDATED:
        plan.action = ACTION_WOULD_UPDATE
    elif plan.action == ACTION_XMP_ONLY:
        plan.action = ACTION_WOULD_WRITE_XMP
    return plan


def xmp_timestamp(wallclock_text, offset_text):
    """XMP に書く ISO 8601 の文字列。"""
    moment = datetime.datetime.strptime(
        wallclock_text, sources.EXIF_DATETIME_FORMAT)
    base = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return base + offset_text if offset_text else base
