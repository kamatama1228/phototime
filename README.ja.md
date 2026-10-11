# phototime

**写真の撮影日時（EXIF `DateTimeOriginal`）とタイムゾーン（`OffsetTimeOriginal`）を、
写真ライブラリに取り込む前に、まとめて直すための CLI です。**

- 撮影日時が入っていない（file 名にだけ日時がある、日時が JSON の sidecar 側にだけ残っている）
- 旅行先の写真のタイムゾーンがずれている
- 取り込んだ後に並び順・アルバム・「○年前の今日」が壊れるのを避けたい

といった場面を想定しています。immich / PhotoPrism / Nextcloud Memories などに
取り込む **前** に使うことを想定しています。

English version: [README.md](README.md)

---

## 先にお伝えすること（過大な約束をしないために）

- **「どの写真がどのタイムゾーンだったか」は、本ツールには分かりません。利用者が
  指定します。** 旅行の写真なら、**旅程ごとに directory を分けて複数回実行する**
  必要があります。**困りごとの中で最も面倒な部分は、本ツールの外にあります。**
- **本ツールは、オフセット（UTC からのずれ）を推定しません。** 情報源が「瞬間」で、
  オフセットの明示が無ければ、その file は skip します（下記）。
- **本ツールが書いた XMP sidecar を、ライブラリ側（immich 等）が読むかどうかは
  確認していません。** 利用者側で確かめてください。
- **issue に必ず答えるとは約束できません。**
- 本ツールは immich / Google / Google Photos とは **無関係です**
  （not affiliated with immich, Google, or Google Photos）。これらが読み書きする
  file を扱うだけです。

## 考え方

**オフセット（UTC からのずれ）を推定しません。**

日時の情報源には、性質の違う 2 種類があります。

| 情報源 | 種別 | 足りないもの |
|---|---|---|
| 同名の JSON sidecar の epoch 秒 | **瞬間（instant）** | 現地のオフセット |
| file の更新時刻（mtime） | **瞬間（instant）** | 現地のオフセット |
| file 名の日時（`20230504_121456` など） | **壁時計（wallclock）** | その瞬間がいつか |
| 既存の EXIF `DateTimeOriginal` | **壁時計（wallclock）** | その瞬間がいつか |

この 2 つを区別せずに扱うと、**撮影日時が利用者のオフセットの分だけ、静かに
ずれます。** そのため本ツールは、

- 情報源が **瞬間** のときは、**`--shift` か `--assume-tz` の明示があるときだけ**
  書き込みます。明示が無ければ **その file を skip します**（`offset_required`）。
- 情報源が **壁時計** のときは、その値をそのまま使い、**オフセットは明示が
  あるときだけ** 書きます。

**どちらの種別から決めたかは、出力の `source_kind` 列に必ず出ます。**

## 使い方

必要なものは **Python 3 だけ**です。外部 package は 1 つも使いません。
network にも接続しません。

```
python3 -m phototime ~/photos                       # 既定は dry-run。何も変えません
python3 -m phototime ~/photos --report ~/plan.csv   # 計画を CSV に出します
python3 -m phototime ~/photos --shift +09:00 --apply --journal ~/undo.json
python3 -m phototime --undo ~/undo.json             # 元に戻します
```

**この tool が画面に出す message は、すべて英語です**（`--help`、警告、中止の
理由、集計行）。option 名はもともと英語なので、下の表はそのまま使えます。

### option

| option | はたらき |
|---|---|
| `--apply` | 実際に書き換えます（既定は dry-run） |
| `--dry-run` | 書き換えずに計画だけを表示します（既定） |
| `--report PATH` | 計画を CSV に書き出します。**対象 directory の内側は指定できません** |
| `--shift OFFSET` | 固定オフセットを明示します（例: `+09:00`）。**推奨** |
| `--assume-tz NAME` | IANA の時刻帯名を明示します（例: `Asia/Tokyo`） |
| `--recursive` | 下位 directory も対象にします |
| `--no-xmp` | XMP sidecar を書き出しません |
| `--no-mtime` | file の更新時刻（mtime）を変更しません |
| `--rename` | file 名に `YYYY-MM-DD_HHMMSS` を前置します（既定 off） |
| `--journal PATH` | `--apply` の記録先。**対象 directory の内側は指定できません** |
| `--undo PATH` | journal を読み、`--apply` の変更を元に戻します |
| `--version` | version を表示します |
| `--help` | 使い方を表示します |

**`--shift` を推奨します。** `--assume-tz` は **OS の時刻帯 database** を読むため、
環境によっては使えません。使えないときは、`--shift` を使うよう案内して終了します
（終了 code 2）。file は変更しません。

### 出力の列

`path, source, source_kind, before_datetime, after_datetime, before_offset,
after_offset, action, reason`

`action` は、dry-run では `would_update` / `would_write_xmp` / `unchanged` /
`skipped`、`--apply` では `updated` / `xmp_only` / `unchanged` / `skipped` です。

### `reason` の意味

