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

Japanese: [README.ja.md](README.ja.md)

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

### What `reason` means

| `reason` | What happened |
|---|---|
| `offset_required` | The date came from an **instant** source (a JSON sidecar or the file mtime) and you did not state an offset. **The file was skipped**; nothing was written. Re-run with `--shift` or `--assume-tz`. |
| `unsupported_structure` | The JPEG is not in a shape this tool is willing to write into — for example it holds **two or more EXIF APP1 segments**, so the tool cannot tell which one is authoritative. **Skipped.** Other APP1 segments, such as XMP, do not cause this. |
| `unreadable_jpeg` | The file starts like a JPEG but could not be parsed (truncated, or the segment chain does not add up). **Skipped.** |
| `not_a_jpeg` / `empty_file` | The file is not a JPEG at all, or has zero length. **Skipped.** |
| `unreadable_file` | The file could not be opened (permissions and similar). **Skipped.** |
| `exif_tag_absent` | There is no existing `DateTimeOriginal` to overwrite, so the value went to `<file>.xmp` instead (`xmp_only`). The JPEG itself was not modified. |
| `offset_tag_absent` | The date tag was updated in place, but there was no existing `OffsetTimeOriginal` to overwrite, so the offset went to `<file>.xmp`. |
| `value_too_long` | The new value does not fit into the existing tag, which has a fixed length. The tool does not grow the segment. **Skipped.** |
| `no_change` | The file already holds the value the tool would write. Nothing to do. |

## An example run

Three files: `IMG_0001.jpg` has an EXIF date but no offset, `IMG_0002.jpg` has no
EXIF date and only a `IMG_0002.jpg.json` sidecar next to it, `IMG_0003.jpg`
carries two EXIF APP1 segments.

**1. Dry-run (the default). Nothing is written, not even the CSV.**

```
$ python3 -m phototime ~/photos
DRY RUN: no file is changed (pass --apply to write)
file          source        kind       before               after                offset  action     reason
------------  ------------  ---------  -------------------  -------------------  ------  ---------  ---------------------
IMG_0001.jpg  exif          wallclock  2023:05:04 12:14:56  2023:05:04 12:14:56  -       unchanged  no_change
IMG_0002.jpg  json_sidecar  instant    -                    -                    -       skipped    offset_required
IMG_0003.jpg  -             -          -                    -                    -       skipped    unsupported_structure
3 files / skipped 2 / unchanged 1
```

`IMG_0002.jpg` is skipped on purpose: the sidecar gives an **instant**, and no
offset was stated, so the tool refuses to guess one.

**2. The same plan as a CSV.**

```
$ python3 -m phototime ~/photos --report ~/plan.csv
```

```
path,source,source_kind,before_datetime,after_datetime,before_offset,after_offset,action,reason
/home/you/photos/IMG_0001.jpg,exif,wallclock,2023:05:04 12:14:56,2023:05:04 12:14:56,,,unchanged,no_change
/home/you/photos/IMG_0002.jpg,json_sidecar,instant,,,,,skipped,offset_required
/home/you/photos/IMG_0003.jpg,,,,,,,skipped,unsupported_structure
```

**3. Write, stating the offset, with a journal.**

```
$ python3 -m phototime ~/photos --shift +09:00 --apply --journal ~/undo.json
journal: /home/you/undo.json (run --undo /home/you/undo.json to revert these changes)
file          source        kind       before               after                offset    action    reason
------------  ------------  ---------  -------------------  -------------------  --------  --------  ---------------------
IMG_0001.jpg  exif          wallclock  2023:05:04 12:14:56  2023:05:04 12:14:56  ->+09:00  updated   offset_tag_absent
IMG_0002.jpg  json_sidecar  instant    -                    2023:05:04 13:14:56  ->+09:00  xmp_only  exif_tag_absent
IMG_0003.jpg  -             -          -                    -                    -         skipped   unsupported_structure
3 files / skipped 1 / updated 1 / xmp_only 1
```

Two things changed with `--shift +09:00`. `IMG_0002.jpg` is no longer skipped:
the instant `2023-05-04 04:14:56 UTC` becomes the wall clock time
`2023:05:04 13:14:56`. And `IMG_0001.jpg`, whose wall clock time is used as it
is, now gets an offset — but it has no `OffsetTimeOriginal` tag to overwrite, so
that offset goes to `IMG_0001.jpg.xmp` (`offset_tag_absent`).

**4. Roll it back.**

```
$ python3 -m phototime --undo ~/undo.json
Reverted 4 entries (journal: /home/you/undo.json)
```

After the round trip, the photos are **byte for byte what they were before step
3**, and the XMP sidecars written in step 3 are removed again. An entry is one
recorded change, so there are more entries than files.

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
