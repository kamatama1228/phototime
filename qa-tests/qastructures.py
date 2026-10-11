"""実機の写真によくある構造のための fixture と、QA 側の segment 走査。

**実装側の test が使う fixture（`tests/`）は読み込まない。**
`phototime.exifio` の `_scan_segments` / `_find_eoi` も使わない。
製品の走査が誤っていても、同じ走査で検証して見逃すことを避けるためである。

ここで組む構造は、実機の JPEG によくあるものである。

- EXIF の APP1 と XMP の APP1 が両方ある（編集ソフト・多くのスマートフォン）
- EXIF の APP1 が 2 つある（＝今も `unsupported_structure` にする側）
- EOI の後ろに data が付いている（motion photo、端末メーカーの独自 data）
- entropy data に `FF 00` の詰め物と RST marker がある
"""

import struct

import qasupport as qa

SOI = b"\xff\xd8"
EOI = b"\xff\xd9"
APP1 = b"\xff\xe1"
APP2 = b"\xff\xe2"
SOS = b"\xff\xda"

EXIF_IDENTIFIER = b"Exif\x00\x00"
XMP_IDENTIFIER = b"http://ns.adobe.com/xap/1.0/\x00"

_SOS_PAYLOAD = b"\x01\x01\x00\x00\x3f\x00"


# --- segment の組み立て ------------------------------------------------

def segment(marker, payload):
    return marker + struct.pack(">H", len(payload) + 2) + payload


def exif_app1(tiff=None):
    """EXIF の APP1。payload は `Exif\\x00\\x00` で始まる。"""
    if tiff is None:
        tiff = qa.build_exif_tiff()
    return segment(APP1, EXIF_IDENTIFIER + tiff)


def xmp_app1(body=b"<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF/></x:xmpmeta>"):
    """XMP の APP1。**EXIF ではない APP1 の代表例である。**"""
    return segment(APP1, XMP_IDENTIFIER + body)


def decoy_xmp_app1():
    """中に `Exif\\x00\\x00` という文字列を含む XMP の APP1。

    「payload の**先頭**が `Exif\\x00\\x00` かどうか」で判別していない実装
    （payload 全体を検索する等）を落とすための囮である。
    """
    return xmp_app1(b"<x:xmpmeta><note>Exif\x00\x00 is not here</note></x:xmpmeta>")


def app2_mpf():
    """APP2（MPF 相当）。EXIF でも XMP でもない segment。"""
    return segment(APP2, b"MPF\x00" + b"\x00" * 16)


def exif_tiff_with_thumbnail(datetime_text="2001:01:01 00:00:00",
                             offset_text="+00:00", thumbnail=None):
    """IFD1（thumbnail）を持つ EXIF。**実機の写真にほぼ必ずある構造である。**

    `qasupport.build_exif_tiff` が作る TIFF の末尾に IFD1 を足し、IFD0 の
    「次の IFD」の位置（offset 22）をその IFD1 に向ける。
    """
    base = bytearray(qa.build_exif_tiff(datetime_text, offset_text))
    if thumbnail is None:
        thumbnail = jpeg([], image=bytes(range(0x30, 0x60)))
    ifd1_start = len(base)
    thumb_offset = ifd1_start + 2 + 24 + 4
    ifd1 = bytearray()
    ifd1 += struct.pack(">H", 2)
    ifd1 += struct.pack(">HHII", 0x0201, 4, 1, thumb_offset)   # 開始位置
    ifd1 += struct.pack(">HHII", 0x0202, 4, 1, len(thumbnail))  # 長さ
    ifd1 += struct.pack(">I", 0)
    assert len(ifd1) == thumb_offset - ifd1_start
    base[22:26] = struct.pack(">I", ifd1_start)
    return bytes(base) + bytes(ifd1) + thumbnail


def entropy_with_stuffing_and_rst():
    """`FF 00` の詰め物と RST marker を含む、規格どおりの entropy data。

    **`FF` を含まない画像 data だけで試験すると、前から走査する実装の
    誤りに気づけない。**
    """
    return (b"\x3a\xff\x00\x7e\x11"
            + b"\xff\xd0"                     # RST0
            + b"\x22\xff\x00\x33"
            + b"\xff\xd1"                     # RST1
            + bytes(range(0x20, 0x50)))


def jpeg(segments=(), image=None, trailing=b""):
    """SOI → segments → SOS → 画像 data → EOI → trailing の JPEG。"""
    if image is None:
        image = entropy_with_stuffing_and_rst()
    parts = [SOI]
    parts.extend(segments)
    parts.append(segment(SOS, _SOS_PAYLOAD))
    parts.append(image)
    parts.append(EOI)
    parts.append(trailing)
    return b"".join(parts)


