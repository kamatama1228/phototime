"""既定では file が 1 byte も変わらず、新しい file も作られない。"""

import os
import tempfile
import unittest

import qasupport as qa


class DefaultIsReadOnly(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

        # 情報源・種別・正常／異常が混ざった directory を作る。
        photo = os.path.join(self.root, "photo.jpg")
        qa.write(photo, qa.plain_jpeg(), mtime=1000000000)
        qa.write_sidecar(photo, qa.EPOCH_20230504)

        qa.write(os.path.join(self.root, "20230504_123456.jpg"),
                 qa.plain_jpeg(with_datetime=False, with_offset=False),
                 mtime=1000000001)
        qa.write(os.path.join(self.root, "trip.jpg"),
                 qa.plain_jpeg("2019:08:01 07:00:00", "+02:00"),
                 mtime=1000000002)
        qa.write(os.path.join(self.root, "broken.jpg"), b"\xff\xd8\x00\x01\x02",
                 mtime=1000000003)
        qa.write(os.path.join(self.root, "empty.jpg"), b"", mtime=1000000004)
        qa.write(os.path.join(self.root, "note.txt"), b"not an image\n",
                 mtime=1000000005)

        self.before = qa.snapshot(self.root)

    def assert_untouched(self, argv):
        code, out, _err = qa.run_cli(argv)
        self.assertEqual(code, 0, "終了 code 0 のはず: %r" % (argv,))
        after = qa.snapshot(self.root)
        self.assertEqual(
            sorted(after), sorted(self.before),
            "新しい file が作られた、または file が消えた: %r" % (argv,))
        self.assertEqual(after, self.before,
                         "SHA256 または mtime が変わった: %r" % (argv,))
        return out

    def test_bare_run_changes_nothing(self):
        out = self.assert_untouched([self.root])
        self.assertIn("DRY RUN", out)

    def test_dry_run_flag_changes_nothing(self):
        self.assert_untouched([self.root, "--dry-run"])

    def test_with_shift_still_changes_nothing(self):
        """--shift を与えても、--apply が無ければ何も変えない。"""
        self.assert_untouched([self.root, "--shift", "+09:00"])

    def test_with_rename_and_xmp_options_still_changes_nothing(self):
        """書き換え側の option を全部付けても、--apply が無ければ変えない。"""
        self.assert_untouched(
            [self.root, "--shift", "+09:00", "--rename", "--recursive"])

    def test_no_file_count_change_in_subdirectory(self):
        """下位 directory を作っても、既定の実行では件数が増えない。"""
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        qa.write(os.path.join(sub, "deep.jpg"), qa.plain_jpeg(), mtime=1000000006)
        self.before = qa.snapshot(self.root)
        self.assert_untouched([self.root, "--recursive", "--shift", "+09:00"])


if __name__ == "__main__":
    unittest.main()
