"""network に 1 回も接続しない。

socket の生成そのものを禁止した状態で、dry-run / --apply / --undo の
全経路を通す。あわせて、network に関わる module を import していないことも
静的に確かめる。
"""

import ast
import os
import socket
import tempfile
import unittest

import qasupport as qa

NETWORK_MODULES = {
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "telnetlib",
    "xmlrpc", "asyncio", "requests", "httpx", "webbrowser", "poplib",
    "imaplib", "socketserver", "ipaddress", "email",
}


class NetworkIsForbidden(unittest.TestCase):
    """socket を一切作れない状態で、全経路を実行する。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")
        self.report = os.path.join(self.outside, "plan.csv")

        photo = os.path.join(self.root, "photo.jpg")
        qa.write(photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(photo, qa.EPOCH_20230504)
        qa.write(os.path.join(self.root, "20230504_123456.jpg"),
                 qa.build_jpeg(exif=None), mtime=1000000001)
        qa.write(os.path.join(self.root, "broken.jpg"), b"\xff\xd8\x00",
                 mtime=1000000002)

        self.attempts = []
        self.saved = {}
        for name in ("socket", "create_connection", "socketpair", "getaddrinfo",
                     "gethostbyname"):
            self.saved[name] = getattr(socket, name)
            setattr(socket, name, self._tripwire(name))
        self.addCleanup(self._restore)

    def _restore(self):
        for name, original in self.saved.items():
            setattr(socket, name, original)

    def _tripwire(self, name):
        def blocked(*args, **kwargs):
            self.attempts.append(name)
            raise AssertionError("network に接続しようとした: socket.%s" % name)
        return blocked

    def test_dry_run_makes_no_socket(self):
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--report", self.report])
        self.assertEqual(code, 0)
        self.assertEqual(self.attempts, [])

    def test_apply_and_undo_make_no_socket(self):
        code, _out, _err = qa.run_cli(
            [self.root, "--shift", "+09:00", "--apply", "--rename",
             "--journal", self.journal])
        self.assertEqual(code, 0)
        code, _out, _err = qa.run_cli(["--undo", self.journal])
        self.assertEqual(code, 0)
        self.assertEqual(self.attempts, [])

    def test_assume_tz_makes_no_socket(self):
        qa.run_cli([self.root, "--assume-tz", "Asia/Tokyo",
                    "--report", self.report])
        self.assertEqual(self.attempts, [])


class NoNetworkImports(unittest.TestCase):

    def test_sources_do_not_import_network_modules(self):
        package = os.path.join(qa.PRODUCT_ROOT, "phototime")
        offenders = {}
        for current, dirnames, filenames in os.walk(package):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(current, name)
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
                found = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            found.add(alias.name.split(".")[0])
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        found.add(node.module.split(".")[0])
                bad = sorted(found & NETWORK_MODULES)
                if bad:
                    offenders[name] = bad
        self.assertEqual(offenders, {})


if __name__ == "__main__":
    unittest.main()
