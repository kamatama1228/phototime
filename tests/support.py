"""test 用の道具。合成 JPEG を組み立て、CLI を呼び、file の状態を記録する。

実行方法:

    python3 -m unittest discover -s products/prod-001/tests -v

`discover` は `tests/` を sys.path に入れる。product の root（`phototime` package
のある directory）は入らないため、この module の import 時に足す。
"""

import hashlib
import io
import os
import re
import struct
import sys

PRODUCT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PRODUCT_ROOT not in sys.path:
    sys.path.insert(0, PRODUCT_ROOT)

from phototime import cli  # noqa: E402  (sys.path を整えた後でないと import できない)

# ---------------------------------------------------------------- 合成 JPEG

_TAG_EXIF_IFD_POINTER = 0x8769
_TAG_DATETIME_ORIGINAL = 0x9003
_TAG_OFFSET_TIME_ORIGINAL = 0x9011
_TYPE_ASCII = 2
_TYPE_LONG = 4


def _ascii_value(text, length):
    raw = text.encode("ascii")
    assert len(raw) <= length
    return raw + b"\x00" * (length - len(raw))


def _tiff_block(datetime_original, offset_time_original):
    """little endian の TIFF block を組み立てる（IFD0 → ExifIFD）。"""
    entries = []
    if datetime_original is not None:
        entries.append((_TAG_DATETIME_ORIGINAL, _TYPE_ASCII, 20,
                        _ascii_value(datetime_original, 20)))
    if offset_time_original is not None:
        entries.append((_TAG_OFFSET_TIME_ORIGINAL, _TYPE_ASCII, 7,
                        _ascii_value(offset_time_original, 7)))
    entries.sort(key=lambda item: item[0])

    ifd0_offset = 8
    ifd0_size = 2 + 12 + 4                      # entry 1 件 ＋ 次 IFD offset
    exif_ifd_offset = ifd0_offset + ifd0_size
    exif_ifd_size = 2 + 12 * len(entries) + 4
    data_offset = exif_ifd_offset + exif_ifd_size

    header = b"II" + struct.pack("<HI", 42, ifd0_offset)
    ifd0 = struct.pack("<H", 1)
    ifd0 += struct.pack("<HHII", _TAG_EXIF_IFD_POINTER, _TYPE_LONG, 1,
                        exif_ifd_offset)
    ifd0 += struct.pack("<I", 0)

    exif_ifd = struct.pack("<H", len(entries))
    blob = b""
    for tag, typ, count, value in entries:
        exif_ifd += struct.pack("<HHII", tag, typ, count, data_offset + len(blob))
        blob += value
    exif_ifd += struct.pack("<I", 0)

    return header + ifd0 + exif_ifd + blob


def _segment(marker, payload):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


_SOF0 = _segment(0xC0, bytes([8]) + struct.pack(">HH", 1, 1) + bytes([1, 1, 0x11, 0]))
_SOS = _segment(0xDA, bytes([1, 1, 0x00, 0, 63, 0]))
_ENTROPY = bytes([0x00, 0x11, 0x22, 0x33, 0x44, 0x55])

# XMP の APP1（EXIF ではない APP1）。実機では編集ソフトや携帯が付ける。
XMP_PAYLOAD = (b"http://ns.adobe.com/xap/1.0/\x00"
               b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
               b'<x:xmpmeta xmlns:x="adobe:ns:meta/"></x:xmpmeta>'
               b'<?xpacket end="w"?>')
XMP_APP1 = _segment(0xE1, XMP_PAYLOAD)


