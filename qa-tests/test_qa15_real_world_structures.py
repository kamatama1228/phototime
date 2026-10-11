"""実機の写真によくある 2 つの構造を、skip せずに処理する（QA 独立検証）。

- (a) **APP1 が 2 つ以上ある JPEG**: `Exif\\x00\\x00` で始まる APP1 だけを EXIF と
  して扱い、XMP などの APP1 は読み飛ばす。**EXIF の APP1 が 2 つ以上あるときだけ**
  `unsupported_structure`。
- (b) **EOI の後ろに data がある JPEG**: 後ろの data を **1 byte も変えずに**
  残したまま処理する。

**実装側の同じ主題の test（`tests/` にある）は
読み込んでいない。** fixture・segment の走査・EXIF の読み直しは、いずれも QA 側で
別に実装した（`qa-tests/qastructures.py`）。

**この file の検証は「結果の byte 列」だけを見る。** 製品の内部関数
（`_find_eoi` / `_is_exif_app1` など）は 1 つも呼んでいない。実装の作りが変わっても、
約束が守られているかどうかだけを見るためである。
"""

import os
import tempfile
import unittest

import qasupport as qa
import qastructures as qs

from test_qa14_write_ahead_journal import Interrupted, WriteHook


class StructureBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.TemporaryDirectory()
        self.addCleanup(self.outside.cleanup)
        self.report = os.path.join(self.outside.name, "plan.csv")
        self.journal = os.path.join(self.outside.name, "undo.jsonl")

    def place(self, name, data, epoch=qa.EPOCH_20230504, mtime=1000000000):
        """JPEG を 1 枚置く。`epoch` を与えると JSON sidecar も置く。"""
        path = os.path.join(self.root, name)
        qa.write(path, data, mtime=mtime)
        if epoch is not None:
            qa.write_sidecar(path, epoch)
        return path

    def dry_run(self):
        code, _out, _err = qa.run_cli([self.root, "--report", self.report,
                                       "--shift", "+09:00"])
        self.assertEqual(code, 0, "終了 code が 0 でない")
        return qa.rows_by_name(self.report)

    def apply(self, *extra):
        code, _out, err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply",
             "--journal", self.journal] + list(extra))
        self.assertEqual(code, 0, "--apply が失敗した: %s" % err)
        return err

    def undo(self):
        code, _out, err = qa.run_cli(["--undo", self.journal])
        self.assertEqual(code, 0, "--undo が失敗した: %s" % err)

    def assert_same_snapshot(self, before, note=""):
        after = qa.snapshot(self.root)
        self.assertEqual(sorted(after), sorted(before),
                         "file の集合が変わっている " + note)
        for name in before:
            self.assertEqual(after[name], before[name],
                             "%s が変わっている %s" % (name, note))


