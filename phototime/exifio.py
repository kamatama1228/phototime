"""JPEG / EXIF の読み取りと、長さを変えない上書き。

方針:

- **既存の tag の値を、同じ長さの ASCII で上書きするだけ**にする。
  tag の新規追加（IFD の再構築）は行わない。file を壊す危険が高いため。
- 上書きは APP1（EXIF）segment の内側だけで起き、画像 data 部（SOS 以降）には
  1 byte も触れない。file の大きさも変わらない。
- 想定した構造でない JPEG は、例外で落とさず `JpegError` で理由を返す。
- 実機の写真によくある 2 つの構造は、受け入れて処理する。
  **APP1 が 2 つ以上あること**（EXIF と XMP が両方入っている場合など）と、
  **EOI の後ろに data が付いていること**（motion photo など）である。
  どちらも、EXIF の APP1 の外側には 1 byte も書き込まない。

扱う tag は次の 2 つだけである。

- 0x9003 DateTimeOriginal   ASCII 20 ("YYYY:MM:DD HH:MM:SS\\0")
- 0x9011 OffsetTimeOriginal ASCII 7  ("+09:00\\0")
"""

import struct

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"

MARKER_SOS = 0xDA
MARKER_EOI = 0xD9
MARKER_APP1 = 0xE1

TAG_EXIF_IFD_POINTER = 0x8769
TAG_DATETIME_ORIGINAL = 0x9003
TAG_OFFSET_TIME_ORIGINAL = 0x9011

TYPE_ASCII = 2

# 受け入れる ASCII の長さ。NUL 終端のあり／なしの両方を許す。
_DATETIME_LENGTHS = (19, 20)
_OFFSET_LENGTHS = (6, 7)

# IFD を辿るときの上限。壊れた file での無限 loop を防ぐ。
_MAX_IFD_ENTRIES = 512

# APP1 payload の先頭がこれなら EXIF である。XMP などは別の識別子で始まる。
EXIF_IDENTIFIER = b"Exif\x00\x00"


class JpegError(Exception):
    """JPEG として扱えなかったことを、CSV に書く reason code と一緒に表す。"""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class AsciiSlot:
    """file の中で、ASCII 値が実際に置かれている位置。"""

    def __init__(self, offset, length, text):
        self.offset = offset
        self.length = length
        self.text = text

    def encode(self, value):
        """`value` を、この slot と同じ長さの byte 列にする。

        入り切らない値は書かない（長さを変えないという約束を守るため）。
        """
        raw = value.encode("ascii", "strict")
        if len(raw) > self.length:
            return None
        return raw + b"\x00" * (self.length - len(raw))


class JpegExif:
    """1 つの JPEG から読み取った、必要な情報だけ。"""

    def __init__(self, size, datetime_slot=None, offset_slot=None):
        self.size = size
        self.datetime_slot = datetime_slot
        self.offset_slot = offset_slot

    @property
    def datetime_original(self):
        return self.datetime_slot.text if self.datetime_slot else None

    @property
    def offset_time_original(self):
        return self.offset_slot.text if self.offset_slot else None

    @property
    def has_datetime_tag(self):
        return self.datetime_slot is not None

    @property
    def has_offset_tag(self):
        return self.offset_slot is not None


def _clean_ascii(raw):
    """ASCII 値から NUL と前後の空白を取り除く。空なら None。"""
    text = raw.split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return text or None


def _scan_segments(data):
    """SOS に達するまでの segment を (marker, payload_start, payload_len) で返す。

    戻り値の 2 つ目は、SOS segment の直後の位置（＝画像 data の開始位置）。
    SOS が無ければ None。
    """
    n = len(data)
    if n == 0:
        raise JpegError("empty_file")
    if n < 4 or data[0:2] != SOI:
        raise JpegError("not_a_jpeg")

    segments = []
    pos = 2
    sos_end = None
    while pos < n:
        if data[pos] != 0xFF:
            raise JpegError("unreadable_jpeg")
        # 0xFF の詰め物は読み飛ばす。
        while pos < n and data[pos] == 0xFF:
            pos += 1
        if pos >= n:
            raise JpegError("unreadable_jpeg")
        marker = data[pos]
        pos += 1

        if marker == MARKER_EOI:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            # 長さを持たない marker。
            continue
        if pos + 2 > n:
            raise JpegError("unreadable_jpeg")
        seg_len = struct.unpack_from(">H", data, pos)[0]
        if seg_len < 2 or pos + seg_len > n:
            raise JpegError("unreadable_jpeg")
        segments.append((marker, pos + 2, seg_len - 2))
        if marker == MARKER_SOS:
            # この後ろは entropy 符号化された画像 data である。触らない。
            sos_end = pos + seg_len
            break
        pos += seg_len

    return segments, sos_end


