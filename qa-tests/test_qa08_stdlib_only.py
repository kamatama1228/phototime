"""外部 package を 1 つも import していない。

Builder の test に頼らず、QA 側で改めて全 `.py` を AST で走査する。
"""

import ast
import os
import sys
import unittest

import qasupport as qa

PACKAGE_DIR = os.path.join(qa.PRODUCT_ROOT, "phototime")
OWN_MODULES = {"phototime"}


def iter_sources(directory):
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = [name for name in sorted(dirnames)
                       if name != "__pycache__"]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield os.path.join(current, name)


def top_level_imports(path):
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 相対 import は自分自身
                names.add("phototime")
            elif node.module:
                names.add(node.module.split(".")[0])
    return names


class StdlibOnly(unittest.TestCase):

    def test_package_directory_exists(self):
        self.assertTrue(os.path.isdir(PACKAGE_DIR))
        self.assertTrue(list(iter_sources(PACKAGE_DIR)), "走査対象が 0 件")

    def test_every_import_is_stdlib_or_own(self):
        allowed = set(sys.stdlib_module_names) | OWN_MODULES
        offenders = {}
        for path in iter_sources(PACKAGE_DIR):
            bad = sorted(top_level_imports(path) - allowed)
            if bad:
                offenders[os.path.relpath(path, qa.PRODUCT_ROOT)] = bad
        self.assertEqual(offenders, {}, "標準 library 以外の import がある")

    def test_no_dynamic_import_of_unknown_modules(self):
        """`__import__` / `importlib` で抜け道を作っていないこと。"""
        offenders = []
        for path in iter_sources(PACKAGE_DIR):
            with open(path, "r", encoding="utf-8") as handle:
                body = handle.read()
            if "__import__(" in body or "importlib" in body:
                offenders.append(os.path.relpath(path, qa.PRODUCT_ROOT))
        self.assertEqual(offenders, [])

    def test_no_subprocess_or_shell_use(self):
        """外部 command を呼んでいないこと（exiftool 等への依存が無いこと）。"""
        forbidden = {"subprocess", "shutil"}
        offenders = {}
        for path in iter_sources(PACKAGE_DIR):
            found = sorted(top_level_imports(path) & forbidden)
            if found:
                offenders[os.path.relpath(path, qa.PRODUCT_ROOT)] = found
        self.assertEqual(offenders, {})

    def test_package_imports_cleanly(self):
        """実際に import できること（宣言だけでなく実行も確かめる）。"""
        import importlib

        for name in ("phototime", "phototime.cli", "phototime.exifio",
                     "phototime.journal", "phototime.plan", "phototime.report",
                     "phototime.runner", "phototime.sources", "phototime.tzpolicy",
                     "phototime.xmp"):
            importlib.import_module(name)


if __name__ == "__main__":
    unittest.main()
