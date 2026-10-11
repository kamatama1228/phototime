# phototime

**A command-line tool that fixes photo capture dates (EXIF `DateTimeOriginal`) and
time zones (`OffsetTimeOriginal`) in bulk, before you import the photos into a
photo library.**

It is meant for situations like these:

- The capture date is missing from the file, and only the filename or a JSON
  sidecar still has it.
- Photos from a trip carry the wrong time zone.
- You want to avoid broken sort order, albums and "on this day" views after the
  import.

It is meant to be run **before** importing into immich, PhotoPrism, Nextcloud
Memories and similar libraries.

日本語版は [README.ja.md](README.ja.md) にあります。

> **This is a draft.** The repository has not been published yet (no repository
> creation, no topics, no published README). Publishing is the owner's decision.

---

## Before you start (so that nothing here is over-promised)

- **You decide which time zone a photo was taken in. This tool cannot know it.**
  For travel photos you will need to **split the photos into one directory per
  leg of the trip and run the tool once per directory.** The most tedious part
  of the problem stays outside this tool.
- **The tool never guesses the UTC offset.** If the source of the date is an
  instant and you did not state the offset, the file is skipped (see below).
- **It has not been confirmed that photo libraries (immich and others) read the
  XMP sidecar files this tool writes.** Please check that on your side.
- **No promise of support.** There is no commitment to answer issues.
- This tool is **not affiliated with immich, Google, or Google Photos.** It
  works with the files that those programs read and write, nothing more.

## How it decides

**The tool never infers the UTC offset.**

Date sources come in two kinds, and they are not interchangeable:

| Source | Kind | What is missing |
|---|---|---|
| Epoch seconds in a JSON sidecar of the same name | **instant** | the local offset |
| File modification time (mtime) | **instant** | the local offset |
| A date in the filename (`20230504_121456` and similar) | **wallclock** | which instant it was |
| An existing EXIF `DateTimeOriginal` | **wallclock** | which instant it was |

If the two kinds are mixed up, the capture date silently moves by the size of
your offset. So this tool behaves as follows:

- When the source is an **instant**, it writes **only if you state the offset**
  with `--shift` or `--assume-tz`. Without that, the file is **skipped**
  (`offset_required`).
- When the source is a **wallclock** value, that value is used as it is, and the
  offset is written **only if you stated one.**

**The column `source_kind` in the output always tells you which kind was used.**

## Usage

All you need is **Python 3**. No external packages are used, and the tool never
connects to the network.

```
python3 -m phototime ~/photos                       # dry-run by default: nothing is changed
python3 -m phototime ~/photos --report ~/plan.csv   # write the plan to a CSV file
python3 -m phototime ~/photos --shift +09:00 --apply --journal ~/undo.json
python3 -m phototime --undo ~/undo.json             # roll the changes back
```

### Options

| Option | What it does |
|---|---|
| `--apply` | Actually write the changes (the default is dry-run) |
| `--dry-run` | Only show the plan, change nothing (default) |
| `--report PATH` | Write the plan to a CSV file. **The path may not be inside the target directory** |
| `--shift OFFSET` | State a fixed offset (for example `+09:00`). **Recommended** |
| `--assume-tz NAME` | State an IANA time zone name (for example `Asia/Tokyo`) |
| `--recursive` | Include subdirectories |
| `--no-xmp` | Do not write XMP sidecar files |
| `--no-mtime` | Do not change the file modification time (mtime) |
| `--rename` | Prefix filenames with `YYYY-MM-DD_HHMMSS` (off by default) |
| `--journal PATH` | Where `--apply` records what it changed. **The path may not be inside the target directory** |
| `--undo PATH` | Read a journal and roll back what `--apply` did |
| `--version` | Print the version |
| `--help` | Print the usage |

**`--shift` is the recommended option.** `--assume-tz` reads the **time zone
database of the operating system**, which is not available everywhere. When it
is unavailable, the tool tells you to use `--shift` and exits with code 2
without changing any file.

### Output columns

`path, source, source_kind, before_datetime, after_datetime, before_offset,
after_offset, action, reason`

In a dry-run, `action` is one of `would_update`, `would_write_xmp`, `unchanged`,
`skipped`. With `--apply`, it is one of `updated`, `xmp_only`, `unchanged`,
`skipped`.

## What it does not do

- **Adding an EXIF tag that does not exist yet.** Only existing values are
  overwritten, because rebuilding the IFD risks corrupting the file. For files
  without the tag, the value is written to `<file>.xmp` instead.
- **Videos (MP4 / MOV) and HEIC / RAW files.**
- A graphical interface.
- Connecting to a library's API (immich and others) or automating the import.
- Faces, places, albums and other metadata.

## About safety

- **By default not a single byte of any file is changed, and no new file is
  created.**
- Writing happens **only inside the EXIF APP1 segment.** The image data and the
  file size do not change.
- `--apply` leaves a journal, and `--undo` rolls the changes back.
- **The journal is written before the change.** Before a file is modified, the
  record needed to restore that file is written to the journal and flushed to
  disk. **So if `--apply` is interrupted (Ctrl-C, power loss), whatever was
  already changed can still be rolled back with `--undo`.**
- **Even so, please back up photos that matter to you before running `--apply`.**

## Known limitations

- **A JPEG that contains two or more EXIF APP1 segments is skipped**
  (`unsupported_structure`), because the tool cannot decide which one is
  authoritative. Other APP1 segments, such as XMP, are left alone and do not
  cause a skip.
- **`--rename` does not rename a JSON sidecar of the same name**
  (`<file>.jpg.json`). Only the image file is renamed, and the JSON sidecar
  keeps its original name. (`--undo` restores both.)
- **There is no way to resume an interrupted `--apply` from where it stopped.**
  Roll back with `--undo` and run it again.

## Paid features

**Not available yet.** No price and no date can be promised.

## License

MIT License (see `LICENSE`).

The source code and documentation of this tool were written with AI assistance
(Anthropic's Claude), then reviewed and published by the repository owner.
