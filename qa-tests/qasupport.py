"""QA 側の道具一式（QA が独自に書いたもの）。

**実装側の test が使う道具（`tests/support.py`）は読み込まない。**
fixture の組み立ても、EXIF の読み取りも、ここで QA が別に実装する。
Builder の parser（`phototime.exifio`）の誤りを、同じ parser で検証して
見逃すことを避けるためである。
"""

import hashlib
import io
import os
import struct
import sys

PRODUCT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PRODUCT_ROOT not in sys.path:
    sys.path.insert(0, PRODUCT_ROOT)

from phototime import cli  # noqa: E402

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
APP1 = b"\xff\xe1"
SOS = b"\xff\xda"

TAG_DATETIME_ORIGINAL = 0x9003
TAG_OFFSET_TIME_ORIGINAL = 0x9011

# 既知の瞬間。手で計算した値であり、実装の関数では求めていない。
#   epoch 1683171296 = 2023-05-04T03:34:56Z
#   +09:00 の壁時計 = 2023-05-04 12:34:56
EPOCH_20230504 = 1683171296
WALLCLOCK_AT_PLUS0900 = "2023:05:04 12:34:56"
WALLCLOCK_AT_UTC = "2023:05:04 03:34:56"


# --- fixture の組み立て ------------------------------------------------

def build_exif_tiff(datetime_text="2001:01:01 00:00:00", offset_text="+00:00",
                    with_datetime=True, with_offset=True, endian="MM",
                    datetime_length=20, offset_length=7):
    """最小の TIFF（EXIF）block を組む。IFD0 → Exif IFD → ASCII 値の順。

    `datetime_length` / `offset_length` で ASCII 値の count を変えられる
    （NUL 終端のあり／なし、想定外の長さの検証に使う）。
    """
    fmt = "<" if endian == "II" else ">"
    tags = []
    if with_datetime:
        tags.append((TAG_DATETIME_ORIGINAL, datetime_length,
                     (datetime_text.encode("ascii")
                      + b"\x00" * datetime_length)[:datetime_length]))
    if with_offset:
        tags.append((TAG_OFFSET_TIME_ORIGINAL, offset_length,
                     (offset_text.encode("ascii")
                      + b"\x00" * offset_length)[:offset_length]))

    exif_ifd_offset = 26
    data_offset = exif_ifd_offset + 2 + len(tags) * 12 + 4

    out = bytearray()
    out += endian.encode("ascii")
    out += struct.pack(fmt + "HI", 42, 8)
    out += struct.pack(fmt + "H", 1)
    out += struct.pack(fmt + "HHII", 0x8769, 4, 1, exif_ifd_offset)
    out += struct.pack(fmt + "I", 0)
    assert len(out) == exif_ifd_offset

    out += struct.pack(fmt + "H", len(tags))
    blob = b""
    for tag, count, value in tags:
        out += struct.pack(fmt + "HHII", tag, 2, count, data_offset + len(blob))
        blob += value
    out += struct.pack(fmt + "I", 0)
    assert len(out) == data_offset
    out += blob
    return bytes(out)


def build_jpeg(exif=None, extra_app1=False, trailing=b"", image=None):
    """SOI → (APP1) → SOS → 画像 data → EOI → (trailing) の JPEG。"""
    parts = [SOI]
    if exif is not None:
        payload = b"Exif\x00\x00" + exif
        parts.append(APP1 + struct.pack(">H", len(payload) + 2) + payload)
    if extra_app1:
        payload = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta/>"
        parts.append(APP1 + struct.pack(">H", len(payload) + 2) + payload)
    sos_payload = b"\x01\x01\x00\x00\x3f\x00"
    parts.append(SOS + struct.pack(">H", len(sos_payload) + 2) + sos_payload)
    parts.append(image if image is not None else bytes(range(0x20, 0x70)))
    parts.append(EOI)
    parts.append(trailing)
    return b"".join(parts)


def plain_jpeg(datetime_text="2001:01:01 00:00:00", offset_text="+00:00",
               with_datetime=True, with_offset=True, endian="MM"):
    return build_jpeg(build_exif_tiff(datetime_text, offset_text,
                                      with_datetime, with_offset, endian))


def write(path, data, mtime=None):
    with open(path, "wb") as handle:
        handle.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def write_sidecar(path, epoch, key="photoTakenTime"):
    """JSON sidecar（`<photo>.jpg.json`）を書く。"""
    body = '{"%s": {"timestamp": "%d", "formatted": "-"}}' % (key, epoch)
    with open(path + ".json", "w", encoding="utf-8") as handle:
        handle.write(body)
    return path + ".json"


# --- QA 独自の EXIF 読み取り（exifio を使わない） ----------------------

def read_exif_values(data):
    """JPEG の byte 列から DateTimeOriginal / OffsetTimeOriginal を読む。

    `phototime.exifio` とは独立に、QA 側で改めて TIFF を辿る。
    """
    index = data.find(APP1)
    if index == -1:
        return {}
    payload = index + 4
    if data[payload:payload + 6] != b"Exif\x00\x00":
        return {}
    tiff = payload + 6
    fmt = "<" if data[tiff:tiff + 2] == b"II" else ">"
    ifd0 = struct.unpack_from(fmt + "I", data, tiff + 4)[0]

    def entries(relative_offset):
        count = struct.unpack_from(fmt + "H", data, tiff + relative_offset)[0]
        for i in range(count):
            base = tiff + relative_offset + 2 + i * 12
            tag, typ, num = struct.unpack_from(fmt + "HHI", data, base)
            yield tag, typ, num, base + 8

    values = {}
    for tag, _typ, _num, field in entries(ifd0):
        if tag != 0x8769:
            continue
        exif_ifd = struct.unpack_from(fmt + "I", data, field)[0]
        for inner_tag, _t, count, value_field in entries(exif_ifd):
            if inner_tag not in (TAG_DATETIME_ORIGINAL, TAG_OFFSET_TIME_ORIGINAL):
                continue
            rel = struct.unpack_from(fmt + "I", data, value_field)[0]
            raw = data[tiff + rel:tiff + rel + count]
            values[inner_tag] = raw.split(b"\x00", 1)[0].decode("ascii").strip()
    return values


def read_file(path):
    with open(path, "rb") as handle:
        return handle.read()


def exif_of(path):
    return read_exif_values(read_file(path))


def image_part(data):
    """SOS marker 以降の byte 列（＝画像 data 部）。"""
    index = data.find(SOS)
    assert index != -1, "SOS が見つからない fixture"
    return data[index:]


# --- snapshot と実行 ---------------------------------------------------

def snapshot(root):
    """directory 内の全 file の（相対 path → SHA256・mtime_ns・大きさ）。"""
    result = {}
    for current, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(current, name)
            stat_result = os.stat(full)
            result[os.path.relpath(full, root)] = (
                hashlib.sha256(read_file(full)).hexdigest(),
                stat_result.st_mtime_ns,
                stat_result.st_size,
            )
    return result


def run_cli(argv):
    """CLI を呼び、(終了 code, 標準出力, 標準エラー) を返す。"""
    out = io.StringIO()
    err = io.StringIO()
    code = cli.main(list(argv), out, err)
    return code, out.getvalue(), err.getvalue()


def read_csv_rows(path):
    import csv
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def rows_by_name(path):
    """CSV を {file 名: {列名: 値}} にする。"""
    rows = read_csv_rows(path)
    header = rows[0]
    table = {}
    for row in rows[1:]:
        record = dict(zip(header, row))
        table[os.path.basename(record["path"])] = record
    return table
