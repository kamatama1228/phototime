"""XMP sidecar の出力。

**EXIF の tag が存在せず、上書きで記録できなかったときだけ**書き出す。

> **未確認であることを隠さない**: 本 tool が書いた XMP sidecar を、写真ライブラリ
> 側が読むかどうかは検証していない。README にも同じことを書く。
"""

from xml.sax.saxutils import escape

_TEMPLATE = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="phototime">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:exif="http://ns.adobe.com/exif/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
   <exif:DateTimeOriginal>{stamp}</exif:DateTimeOriginal>
   <xmp:CreateDate>{stamp}</xmp:CreateDate>
   <photoshop:DateCreated>{stamp}</photoshop:DateCreated>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


def sidecar_path(path):
    """`<file>.xmp`。元の拡張子は残す（同名の別形式と衝突させないため）。"""
    return path + ".xmp"


def render(stamp):
    """ISO 8601 の日時文字列から XMP packet を作る。"""
    return _TEMPLATE.format(stamp=escape(stamp))
