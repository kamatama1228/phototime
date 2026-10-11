"""対象 file を集め、計画を立て、`--apply` のときだけ実行する。

**既定は dry-run である。** dry-run では file を 1 つも作らず、1 byte も変えない。
`--report` を指定したときだけ CSV を書く。
"""

import os

from phototime import exifio, journal as journal_mod, plan as plan_mod, xmp

# sidecar は対象にしない（本体の file だけを数える）。
_SIDECAR_EXTENSIONS = (".json", ".xmp")


class Options:
    """CLI から渡される実行条件。"""

    def __init__(self, apply=False, recursive=False, write_xmp=True,
                 set_mtime=True, rename=False):
        self.apply = apply
        self.recursive = recursive
        self.write_xmp = write_xmp
        self.set_mtime = set_mtime
        self.rename = rename


def is_inside(path, root):
    """`path` が `root` の内側（または root そのもの）かどうか。"""
    root_real = os.path.realpath(root)
    target_real = os.path.realpath(path)
    try:
        return os.path.commonpath([root_real, target_real]) == root_real
    except ValueError:
        return False


def iter_target_files(root, recursive):
    """対象になる file の path を、並びを決めて返す。"""
    found = []
    if recursive:
        for current, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                found.append(os.path.join(current, name))
    else:
        for name in sorted(os.listdir(root)):
            candidate = os.path.join(root, name)
            if os.path.isfile(candidate):
                found.append(candidate)
    return [path for path in found
            if os.path.splitext(path)[1].lower() not in _SIDECAR_EXTENSIONS]


def build_plans(root, policy, options):
    """全 file について `FilePlan` を作る。file には触れない。"""
    plans = []
    for path in iter_target_files(root, options.recursive):
        try:
            jpeg = exifio.read_jpeg(path)
            stat_result = os.stat(path)
        except exifio.JpegError as exc:
            plans.append(plan_mod.skipped(path, exc.reason))
            continue
        except OSError:
            plans.append(plan_mod.skipped(path, "unreadable_file"))
            continue
        plans.append(plan_mod.build_plan(path, jpeg, stat_result, policy, options))
    return plans


def warnings_for(plans):
    """利用者に伝えるべき警告（tag を追加しない旨を含む）。"""
    messages = []
    for item in plans:
        if item.reason == plan_mod.REASON_EXIF_TAG_ABSENT:
            messages.append(
                "Warning: %s: the EXIF data has no DateTimeOriginal tag. "
                "This tool does not add tags, so the date/time is written to "
                "an XMP sidecar instead: %s"
                % (item.path, xmp.sidecar_path(item.path)))
        elif item.reason == plan_mod.REASON_OFFSET_TAG_ABSENT:
            messages.append(
                "Warning: %s: the EXIF data has no OffsetTimeOriginal tag. "
                "This tool does not add tags, so the offset is written to "
                "an XMP sidecar instead: %s"
                % (item.path, xmp.sidecar_path(item.path)))
    return messages


def execute(root, plans, journal):
    """`--apply` の実体。journal に、元に戻すための記録を残す。

    戻り値は、実行中に起きた問題の一覧（空なら問題なし）。
    """
    problems = []
    for item in plans:
        if not item.changes_file:
            continue
        try:
            _execute_one(item, journal)
        except (exifio.JpegError, OSError) as exc:
            problems.append("%s: %s" % (item.path, exc))
    return problems


def _execute_one(item, journal):
    """1 file 分の変更を行う。

    **すべての変更は write-ahead である。** **変更を 1 つ行う前に、
    それを戻すための記録を journal へ書き、disk へ送る。** `journal.record_*`
    から戻った後でなければ、file に触れてはいけない。**この順序を入れ替えると、
    途中で落ちたときに `--undo` で戻せなくなる。**
    """
    path = item.path
    before = os.stat(path)

    # (1) EXIF の上書き。**読む → 記録する → 書く。**
    originals = (exifio.read_patch_originals(path, item.patches)
                 if item.patches else [])
    # mtime の変更（下の (2)）も、この記録で戻せる。
    journal.record_file(path, originals, before.st_atime_ns, before.st_mtime_ns)
    if originals:
        exifio.write_patches(path, originals)

    # (2) mtime。記録は (1) で済んでいる。
    if item.target_mtime is not None:
        os.utime(path, (item.target_mtime, item.target_mtime))

    # (3) rename。**記録してから動かす。**
    if item.rename_to is not None:
        destination = os.path.join(os.path.dirname(path), item.rename_to)
        if os.path.exists(destination):
            raise OSError("the rename target already exists: %s" % destination)
        journal.record_rename(path, destination)
        os.replace(path, destination)
        path = destination

    # (4) XMP sidecar。**記録してから書く。**
    if item.xmp_needed:
        sidecar = xmp.sidecar_path(path)
        previous = None
        if os.path.exists(sidecar):
            with open(sidecar, "rb") as handle:
                previous = handle.read()
        journal.record_write(sidecar, previous)
        stamp = plan_mod.xmp_timestamp(item.after_datetime, item.after_offset)
        with open(sidecar, "w", encoding="utf-8") as handle:
            handle.write(xmp.render(stamp))


def new_journal(root, path):
    """journal を作って開く。**file を 1 つでも書き換える前に呼ぶこと。**"""
    return journal_mod.Journal(os.path.realpath(root), path)