class ExifAndXmpApp1(StructureBase):
    """(a) の前半。EXIF と XMP の APP1 を両方持つ JPEG。"""

    NAME = "exif_and_xmp.jpg"

    def make(self, segments=None):
        segments = segments or [qs.exif_app1(), qs.xmp_app1()]
        self.original = qs.jpeg(segments)
        return self.place(self.NAME, self.original)

    def test_default_run_changes_nothing(self):
        """新しく受け入れる構造でも、既定では 1 byte も変わらないこと。"""
        self.make()
        before = qa.snapshot(self.root)
        code, _out, _err = qa.run_cli([self.root, "--shift", "+09:00"])
        self.assertEqual(code, 0)
        self.assert_same_snapshot(before, "（既定の実行）")

    def test_not_skipped_and_datetime_is_decided(self):
        """**skip されず**、日時が判定される（dry-run の表で確認）。"""
        self.make()
        row = self.dry_run()[self.NAME]
        self.assertNotEqual(row["reason"], "unsupported_structure",
                            "XMP の APP1 があるだけで skip されている")
        self.assertEqual(row["action"], "would_update")
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(row["after_offset"], "+09:00")

    def test_apply_writes_exif_and_leaves_xmp_app1_untouched(self):
        """**書き換えの後、XMP の APP1 が 1 byte も変わっていない**こと。"""
        path = self.make()
        self.apply()
        after = qa.read_file(path)

        values = qs.read_exif(after)
        self.assertEqual(values[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(values[qa.TAG_OFFSET_TIME_ORIGINAL], "+09:00")

        before_spans = qs.xmp_app1_spans(self.original)
        self.assertEqual(len(before_spans), 1, "fixture に XMP の APP1 が無い")
        after_spans = qs.xmp_app1_spans(after)
        self.assertEqual(after_spans, before_spans,
                         "XMP の APP1 の位置・長さが変わっている")
        start, end = before_spans[0]
        self.assertEqual(after[start:end], self.original[start:end],
                         "XMP の APP1 の中身が変わっている")

    def test_every_changed_byte_is_inside_the_exif_app1(self):
        """**変わった byte が、EXIF の APP1 の内側にしか無い。**

        「XMP を壊していない」より強い確認である。**file 全体のどこが変わったかを
        QA 側で数え、EXIF の APP1 の範囲の外に 1 つでもあれば落ちる。**
        """
        path = self.make()
        self.apply()
        after = qa.read_file(path)
        span = qs.exif_app1_span(self.original)
        self.assertIsNotNone(span)
        start, end = span
        changed = qs.differing_offsets(self.original, after)
        self.assertTrue(changed, "何も書き換わっていない（test が無意味）")
        outside = [i for i in changed if not start <= i < end]
        self.assertEqual(outside, [],
                         "EXIF の APP1 の外側が書き換わっている: %r" % outside[:16])

    def test_xmp_app1_before_exif_app1(self):
        """**XMP の APP1 が先にある並び**でも同じ（実機では順序が一定しない）。"""
        path = self.make([qs.xmp_app1(), qs.exif_app1()])
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_update")
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(qs.read_exif(after)[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertEqual(qs.xmp_app1_spans(after)[0], qs.xmp_app1_spans(self.original)[0])
        start, end = qs.xmp_app1_spans(self.original)[0]
        self.assertEqual(after[start:end], self.original[start:end])

    def test_app1_that_merely_contains_the_exif_identifier(self):
        """**payload の途中に `Exif\\x00\\x00` を含む XMP** は、EXIF ではない。

        これを EXIF と数える実装は「EXIF の APP1 が 2 つ」と誤判定して skip する。
        """
        self.make([qs.exif_app1(), qs.decoy_xmp_app1()])
        row = self.dry_run()[self.NAME]
        self.assertNotEqual(row["reason"], "unsupported_structure")
        self.assertEqual(row["action"], "would_update")

    def test_many_non_exif_app1_segments(self):
        """**EXIF でない APP1 が何個あっても skip しない。**"""
        self.make([qs.xmp_app1(), qs.exif_app1(), qs.xmp_app1(b"<a/>"),
                   qs.app2_mpf(), qs.xmp_app1(b"<b/>")])
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_update")

    def test_undo_restores_the_whole_file(self):
        """`--undo` で file 全体の byte 列が元に戻ること。"""
        path = self.make()
        before = qa.snapshot(self.root)
        self.apply()
        self.assertNotEqual(qa.read_file(path), self.original,
                            "書き換わっていない（test が無意味）")
        self.undo()
        self.assertEqual(qa.read_file(path), self.original,
                         "byte 列が元に戻っていない")
        self.assert_same_snapshot(before, "（--undo 後）")


class TwoExifApp1(StructureBase):
    """(a) の後半。EXIF の APP1 が 2 つある JPEG は skip。"""

    NAME = "two_exif.jpg"

    def make(self):
        self.original = qs.jpeg([
            qs.exif_app1(qa.build_exif_tiff("2001:01:01 00:00:00", "+00:00")),
            qs.exif_app1(qa.build_exif_tiff("2002:02:02 00:00:00", "+01:00")),
        ])
        return self.place(self.NAME, self.original)

    def test_still_skipped_with_unsupported_structure(self):
        self.make()
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "unsupported_structure")

    def test_apply_does_not_change_a_single_byte(self):
        path = self.make()
        before = qa.snapshot(self.root)
        self.apply()
        self.assertEqual(qa.read_file(path), self.original,
                         "skip したはずの file が書き換わっている")
        after = qa.snapshot(self.root)
        self.assertEqual(after[self.NAME], before[self.NAME],
                         "skip したはずの file の SHA256 / mtime が変わっている")

    def test_three_exif_app1_also_skipped(self):
        """3 つ以上でも同じ（「ちょうど 2 つ」だけを見ていないことの確認）。"""
        self.place("three.jpg", qs.jpeg([qs.exif_app1(), qs.exif_app1(),
                                         qs.exif_app1()]))
        self.assertEqual(self.dry_run()["three.jpg"]["reason"],
                         "unsupported_structure")


class DataAfterEoi(StructureBase):
    """(b)。EOI の後ろに data がある JPEG。"""

    NAME = "motion.jpg"

    def make(self, trailing=None, segments=None):
        trailing = qs.motion_photo_trailing() if trailing is None else trailing
        segments = segments or [qs.exif_app1()]
        self.original = qs.jpeg(segments, trailing=trailing)
        self.trailing = trailing
        return self.place(self.NAME, self.original)

    def test_fixture_would_defeat_a_naive_rfind(self):
        """**この fixture に歯があることを先に示す。**

        末尾の data の中に `FF D9` が含まれており、`data.rfind(b"\\xff\\xd9")` で
        EOI を探す実装は、画像本体の終わりを**誤った位置**だと判断する。
        """
        self.make()
        correct = qs.image_end(self.original) - 2
        naive = self.original.rfind(b"\xff\xd9")
        self.assertNotEqual(correct, naive,
                            "末尾の data に紛らわしい FF D9 が無い（test が弱い）")

    def test_default_run_changes_nothing(self):
        """既定では 1 byte も変わらないこと。"""
        self.make()
        before = qa.snapshot(self.root)
        code, _out, _err = qa.run_cli([self.root, "--shift", "+09:00"])
        self.assertEqual(code, 0)
        self.assert_same_snapshot(before, "（既定の実行）")

    def test_not_skipped_and_datetime_is_decided(self):
        self.make()
        row = self.dry_run()[self.NAME]
        self.assertNotEqual(row["reason"], "unsupported_structure",
                            "EOI の後ろに data があるだけで skip されている")
        self.assertEqual(row["action"], "would_update")
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900)

    def test_apply_leaves_the_trailing_data_byte_identical(self):
        """**書き換えの後、EOI の後ろの data が 1 byte も変わっていない**こと。"""
        path = self.make()
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(len(after), len(self.original), "file の大きさが変わった")
        self.assertEqual(qs.trailing_part(after), self.trailing,
                         "EOI の後ろの data が変わっている")
        self.assertEqual(qs.read_exif(after)[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)

    def test_image_data_is_byte_identical(self):
        """SOS から EOI までの byte 列が完全に一致すること。"""
        path = self.make()
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(qs.body_part(after), qs.body_part(self.original),
                         "画像 data 部が変わっている")

    def test_every_changed_byte_is_inside_the_exif_app1(self):
        path = self.make()
        self.apply()
        after = qa.read_file(path)
        start, end = qs.exif_app1_span(self.original)
        changed = qs.differing_offsets(self.original, after)
        self.assertTrue(changed, "何も書き換わっていない（test が無意味）")
        outside = [i for i in changed if not start <= i < end]
        self.assertEqual(outside, [],
                         "EXIF の APP1 の外側が書き換わっている: %r" % outside[:16])

    def test_undo_restores_the_whole_file(self):
        """`--undo` で file 全体の byte 列が元に戻ること。"""
        path = self.make()
        before = qa.snapshot(self.root)
        self.apply()
        self.assertNotEqual(qa.read_file(path), self.original)
        self.undo()
        self.assertEqual(qa.read_file(path), self.original)
        self.assert_same_snapshot(before, "（--undo 後）")

    def test_trailing_is_a_whole_jpeg(self):
        """**EOI の後ろに、完全な JPEG がまるごと 1 枚付いている場合。**"""
        path = self.make(trailing=qs.nested_jpeg_trailing())
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_update")
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(qs.trailing_part(after), self.trailing,
                         "後ろに付いた JPEG が変わっている")

    def test_both_structures_in_one_file(self):
        """**XMP の APP1 と EOI の後ろの data が、同じ file にある場合。**"""
        path = self.make(segments=[qs.exif_app1(), qs.xmp_app1()])
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_update")
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(qs.trailing_part(after), self.trailing)
        start, end = qs.xmp_app1_spans(self.original)[0]
        self.assertEqual(after[start:end], self.original[start:end])
        self.assertEqual(qs.read_exif(after)[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)

    def test_progressive_jpeg_with_trailing_data(self):
        """**SOS が 2 つある JPEG**（progressive 相当）＋ 末尾 data。

        前から走査して EOI を探す以上、2 本目以降の segment を規則どおり
        通過できなければならない。
        """
        self.original = qs.progressive_jpeg([qs.exif_app1(), qs.xmp_app1()],
                                            trailing=qs.motion_photo_trailing())
        self.trailing = qs.motion_photo_trailing()
        path = self.place(self.NAME, self.original)
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_update",
                         "progressive の JPEG を扱えていない")
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(qs.trailing_part(after), self.trailing)
        self.assertEqual(qs.body_part(after), qs.body_part(self.original))
        self.assertEqual(qs.read_exif(after)[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.undo()
        self.assertEqual(qa.read_file(path), self.original)

    def test_truncated_file_is_still_rejected(self):
        """**受け入れる範囲を広げすぎていないこと。**

        EOI を持たない file は、後ろの data を受け入れるようになった後も
        `unreadable_jpeg` でなければならない。
        """
        whole = qs.jpeg([qs.exif_app1()])
        self.place("truncated.jpg", whole[:len(whole) - 8], epoch=None)
        row = self.dry_run()["truncated.jpg"]
        self.assertEqual(row["action"], "skipped")
        self.assertEqual(row["reason"], "unreadable_jpeg")


class XmpOnlyWithoutExif(StructureBase):
    """EXIF の APP1 が無く、XMP の APP1 だけがある JPEG（sidecar に逃げる経路）。"""

    NAME = "xmp_only.jpg"

    def test_falls_back_to_the_sidecar_path(self):
        path = self.place(self.NAME, qs.jpeg([qs.xmp_app1()]))
        original = qa.read_file(path)
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_write_xmp")
        self.assertEqual(row["reason"], "exif_tag_absent")
        self.apply()
        self.assertEqual(qa.read_file(path), original,
                         "EXIF の tag が無いのに file が書き換わっている")
        self.assertTrue(os.path.exists(path + ".xmp"), "sidecar が作られていない")


class InterruptedApplyOnNewStructures(StructureBase):
    """「中断しても戻せる」ことを、**新しく受け入れる 2 種類の file で**確かめる。

    受け入れる入力が増えたぶん、この約束も、その入力に対して成り立たなければ
    ならない。
    """

    def make_mixed(self):
        """XMP 付き・末尾 data 付き・両方・通常の 4 枚を並べる。"""
        names = []
        for index, segments_trailing in enumerate([
                ([qs.exif_app1(), qs.xmp_app1()], b""),
                ([qs.exif_app1()], qs.motion_photo_trailing()),
                ([qs.xmp_app1(), qs.exif_app1()], qs.nested_jpeg_trailing()),
                ([qs.exif_app1()], b""),
        ]):
            segments, trailing = segments_trailing
            name = "mixed%02d.jpg" % index
            self.place(name, qs.jpeg(segments, trailing=trailing),
                       epoch=qa.EPOCH_20230504 + index,
                       mtime=1000000000 + index)
            names.append(name)
        return names

    def test_interrupted_apply_can_still_be_undone(self):
        self.make_mixed()
        for stop_at in (1, 2, 3, 4):
            with self.subTest(stop_at=stop_at):
                self.setUp()
                self.make_mixed()
                before = qa.snapshot(self.root)
                with WriteHook(self.root, stop_at=stop_at):
                    with self.assertRaises(Interrupted):
                        qa.run_cli([self.root, "--shift", "+09:00", "--apply",
                                    "--journal", self.journal])
                self.undo()
                self.assert_same_snapshot(
                    before, "（%d 件目の変更の直前で中断）" % stop_at)


class ExifWithThumbnail(StructureBase):
    """**IFD1（thumbnail）を持つ EXIF。**

    名指しで要求された構造ではないが、**実機の写真にはほぼ必ずある。**
    上書きが「既存の tag と同じ長さの範囲」に閉じているなら、thumbnail は
    1 byte も変わらないはずである。
    """

    NAME = "with_thumb.jpg"

    def make(self, trailing=b"", with_xmp=False):
        self.thumbnail = qs.jpeg([], image=bytes(range(0x30, 0x60)))
        tiff = qs.exif_tiff_with_thumbnail(thumbnail=self.thumbnail)
        segments = [qs.exif_app1(tiff)]
        if with_xmp:
            segments.append(qs.xmp_app1())
        self.original = qs.jpeg(segments, trailing=trailing)
        self.assertIn(self.thumbnail, self.original, "fixture に thumbnail が無い")
        return self.place(self.NAME, self.original)

    def test_thumbnail_is_untouched_after_apply(self):
        path = self.make()
        self.apply()
        after = qa.read_file(path)
        self.assertEqual(qs.read_exif(after)[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertIn(self.thumbnail, after, "thumbnail が壊れている")

    def test_thumbnail_with_xmp_and_trailing_data(self):
        """**3 つの構造が同じ file にある場合**（実機に最も近い組み合わせ）。"""
        path = self.make(trailing=qs.motion_photo_trailing(), with_xmp=True)
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "would_update")
        self.apply()
        after = qa.read_file(path)
        self.assertIn(self.thumbnail, after)
        self.assertEqual(qs.trailing_part(after), qs.motion_photo_trailing())
        start, end = qs.xmp_app1_spans(self.original)[0]
        self.assertEqual(after[start:end], self.original[start:end])
        self.assertEqual(qs.read_exif(after)[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)

    def test_undo_restores_the_whole_file(self):
        path = self.make(trailing=qs.motion_photo_trailing(), with_xmp=True)
        self.apply()
        self.undo()
        self.assertEqual(qa.read_file(path), self.original)


class ObservedLimitsOfTheForwardScan(StructureBase):
    """**前から走査するようになったことの代償を、記録として確かめる。**

    実装の側は「規格から外れた entropy data（詰められていない `FF`）を持つ
    file は `unreadable_jpeg` になり得る」と申告した。**QA は申告を転記せず、
    実際に確かめる。** **要求ではないので合否には使わない。**
    安全側（file を 1 byte も変えない）であることだけは、合否と同じ強さで確かめる。
    """

    NAME = "unstuffed.jpg"

    def test_entropy_data_with_an_unstuffed_ff(self):
        image = b"\x11\x22\xff\x7f\x33\x44"   # FF の後ろが 00 でも RST でもない
        path = self.place(self.NAME, qs.jpeg([qs.exif_app1()], image=image))
        original = qa.read_file(path)
        row = self.dry_run()[self.NAME]
        self.assertEqual(row["action"], "skipped",
                         "観測が変わった。QA 結果欄の記録を見直すこと")
        self.assertEqual(row["reason"], "unreadable_jpeg",
                         "観測が変わった。QA 結果欄の記録を見直すこと")
        self.apply()
        self.assertEqual(qa.read_file(path), original,
                         "扱えない file が書き換わっている")


class NegativeControl(StructureBase):
    """**この file の test に歯があることを示す。**

    直す前の実装の規則（**APP1 が 2 つ以上なら skip、EOI の後ろに data が
    あれば skip**）を、test の中だけで `read_jpeg` の外側に被せる。
    **製品の code は 1 文字も変更していない。**

    これが無いと、「全部 OK」は、fixture が何も踏んでいなくても出せる。
    """

    def _install_old_rules(self):
        from phototime import exifio

        real_read_jpeg = exifio.read_jpeg

        def old_read_jpeg(path):
            data = qa.read_file(path)
            try:
                segments = qs.scan(data)
            except AssertionError:
                return real_read_jpeg(path)
            app1s = [item for item in segments if item[0] == 0xE1]
            if len(app1s) > 1:
                raise exifio.JpegError("unsupported_structure")
            if data.rfind(qs.EOI) != len(data) - 2:
                raise exifio.JpegError("unsupported_structure")
            return real_read_jpeg(path)

        exifio.read_jpeg = old_read_jpeg
        self.addCleanup(setattr, exifio, "read_jpeg", real_read_jpeg)

    def test_old_rules_would_fail_these_fixtures(self):
        """直す前の規則なら、この 2 つの fixture は `unsupported_structure`。"""
        self.place("exif_and_xmp.jpg", qs.jpeg([qs.exif_app1(), qs.xmp_app1()]))
        self.place("motion.jpg",
                   qs.jpeg([qs.exif_app1()],
                           trailing=qs.motion_photo_trailing()))
        rows = self.dry_run()
        self.assertEqual(rows["exif_and_xmp.jpg"]["action"], "would_update")
        self.assertEqual(rows["motion.jpg"]["action"], "would_update")

        self._install_old_rules()
        rows = self.dry_run()
        self.assertEqual(rows["exif_and_xmp.jpg"]["reason"],
                         "unsupported_structure",
                         "fixture が (a) の経路を踏んでいない")
        self.assertEqual(rows["motion.jpg"]["reason"],
                         "unsupported_structure",
                         "fixture が (b) の経路を踏んでいない")


if __name__ == "__main__":
    unittest.main()
