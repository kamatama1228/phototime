"""phototime の command line。

終了 code:

- `0` … 正常に終わった（1 枚ごとの skip は、ここに含む）
- `2` … 実行する前に中止した（安全のための中止・引数の誤り・時刻帯を解決できない）

**既定は dry-run である。** 書き換えるには `--apply` を明示する。
"""

import argparse
import datetime
import os
import sys

from phototime import __version__, journal as journal_mod, plan as plan_mod
from phototime import report, runner, tzpolicy

EXIT_OK = 0
EXIT_ABORTED = 2

DESCRIPTION = (
    "Fix the capture date/time (EXIF DateTimeOriginal) and the UTC offset "
    "(OffsetTimeOriginal) of photos in bulk, before importing them into a "
    "photo library. The default is a dry run that does not change a single "
    "byte."
)

EPILOG = (
    "Offsets are never guessed. When the source of the date/time is an "
    "instant (the epoch seconds in a JSON sidecar, or the file mtime), the "
    "file is skipped unless you state the offset with --shift or --assume-tz."
)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="phototime",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "directory", nargs="?",
        help="the directory to process (omit it when using --undo)")
    parser.add_argument(
        "--apply", action="store_true",
        help="actually write the changes (the default is a dry run)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="show the plan without changing anything (default)")
    parser.add_argument(
        "--report", metavar="PATH",
        help="write a CSV report to PATH; it must be outside the target "
             "directory")
    parser.add_argument(
        "--shift", metavar="OFFSET",
        help="state a fixed UTC offset, for example +09:00 (recommended)")
    parser.add_argument(
        "--assume-tz", metavar="NAME",
        help="state an IANA time zone name, for example Asia/Tokyo; "
             "this relies on the time zone database of the operating system")
    parser.add_argument(
        "--recursive", action="store_true",
        help="also process sub-directories")
    parser.add_argument(
        "--no-xmp", action="store_true",
        help="do not write XMP sidecar files")
    parser.add_argument(
        "--no-mtime", action="store_true",
        help="do not change the modification time (mtime) of the files")
    parser.add_argument(
        "--rename", action="store_true",
        help="prefix file names with YYYY-MM-DD_HHMMSS (off by default)")
    parser.add_argument(
        "--journal", metavar="PATH",
        help="write the record of --apply to PATH; it must be outside the "
             "target directory")
    parser.add_argument(
        "--undo", metavar="PATH",
        help="read a journal and revert the changes made by --apply")
    parser.add_argument(
        "--version", action="version", version="phototime %s" % __version__)
    return parser


def _abort(err, message):
    err.write("Aborted: %s\n" % message)
    return EXIT_ABORTED


def _default_journal_path():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(os.getcwd(), "phototime-journal-%s.json" % stamp)


def _run_undo(path, out, err):
    try:
        payload = journal_mod.load(path)
    except journal_mod.UndoError as exc:
        return _abort(err, str(exc))
    if payload.get("incomplete"):
        err.write(
            "Warning: the journal was not written to the end (--apply may "
            "have been interrupted). Reverting as far as it was recorded.\n")
    restored, failures = journal_mod.undo(payload)
    out.write("Reverted %d entries (journal: %s)\n" % (restored, path))
    for target, message in failures:
        err.write("Warning: could not revert %s: %s\n" % (target, message))
    return EXIT_OK


def main(argv=None, out=None, err=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    out = out or sys.stdout
    err = err or sys.stderr

    if args.undo:
        return _run_undo(args.undo, out, err)

    if not args.directory:
        return _abort(err, "please give the directory to process.")
    root = args.directory
    if not os.path.isdir(root):
        return _abort(err, "not a directory: %s" % root)

    if args.apply and args.dry_run:
        return _abort(err, "--apply and --dry-run cannot be used together.")
    if args.shift and args.assume_tz:
        return _abort(err, "--shift and --assume-tz cannot be used together.")

    # 対象 directory の内側に出力を置かない（dry-run で file を 1 つも作らないため）。
    if args.report and runner.is_inside(args.report, root):
        return _abort(
            err,
            "the --report path is inside the target directory: %s "
            "(give a path outside it, so that the target is left unchanged)"
            % args.report)

    journal_path = None
    if args.apply:
        journal_path = args.journal or _default_journal_path()
        if runner.is_inside(journal_path, root):
            return _abort(
                err,
                "the --journal path is inside the target directory: %s "
                "(give a path outside it, so that the target is left "
                "unchanged)" % journal_path)

    try:
        policy = tzpolicy.build_policy(args.shift, args.assume_tz)
    except tzpolicy.TimezoneUnavailable as exc:
        return _abort(err, str(exc))

    options = runner.Options(
        apply=args.apply,
        recursive=args.recursive,
        write_xmp=not args.no_xmp,
        set_mtime=not args.no_mtime,
        rename=args.rename,
    )

    plans = runner.build_plans(root, policy, options)
    for message in runner.warnings_for(plans):
        err.write(message + "\n")

    exit_code = EXIT_OK
    if args.apply:
        # **journal は、書き換えを 1 件も始める前に開く。**
        # 開けないなら、ここで中止する。file には触れていない。
        try:
            journal = runner.new_journal(root, journal_path)
        except OSError as exc:
            return _abort(err, "cannot create the journal: %s" % exc)
        try:
            problems = runner.execute(root, plans, journal)
        finally:
            journal.close()
        out.write("journal: %s (run --undo %s to revert these changes)\n"
                  % (journal_path, journal_path))
        for message in problems:
            err.write("Warning: %s\n" % message)
    else:
        for item in plans:
            plan_mod.to_dry_run(item)
        out.write("DRY RUN: no file is changed (pass --apply to write)\n")

    if plans:
        out.write(report.render_table(root, plans) + "\n")
    out.write(report.render_summary(report.summarize(plans), len(plans)) + "\n")

    if args.report:
        report.write_csv(args.report, plans)
        out.write("CSV: %s\n" % args.report)

    return exit_code