| `reason` | 何が起きたか |
|---|---|
| `offset_required` | 日時の情報源が **瞬間**（JSON sidecar か file の mtime）で、オフセットの明示が無かった。**その file は skip し、何も書いていません。** `--shift` か `--assume-tz` を付けて実行し直してください。 |
| `unsupported_structure` | 書き込んでよい形の JPEG だと判断できなかった。たとえば **EXIF の APP1 segment が 2 つ以上ある** 場合で、どれを正とするか決められません。**skip します。** XMP など、EXIF 以外の APP1 は、この理由になりません。 |
| `unreadable_jpeg` | JPEG として始まっているが、解釈できなかった（途中で切れている、segment のつながりが合わない）。**skip します。** |
| `not_a_jpeg` / `empty_file` | JPEG ではない file、または大きさが 0 の file。**skip します。** |
| `unreadable_file` | file を開けなかった（権限など）。**skip します。** |
| `exif_tag_absent` | 上書きする `DateTimeOriginal` が無かったため、値を `<file>.xmp` に書きました（`xmp_only`）。**JPEG 本体は変更していません。** |
| `offset_tag_absent` | 日時の tag はその場で書き換えたが、上書きする `OffsetTimeOriginal` が無かったため、オフセットを `<file>.xmp` に書きました。 |
| `value_too_long` | 新しい値が、長さの決まっている既存の tag に収まらなかった。**segment を広げないため skip します。** |
| `no_change` | 書こうとした値が、すでに入っていた。何もしません。 |

## 実行例

file は 3 つです。`IMG_0001.jpg` は EXIF に日時があるがオフセットが無い、
`IMG_0002.jpg` は EXIF に日時が無く、隣に `IMG_0002.jpg.json` だけがある、
`IMG_0003.jpg` は EXIF の APP1 が 2 つある、という状態です。

**1. dry-run（既定）。CSV も含めて、何も書きません。**

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

`IMG_0002.jpg` を skip するのは、意図した動作です。sidecar が与えるのは
**瞬間** であり、オフセットの明示が無いので、推定しません。

**2. 同じ計画を CSV に出す。**

```
$ python3 -m phototime ~/photos --report ~/plan.csv
```

```
path,source,source_kind,before_datetime,after_datetime,before_offset,after_offset,action,reason
/home/you/photos/IMG_0001.jpg,exif,wallclock,2023:05:04 12:14:56,2023:05:04 12:14:56,,,unchanged,no_change
/home/you/photos/IMG_0002.jpg,json_sidecar,instant,,,,,skipped,offset_required
/home/you/photos/IMG_0003.jpg,,,,,,,skipped,unsupported_structure
```

**3. オフセットを明示して、journal を残して書き込む。**

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

`--shift +09:00` を付けたことで、2 つのことが変わりました。`IMG_0002.jpg` は
skip されなくなり、瞬間 `2023-05-04 04:14:56 UTC` が壁時計の
`2023:05:04 13:14:56` になりました。`IMG_0001.jpg` は壁時計の値をそのまま使い、
オフセットが付きます——ただし上書きする `OffsetTimeOriginal` tag が無いため、
オフセットは `IMG_0001.jpg.xmp` に書かれます（`offset_tag_absent`）。

**4. 元に戻す。**

```
$ python3 -m phototime --undo ~/undo.json
Reverted 4 entries (journal: /home/you/undo.json)
```

往復した後、写真は **3 の前と 1 byte も違いません。** 3 で書かれた XMP sidecar も
消えます。entry は記録した変更の 1 件ずつなので、file の数より多くなります。

## できないこと

- **EXIF に存在しない tag の新規追加。** 既存の値の上書きだけを行います
  （IFD を組み直すと file を壊す危険があるため）。tag が無い file については、
  `<file>.xmp` に書き出します。
- **動画（MP4 / MOV）、HEIC / RAW の書き換え。**
- GUI。
- ライブラリ本体（immich 等）への API 接続や、取り込みの自動化。
- 顔・場所・アルバムなどの metadata。

## 安全について

- **既定では file を 1 byte も変えず、新しい file も作りません。**
- 書き換えは **EXIF の APP1 segment の内側だけ**で起き、**画像 data 部と file の
  大きさは変わりません。**
- `--apply` は journal を残し、`--undo` で元に戻せます。
- **journal は、書き換えの前に書かれます。** 1 枚を書き換える前に、その 1 枚を
  戻すための記録を journal の file へ書き、disk へ送ってから、書き換えます。
  **そのため `--apply` を途中で中断しても（Ctrl-C、電源断など）、そこまでに
  書き換わった分は `--undo` で戻せます。**
- **それでも、大事な写真は先に backup を取ってください。**

## 既知の制限

- **EXIF の APP1 segment が 2 つ以上ある JPEG は skip します**
  （`unsupported_structure`）。どれを正とするか決められないためです。**XMP など、
  EXIF 以外の APP1 は、そのまま残し、skip の理由にもしません。**
- **`--rename` は、同名の JSON sidecar（`<file>.jpg.json`）を一緒に rename
  しません。** 画像の file 名だけが変わり、JSON sidecar は元の名前のまま残ります
  （`--undo` では両方とも元に戻ります）。
- **`--apply` を中断した後、処理を途中から再開する機能はありません。**
  `--undo` で戻してから、もう一度やり直してください。

## 有料部分

**準備中です。** 金額も時期もお約束できません。

## license

MIT License（`LICENSE` を参照）。

本ツールの code と文書は、AI（Anthropic の Claude）の支援を受けて書かれ、
repository の所有者が確認して公開しています。
