"""tag が無い JPEG では EXIF を変えず、.xmp を作り、警告して終了 code 0。"""

import os
import tempfile
import unittest

import qasupport as qa


def assert_no_add_warning(case, err):
    """「tag は追加しない」「XMP sidecar に書く」の 2 つの事実が、警告に出ていること。

    出力は英語になったため、語そのものではなく**述べている事実**で確かめる。
    AC が求める事実（警告が出ること・追加しないこと・sidecar に逃がすこと）は
    1 つも落としていない。
    """
    low = err.lower()
    case.assertIn("warning", low, "警告が 1 つも出ていない: %r" % (err,))
    case.assertIn("does not add tags", low,
                  "「tag を追加しない」旨が警告に無い: %r" % (err,))
    case.assertIn("xmp sidecar", low,
                  "「XMP sidecar に書く」旨が警告に無い: %r" % (err,))


class MissingTagGoesToXmp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")

    def test_no_exif_at_all(self):
        """EXIF 自体が無い JPEG（file 名が情報源）。"""
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.build_jpeg(exif=None), mtime=1000000000)
        before = qa.read_file(path)

        code, _out, err = qa.run_cli([self.root, "--apply",
                                      "--journal", self.journal])
        self.assertEqual(code, 0)
        self.assertEqual(qa.read_file(path), before,
                         "tag が無い file の EXIF が変更されている")
        self.assertTrue(os.path.isfile(path + ".xmp"), ".xmp が作られていない")
        assert_no_add_warning(self, err)

        body = open(path + ".xmp", "r", encoding="utf-8").read()
        self.assertIn("2023-05-04T12:34:56", body)

    def test_exif_present_but_datetime_tag_absent(self):
        """APP1 はあるが DateTimeOriginal tag が無い JPEG。"""
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.plain_jpeg(with_datetime=False, with_offset=False),
                 mtime=1000000000)
        before = qa.read_file(path)

        code, _out, err = qa.run_cli([self.root, "--apply",
                                      "--journal", self.journal])
        self.assertEqual(code, 0)
        self.assertEqual(qa.read_file(path), before)
        self.assertTrue(os.path.isfile(path + ".xmp"))
        assert_no_add_warning(self, err)

    def test_offset_tag_absent_goes_to_xmp_too(self):
        """DateTimeOriginal はあるが OffsetTimeOriginal tag が無い場合。"""
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", with_offset=False),
                 mtime=1000000000)

        code, _out, err = qa.run_cli([self.root, "--shift", "+09:00", "--apply",
                                      "--journal", self.journal])
        self.assertEqual(code, 0)
        values = qa.exif_of(path)
        self.assertEqual(values[qa.TAG_DATETIME_ORIGINAL],
                         qa.WALLCLOCK_AT_PLUS0900)
        self.assertNotIn(qa.TAG_OFFSET_TIME_ORIGINAL, values,
                         "存在しない tag を新規に追加している（Non-goals 違反）")
        self.assertTrue(os.path.isfile(path + ".xmp"))
        assert_no_add_warning(self, err)

    def test_no_xmp_option_suppresses_sidecar(self):
        """--no-xmp を付けたときは sidecar を作らない。"""
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.build_jpeg(exif=None), mtime=1000000000)
        before = qa.snapshot(self.root)

        code, _out, _err = qa.run_cli([self.root, "--apply", "--no-xmp",
                                       "--journal", self.journal])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(path + ".xmp"))
        self.assertEqual(qa.snapshot(self.root), before)

    def test_xmp_is_well_formed_xml(self):
        """作った sidecar が XML として読めること。"""
        from xml.dom import minidom

        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.build_jpeg(exif=None), mtime=1000000000)
        qa.run_cli([self.root, "--apply", "--journal", self.journal])
        body = open(path + ".xmp", "r", encoding="utf-8").read()
        start = body.index("<x:xmpmeta")
        end = body.index("</x:xmpmeta>") + len("</x:xmpmeta>")
        minidom.parseString(body[start:end])


if __name__ == "__main__":
    unittest.main()
