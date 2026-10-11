"""network に 1 回も接続しない。

2 つの側面から確かめる。

1. **静的**: network 関連の標準 library を、実装が 1 つも import していない。
2. **動的**: `--apply` を含む一連の実行の間、socket の生成を禁止する。
   触れただけで fail する。
"""

import os
import socket
import tempfile
import unittest
from unittest import mock

import support
from test_ac08_stdlib_only import _python_files, _top_level_imports

NETWORK_MODULES = {
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "poplib",
    "imaplib", "telnetlib", "xmlrpc", "asyncio", "socketserver",
    "webbrowser", "requests", "urllib3",
}

EPOCH = 1683170096


class NoNetworkAccess(unittest.TestCase):

    def test_implementation_does_not_import_network_modules(self):
        package = os.path.join(support.PRODUCT_ROOT, "phototime")
        offenders = {}
        for path in _python_files():
            if not path.startswith(package):
                continue  # test 側（本 file）は socket を意図して import する
            found = sorted(_top_level_imports(path) & NETWORK_MODULES)
            if found:
                offenders[os.path.basename(path)] = found
        self.assertEqual(offenders, {})

    def test_no_socket_is_created_during_a_full_run(self):
        with tempfile.TemporaryDirectory() as root, \
                tempfile.TemporaryDirectory() as out:
            jpeg = os.path.join(root, "IMG_0001.jpg")
            support.write_jpeg(jpeg)
            support.write_sidecar(jpeg, EPOCH)
            support.write_jpeg(os.path.join(root, "20230504_121456.jpg"),
                               datetime_original=None, offset_time_original=None)
            journal = os.path.join(out, "journal.json")
            report = os.path.join(out, "report.csv")

            def forbidden(*args, **kwargs):
                raise AssertionError("network に接続しようとした")

            with mock.patch.object(socket, "socket", forbidden), \
                    mock.patch.object(socket, "create_connection", forbidden), \
                    mock.patch.object(socket, "getaddrinfo", forbidden):
                applied = support.run_cli([root, "--shift", "+09:00", "--apply",
                                           "--journal", journal,
                                           "--report", report])
                undone = support.run_cli(["--undo", journal])

            self.assertEqual(applied.code, 0, applied.err)
            self.assertEqual(undone.code, 0, undone.err)

    def test_the_guard_would_actually_fire(self):
        """guard 自体が効いていることを確かめる（空振りの test にしない）。"""
        def forbidden(*args, **kwargs):
            raise AssertionError("network に接続しようとした")

        with mock.patch.object(socket, "socket", forbidden):
            with self.assertRaises(AssertionError):
                socket.socket()


if __name__ == "__main__":
    unittest.main()