def motion_photo_trailing():
    """EOI の後ろに付ける data。**中に `FF D9` を含む。**

    `data.rfind(b"\\xff\\xd9")` で EOI を探す実装は、ここにある `FF D9` を
    画像本体の終わりだと誤認する。**誤認したことは、後ろの data を書き換えて
    しまう形ではなく、EXIF の位置計算が狂う形で現れ得る。**
    """
    return (b"MotionPhoto_Data\x00" + bytes(range(0x00, 0x30))
            + b"\xff\xd9"                    # 紛らわしい EOI もどき
            + b"trailer-tail" + b"\xff\xd9\xff\xd8")


def progressive_jpeg(segments=(), trailing=b""):
    """SOS が 2 つある JPEG（progressive に相当。編集ソフトの出力によくある）。

    1 本目の SOS の後ろに、DHT と 2 本目の SOS が続く。**前から走査して EOI を
    探す実装は、ここを規則どおり通過できなければならない。**
    """
    parts = [SOI]
    parts.extend(segments)
    parts.append(segment(SOS, _SOS_PAYLOAD))
    parts.append(entropy_with_stuffing_and_rst())
    parts.append(segment(b"\xff\xc4", b"\x00" * 8))      # DHT
    parts.append(segment(SOS, _SOS_PAYLOAD))
    parts.append(entropy_with_stuffing_and_rst())
    parts.append(EOI)
    parts.append(trailing)
    return b"".join(parts)


def nested_jpeg_trailing():
    """EOI の後ろに、完全な JPEG がまるごと 1 枚付いている場合。"""
    return jpeg([exif_app1()], trailing=b"")


# --- QA 側の segment 走査（製品の実装を使わない） ----------------------

def scan(data):
    """SOS に達するまでの segment を [(marker, payload_start, payload_len)] で返す。

    `phototime.exifio._scan_segments` とは別に、QA 側で改めて辿る。
    """
    assert data[0:2] == SOI, "SOI で始まっていない fixture"
    out = []
    pos = 2
    while pos < len(data):
        assert data[pos] == 0xFF, "marker の位置がずれている fixture"
        while data[pos] == 0xFF:
            pos += 1
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        length = struct.unpack_from(">H", data, pos)[0]
        out.append((marker, pos + 2, length - 2))
        if marker == 0xDA:
            break
        pos += length
    return out


def exif_app1_span(data):
    """EXIF の APP1 segment が占める [開始, 終了) を返す。無ければ None。"""
    for marker, payload_start, payload_len in scan(data):
        if marker != 0xE1:
            continue
        if data[payload_start:payload_start + 6] != EXIF_IDENTIFIER:
            continue
        return payload_start - 4, payload_start + payload_len
    return None


def xmp_app1_spans(data):
    """XMP の APP1 segment が占める [開始, 終了) の一覧。"""
    spans = []
    for marker, payload_start, payload_len in scan(data):
        if marker != 0xE1:
            continue
        if data[payload_start:payload_start + 6] == EXIF_IDENTIFIER:
            continue
        spans.append((payload_start - 4, payload_start + payload_len))
    return spans


def image_end(data):
    """画像本体の EOI の位置（**前から走査して決める**）。"""
    segments = scan(data)
    marker, payload_start, payload_len = segments[-1]
    assert marker == 0xDA, "SOS が無い fixture"
    pos = payload_start + payload_len
    while pos < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        while data[pos] == 0xFF:
            pos += 1
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            return pos
        if marker == 0x00 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        pos += struct.unpack_from(">H", data, pos)[0]
    raise AssertionError("EOI が見つからない fixture")


def trailing_part(data):
    """EOI の後ろの data。"""
    return data[image_end(data):]


def body_part(data):
    """SOS marker から画像本体の EOI までの byte 列（＝画像 data 部）。"""
    segments = scan(data)
    marker, payload_start, payload_len = segments[-1]
    assert marker == 0xDA
    return data[payload_start - 4:image_end(data)]


def read_exif(data):
    """EXIF の APP1 から DateTimeOriginal / OffsetTimeOriginal を読む。

    `qasupport.read_exif_values` は **最初の APP1** を EXIF だと仮定して
    いるため、XMP が先にある file には使えない。EXIF の APP1 だけを切り出して
    渡すことで、`qasupport` の独立な parser をそのまま使う。
    """
    span = exif_app1_span(data)
    if span is None:
        return {}
    start, end = span
    return qa.read_exif_values(SOI + data[start:end])


def differing_offsets(before, after):
    """2 つの byte 列で、値が違う位置の一覧。長さが違えば AssertionError。"""
    assert len(before) == len(after), "file の大きさが変わっている"
    return [i for i in range(len(before)) if before[i] != after[i]]