def _find_eoi(data, pos):
    """画像本体の EOI（`FF D9`）の位置を、前から走査して返す。

    `data.rfind(EOI)` では、EOI の後ろに付いた data（motion photo、端末メーカーの
    独自 data）の中にたまたま現れた `FF D9` を拾ってしまう。EOI の後ろの data を
    受け入れる以上、後ろから探してはいけない。

    entropy 符号化された data の中の 0xFF は `FF 00` に詰められている。RST
    marker（`FF D0`〜`FF D7`）と、progressive JPEG の 2 本目以降の segment も
    通過する。EOI が見つからなければ `unreadable_jpeg`（＝切り詰められた file）。
    """
    n = len(data)
    while pos < n:
        if data[pos] != 0xFF:
            pos += 1
            continue
        # 0xFF の詰め物は読み飛ばす。最後の 0xFF の次が marker である。
        while pos < n and data[pos] == 0xFF:
            pos += 1
        if pos >= n:
            raise JpegError("unreadable_jpeg")
        marker = data[pos]
        pos += 1

        if marker == MARKER_EOI:
            return pos - 2
        if marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            # byte stuffing（FF 00）、TEM、RST。長さを持たない。
            continue
        # 長さを持つ marker（progressive の 2 本目以降の SOS・DHT、DNL など）。
        if pos + 2 > n:
            raise JpegError("unreadable_jpeg")
        seg_len = struct.unpack_from(">H", data, pos)[0]
        if seg_len < 2 or pos + seg_len > n:
            raise JpegError("unreadable_jpeg")
        pos += seg_len

    raise JpegError("unreadable_jpeg")


def _is_exif_app1(data, payload_start, payload_len):
    """この APP1 が EXIF かどうか（XMP などの APP1 と区別する）。"""
    if payload_len < len(EXIF_IDENTIFIER):
        return False
    end = payload_start + len(EXIF_IDENTIFIER)
    return data[payload_start:end] == EXIF_IDENTIFIER


def _iter_ifd_entries(data, tiff_start, ifd_rel_offset, endian, limit_end):
    """1 つの IFD の entry を (tag, type, count, value_field_offset) で返す。"""
    ifd_abs = tiff_start + ifd_rel_offset
    if ifd_abs < tiff_start or ifd_abs + 2 > limit_end:
        raise JpegError("unsupported_structure")
    count = struct.unpack_from(endian + "H", data, ifd_abs)[0]
    if count > _MAX_IFD_ENTRIES:
        raise JpegError("unsupported_structure")
    end = ifd_abs + 2 + count * 12
    if end > limit_end:
        raise JpegError("unsupported_structure")
    for i in range(count):
        base = ifd_abs + 2 + i * 12
        tag, typ, cnt = struct.unpack_from(endian + "HHI", data, base)
        yield tag, typ, cnt, base + 8


def _read_ascii_slot(data, tiff_start, endian, typ, count, value_field, limit_end,
                     allowed_lengths):
    """ASCII tag の値と、その置かれている位置を返す。扱えない形なら None。"""
    if typ != TYPE_ASCII or count not in allowed_lengths:
        return None
    if count <= 4:
        # 4 byte 以内なら value field に直接入る。この長さの値は想定していない。
        return None
    rel = struct.unpack_from(endian + "I", data, value_field)[0]
    abs_offset = tiff_start + rel
    if abs_offset < tiff_start or abs_offset + count > limit_end:
        raise JpegError("unsupported_structure")
    text = _clean_ascii(data[abs_offset:abs_offset + count])
    return AsciiSlot(abs_offset, count, text)


