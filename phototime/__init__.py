"""phototime — 写真の撮影日時・タイムゾーンを、取り込む前にまとめて直す CLI。

設計上、最も重要な規則は「日時の決定」の規則である。
情報源を **瞬間（instant）** と **壁時計（wallclock）** の 2 種類に分け、
オフセットを推定しない。利用者の明示が無ければ skip する。
（`phototime.sources` と `phototime.plan` を参照）

標準 library だけで動く。外部 package は 1 つも import しない。
network には 1 回も接続しない。
"""

__version__ = "0.1.0"
TOOL_NAME = "phototime"
