"""出力。既定の dry-run では、標準出力に表を出すだけで file を作らない。

CSV を file に書くのは `--report <path>` を指定したときだけである。
**CSV の列は固定である。** 順序も名前も変えてはいけない。
"""

import csv
import os

CSV_COLUMNS = [
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

# 標準出力の表の列（CSV とは別物。人が読むためのもの）
_TABLE_HEADERS = ["file", "source", "kind", "before", "after", "offset", "action",
                  "reason"]


def write_csv(path, plans):
    """`--report` で指定された path に CSV を書く。"""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for plan in plans:
            writer.writerow(plan.as_row())


def _offset_cell(plan):
    before = plan.before_offset or "-"
    after = plan.after_offset or "-"
    if before == after:
        return before
    return "%s>%s" % (before, after)


def _rows(root, plans):
    rows = []
    for plan in plans:
        rows.append([
            os.path.relpath(plan.path, root),
            plan.source or "-",
            plan.source_kind or "-",
            plan.before_datetime or "-",
            plan.after_datetime or "-",
            _offset_cell(plan),
            plan.action,
            plan.reason or "-",
        ])
    return rows


def render_table(root, plans):
    """標準出力に出す表を文字列で返す。"""
    rows = [_TABLE_HEADERS] + _rows(root, plans)
    widths = [max(len(row[i]) for row in rows) for i in range(len(_TABLE_HEADERS))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[i])
                               for i, cell in enumerate(row)).rstrip())
        if index == 0:
            lines.append("  ".join("-" * width for width in widths))
    return "\n".join(lines)


def summarize(plans):
    """action ごとの件数。"""
    counts = {}
    for plan in plans:
        counts[plan.action] = counts.get(plan.action, 0) + 1
    return counts


def render_summary(counts, total):
    parts = ["%d files" % total]
    for action in sorted(counts):
        parts.append("%s %d" % (action, counts[action]))
    return " / ".join(parts)