def jpeg_bytes(datetime_original="2001:01:01 00:00:00",
               offset_time_original="+00:00",
               app1_count=1, trailing=b"", xmp_app1=False):
    """合成 JPEG の byte 列。

    - `datetime_original=None` かつ `offset_time_original=None` で、EXIF の
      日時 tag が無い JPEG になる。
    - `app1_count=0` で APP1 そのものが無い JPEG、`2` で **EXIF の** APP1 が
      2 つある「想定した構造でない」JPEG になる。
    - `xmp_app1=True` で、EXIF の APP1 の後ろに XMP の APP1 が付く。実機の
      写真によくある形であり、受け入れて処理しなければならない。
    - `trailing` を与えると EOI の後ろに独自 data が付く（motion photo など）。
    """
    data = b"\xff\xd8"
    if app1_count:
        app1 = _segment(0xE1, b"Exif\x00\x00"
                        + _tiff_block(datetime_original, offset_time_original))
        data += app1 * app1_count
    if xmp_app1:
        data += XMP_APP1
    data += _SOF0 + _SOS + _ENTROPY + b"\xff\xd9" + trailing
    return data


def write_jpeg(path, **kwargs):
    with open(path, "wb") as handle:
        handle.write(jpeg_bytes(**kwargs))
    return path


def write_bytes(path, raw):
    with open(path, "wb") as handle:
        handle.write(raw)
    return path


def write_sidecar(jpeg_path, epoch):
    """Takeout 風の JSON sidecar（`<file>.json`）を作る。"""
    path = jpeg_path + ".json"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"title": "x", "photoTakenTime": {"timestamp": "%d"}}'
                     % epoch)
    return path


# ---------------------------------------------------------------- 検証の道具

def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def snapshot(root):
    """directory 以下の {相対 path: (SHA256, mtime_ns)}。"""
    result = {}
    for current, _dirs, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(current, name)
            result[os.path.relpath(full, root)] = (
                sha256(full), os.stat(full).st_mtime_ns)
    return result


def image_data_after_sos(path):
    """SOS marker 以降の byte 列（＝画像 data 部）。"""
    with open(path, "rb") as handle:
        raw = handle.read()
    index = raw.find(b"\xff\xda")
    assert index != -1, "SOS marker が見つかりません: %s" % path
    return raw[index:]


def file_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def xmp_app1_region(path):
    """XMP の APP1 segment が置かれている (開始位置, byte 列)。

    実装を通さずに、file の byte 列から直接探す。
    """
    raw = file_bytes(path)
    index = raw.find(XMP_APP1)
    assert index != -1, "XMP の APP1 が見つかりません: %s" % path
    return index, raw[index:index + len(XMP_APP1)]


def trailing_region(path, length):
    """file の末尾 `length` byte（＝EOI の後ろに付けた data）。"""
    return file_bytes(path)[-length:]


def read_exif(path):
    """実装の reader で EXIF の日時とオフセットを読み直す。"""
    from phototime import exifio

    info = exifio.read_jpeg(path)
    return info.datetime_original, info.offset_time_original


_DATETIME_PATTERN = re.compile(rb"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}")
_OFFSET_PATTERN = re.compile(rb"[+-]\d{2}:\d{2}\x00")


def raw_datetime_strings(path):
    """**実装を通さずに** file の byte 列から日時らしい文字列を拾う。

    「書いた値が再読み込みで一致する」を、実装の reader だけに頼らずに確かめる。
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    return [match.decode("ascii") for match in _DATETIME_PATTERN.findall(raw)]


def raw_offset_strings(path):
    """同じく、byte 列から OffsetTimeOriginal らしい文字列を拾う。"""
    with open(path, "rb") as handle:
        raw = handle.read()
    return [match[:-1].decode("ascii") for match in _OFFSET_PATTERN.findall(raw)]


class Result:
    def __init__(self, code, out, err):
        self.code = code
        self.out = out
        self.err = err


def run_cli(argv):
    """CLI を呼び、終了 code と標準出力・標準エラーを返す。"""
    out = io.StringIO()
    err = io.StringIO()
    code = cli.main(argv, out=out, err=err)
    return Result(code, out.getvalue(), err.getvalue())


def read_csv(path):
    """CSV を (header, [row...]) で返す。"""
    import csv

    with open(path, "r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


def csv_row_for(rows, header, filename):
    """basename が一致する行を dict で返す。"""
    for row in rows:
        if os.path.basename(row[0]) == filename:
            return dict(zip(header, row))
    raise AssertionError("CSV に %s の行がありません: %r" % (filename, rows))
