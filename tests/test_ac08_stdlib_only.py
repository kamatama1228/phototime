"""外部 package を 1 つも import していない。

実装は Python 標準 library だけで動く。

source を `ast` で走査し、標準 library と first-party 以外の import が 0 件で
あることを確かめる。
"""

import ast
import os
import sys
import unittest

import support

def _first_party_names():
    """`phototime` package と、`tests/` にある module 名。"""
    names = {"phototime"}
    tests_dir = os.path.join(support.PRODUCT_ROOT, "tests")
    for name in os.listdir(tests_dir):
        if name.endswith(".py"):
            names.add(name[:-3])
    return names

# `sys.stdlib_module_names` が無い環境（Python 3.9 以前）のための控え。
_FALLBACK_STDLIB = {
    "argparse", "ast", "base64", "csv", "datetime", "hashlib", "io", "json",
    "os", "re", "shutil", "socket", "struct", "sys", "tempfile", "unittest",
    "xml", "zoneinfo",
}


def _stdlib_names():
    names = getattr(sys, "stdlib_module_names", None)
    return set(names) if names else _FALLBACK_STDLIB


def _python_files():
    for directory in (os.path.join(support.PRODUCT_ROOT, "phototime"),
                      os.path.join(support.PRODUCT_ROOT, "tests")):
        for name in sorted(os.listdir(directory)):
            if name.endswith(".py"):
                yield os.path.join(directory, name)


def _top_level_imports(path):
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相対 import は first-party
                continue
            if node.module:
                found.add(node.module.split(".")[0])
    return found


class OnlyStandardLibraryIsImported(unittest.TestCase):

    def test_no_third_party_imports(self):
        allowed = _stdlib_names() | _first_party_names()
        offenders = {}
        checked = 0
        for path in _python_files():
            checked += 1
            outside = sorted(_top_level_imports(path) - allowed)
            if outside:
                offenders[os.path.relpath(path, support.PRODUCT_ROOT)] = outside
        self.assertGreater(checked, 0, "走査した file が 0 件（test が無意味）")
        self.assertEqual(offenders, {}, "標準 library 以外を import している")

    def test_the_scan_would_actually_catch_something(self):
        """走査そのものが機能していることを、作った source で確かめる。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.py")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("import requests\nfrom numpy import array\n")
            self.assertEqual(_top_level_imports(path), {"requests", "numpy"})


if __name__ == "__main__":
    unittest.main()