def _parse_exif_app1(data, payload_start, payload_len):
    """APP1(EXIF) から DateTimeOriginal / OffsetTimeOriginal の位置を取り出す。"""
    header = data[payload_start:payload_start + 6]
    if header != b"Exif\x00\x00":
        # EXIF でない APP1（XMP など）。EXIF は無いものとして扱う。
        return None, None

    tiff_start = payload_start + 6
    limit_end = payload_start + payload_len
    if tiff_start + 8 > limit_end:
        raise JpegError("unsupported_structure")

    byte_order = data[tiff_start:tiff_start + 2]
    if byte_order == b"II":
        endian = "<"
    elif byte_order == b"MM":
        endian = ">"
    else:
        raise JpegError("unsupported_structure")

    magic, ifd0_rel = struct.unpack_from(endian + "HI", data, tiff_start + 2)
    if magic != 42:
        raise JpegError("unsupported_structure")

    exif_ifd_rel = None
    for tag, typ, cnt, value_field in _iter_ifd_entries(
            data, tiff_start, ifd0_rel, endian, limit_end):
        if tag == TAG_EXIF_IFD_POINTER and cnt == 1:
            exif_ifd_rel = struct.unpack_from(endian + "I", data, value_field)[0]
            break

    if exif_ifd_rel is None:
        return None, None

    datetime_slot = None
    offset_slot = None
    for tag, typ, cnt, value_field in _iter_ifd_entries(
            data, tiff_start, exif_ifd_rel, endian, limit_end):
        if tag == TAG_DATETIME_ORIGINAL:
            datetime_slot = _read_ascii_slot(
                data, tiff_start, endian, typ, cnt, value_field, limit_end,
                _DATETIME_LENGTHS)
        elif tag == TAG_OFFSET_TIME_ORIGINAL:
            offset_slot = _read_ascii_slot(
                data, tiff_start, endian, typ, cnt, value_field, limit_end,
                _OFFSET_LENGTHS)

    return datetime_slot, offset_slot


def read_jpeg(path):
    """JPEG を読んで `JpegExif` を返す。扱えなければ `JpegError` を投げる。"""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        raise JpegError("unreadable_file")

    segments, sos_end = _scan_segments(data)
    if sos_end is None:
        raise JpegError("unreadable_jpeg")

    # EOI の後ろに data があってもよい。その data には触れない。
    # ここでは「画像本体が EOI で閉じていること」だけを確かめる。切り詰められた
    # file は `_find_eoi` が `unreadable_jpeg` にする。
    _find_eoi(data, sos_end)

    # EXIF の APP1 だけを対象にする。XMP などの APP1 は読み飛ばし、書き換えも
    # しない。
    exif_app1s = [seg for seg in segments
                  if seg[0] == MARKER_APP1 and _is_exif_app1(data, seg[1], seg[2])]
    if len(exif_app1s) > 1:
        # EXIF の APP1 が複数ある file は、どれを正とするか決められない。
        raise JpegError("unsupported_structure")

    datetime_slot = None
    offset_slot = None
    if exif_app1s:
        _, payload_start, payload_len = exif_app1s[0]
        datetime_slot, offset_slot = _parse_exif_app1(
            data, payload_start, payload_len)

    return JpegExif(len(data), datetime_slot, offset_slot)


def read_patch_originals(path, patches):
    """`patches`（(offset, 新しい byte 列) の列）の、**書き込む前の** byte 列を読む。

    戻り値は [(offset, before, after)]（journal 用）。**file は 1 byte も変えない。**

    write-ahead のため、「読む」と「書く」を 2 つの関数に分けてある。
    呼び出し側は、ここで得た before を journal に残し、disk へ flush してから
    `write_patches` を呼ぶ。順序を逆にしてはいけない。
    """
    originals = []
    with open(path, "rb") as handle:
        for offset, new_bytes in patches:
            handle.seek(offset)
            before = handle.read(len(new_bytes))
            if len(before) != len(new_bytes):
                raise JpegError("unsupported_structure")
            originals.append((offset, before, new_bytes))
    return originals


def write_patches(path, originals):
    """`read_patch_originals` が返した組を file に書き込む。

    長さを変えないため、file の大きさも、画像 data 部も変わらない。
    """
    with open(path, "r+b") as handle:
        for offset, _before, new_bytes in originals:
            handle.seek(offset)
            handle.write(new_bytes)
        handle.flush()


def apply_patches(path, patches):
    """読み取りと書き込みをまとめて行う（write-ahead を使わない経路）。

    **`--apply` の本体は、これではなく `read_patch_originals` +
    `write_patches` を使う**（journal を変更の前に disk へ書くため）。この関数は、
    journal を必要としない呼び出し側のために残してある。
    """
    originals = read_patch_originals(path, patches)
    write_patches(path, originals)
    return originals


def restore_patches(path, patches):
    """journal に記録した byte 列を書き戻す。"""
    with open(path, "r+b") as handle:
        for offset, original in patches:
            handle.seek(offset)
            handle.write(original)
        handle.flush()
