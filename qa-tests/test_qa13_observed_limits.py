"""要求ではない。**観測した挙動の記録**。

ここにある test は合否の根拠ではない。「仕様が触れていない境界で、実際には
何が起きるか」を、推測ではなく実行結果として残すために書く。
挙動が変わればここが落ちるので、後から気づける。

> **以前は、ここに `JournalIsWrittenOnlyAtTheEnd` という観測があった。**
> 「journal は全 file の処理後に 1 回だけ保存される」という挙動であり、
> **中断すると書き換わった file があるのに journal が無い**という欠陥
> そのものだった。**その欠陥を無くすことが後から要求になり**、実装が
> 直ったため、この観測は**合格条件の裏返し**になった。記録としての役目は
> 終わり、**同じ境界を「あるべき姿」の側から検証する test が
> `test_qa14_write_ahead_journal.py` にある**（`journal_file_exists_at_the_
> first_change`）。**test を通すために条件を緩めたのではなく、要求が
> 変わったため、検証の向きを変えた。**
"""

import os
import tempfile
import unittest

import qasupport as qa


class UnusualTagLength(unittest.TestCase):
    """`DateTimeOriginal` の長さが想定外のとき、実際は何が起きるか。

    Builder の「既知の問題」は **`skipped` にしている** と書いているが、
    観測される挙動は **「tag が無い」扱い**（XMP sidecar に逃がす）である。
    どちらでも既存の byte は書き換わらないため AC には触れないが、
    記述と実装がずれているので記録する。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.report = os.path.join(self.outside, "plan.csv")
        self.journal = os.path.join(self.outside, "undo.json")

    def test_oversized_datetime_tag_is_treated_as_absent(self):
        path = os.path.join(self.root, "20230504_123456.jpg")
        tiff = qa.build_exif_tiff("2001:01:01 00:00:00", "+00:00",
                                  datetime_length=25, offset_length=7)
        qa.write(path, qa.build_jpeg(tiff), mtime=1000000000)
        before = qa.read_file(path)

        code, _out, _err = qa.run_cli(
            [self.root, "--apply", "--journal", self.journal,
             "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["20230504_123456.jpg"]
        # 観測: skipped ではなく xmp_only / exif_tag_absent になる。
        self.assertEqual(row["action"], "xmp_only")
        self.assertEqual(row["reason"], "exif_tag_absent")
        # どちらにせよ、既存の EXIF の byte は変わらない。
        self.assertEqual(qa.read_file(path), before,
                         "想定外の長さの tag を書き換えている")

    def test_value_that_does_not_fit_is_skipped(self):
        """slot が短すぎて値が入らない場合は `value_too_long` で skip する。"""
        path = os.path.join(self.root, "20230504_123456.jpg")
        tiff = qa.build_exif_tiff("2001:01:01 00:00", "+00:00",
                                  datetime_length=19, offset_length=7)
        # 19 byte の slot には 19 byte の値が入るため、ここでは収まる。
        qa.write(path, qa.build_jpeg(tiff), mtime=1000000000)
        code, _out, _err = qa.run_cli([self.root, "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["20230504_123456.jpg"]
        self.assertEqual(row["action"], "would_update")


class RenameLeavesSidecarBehind(unittest.TestCase):
    """`--rename` は JSON sidecar を一緒に動かさない（Builder の自己申告の確認）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.report = os.path.join(self.outside, "plan.csv")
        self.journal = os.path.join(self.outside, "undo.json")

        self.photo = os.path.join(self.root, "photo.jpg")
        qa.write(self.photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(self.photo, qa.EPOCH_20230504)

    def test_sidecar_keeps_the_old_name(self):
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--rename",
             "--journal", self.journal])
        self.assertEqual(code, 0)
        renamed = os.path.join(self.root, "2023-05-04_123456_photo.jpg")
        self.assertTrue(os.path.isfile(renamed), "rename されていない")
        # 観測: sidecar は元の名前のまま残る。
        self.assertTrue(os.path.isfile(self.photo + ".json"))
        self.assertFalse(os.path.exists(renamed + ".json"))

    def test_rerun_after_rename_falls_back_to_exif(self):
        """rename 後の再実行では sidecar が見つからず、情報源が変わる。

        1 回目で EXIF に正しい壁時計が入るため、2 回目は (c) 既存 EXIF
        （wallclock）が使われ、値はずれない。**ずれないことを確かめる。**
        """
        qa.run_cli([self.root, "--shift", "+09:00", "--apply", "--rename",
                    "--journal", self.journal])
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--report", self.report])
        self.assertEqual(code, 0)
        row = qa.rows_by_name(self.report)["2023-05-04_123456_photo.jpg"]
        self.assertEqual(row["source_kind"], "wallclock")
        self.assertEqual(row["after_datetime"], qa.WALLCLOCK_AT_PLUS0900,
                         "再実行で日時がずれている")


if __name__ == "__main__":
    unittest.main()
