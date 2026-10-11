"""--help が、README に書いた option をすべて含む。

**README が英語版と日本語版に分かれたのに合わせて直した。**
**要求そのもの（option 表と `--help` の一致）は 1 つも変えていない。**
確認の対象が `README.md`（英語版）と `README.ja.md`（日本語版）の 2 つになった。

**断り書きの確認（要求ではなく記録）も、両方の版に対して行う。** 語は英語版の
言い回しに合わせ、同じ内容を日本語版にも求めている。**`exiftool` の 1 語だけは、
求める側から「書かれていないこと」を求める側へ変えた**——無料の代替手段に
ついての記述を README から外す、と決まったためである。
"""

import contextlib
import io
import os
import re
import unittest

import qasupport as qa
from phototime import cli

README = os.path.join(qa.PRODUCT_ROOT, "README.md")
README_JA = os.path.join(qa.PRODUCT_ROOT, "README.ja.md")

# README の option 表の 1 列目から `--xxx` を拾う。
_TABLE_OPTION = re.compile(r"^\|\s*`(--[a-z-]+)[^`]*`\s*\|")


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def flat(path):
    """改行の位置に左右されないように、空白を 1 つに潰した本文。"""
    return re.sub(r"\s+", " ", read_text(path))


def readme_options(path=README):
    options = []
    for line in read_text(path).splitlines():
        match = _TABLE_OPTION.match(line.strip())
        if match:
            options.append(match.group(1))
    return options


def help_text():
    buffer = io.StringIO()
    parser = cli.build_parser()
    with contextlib.redirect_stdout(buffer):
        parser.print_help()
    return buffer.getvalue()


def help_options(text):
    return set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", text))


class HelpMatchesReadme(unittest.TestCase):

    def setUp(self):
        self.readme = readme_options()
        self.help = help_text()

    def test_readme_lists_options(self):
        self.assertGreaterEqual(len(self.readme), 10,
                                "README の option 表を読み取れていない: %r"
                                % self.readme)

    def test_help_contains_every_readme_option(self):
        missing = [name for name in self.readme if name not in self.help]
        self.assertEqual(missing, [],
                         "README にあるが --help に無い option")

    def test_readme_contains_every_help_option(self):
        """逆向きも確かめる（README が古くなっていないこと）。"""
        declared = set()
        for action in cli.build_parser()._actions:
            declared.update(opt for opt in action.option_strings
                            if opt.startswith("--"))
        missing = sorted(declared - set(self.readme))
        self.assertEqual(missing, [],
                         "--help にあるが README に無い option")

    def test_help_runs_through_main_and_exits_zero(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--shift", buffer.getvalue())

    def test_help_mentions_that_default_is_dry_run(self):
        self.assertIn("dry-run", self.help)

    def test_both_readmes_declare_the_same_option_names(self):
        """**英語版と日本語版で option 名が同じ**（確認を 2 つの版に広げる）。"""
        self.assertEqual(sorted(readme_options(README_JA)), sorted(self.readme),
                         "README.md と README.ja.md で option 名が違う")

    def test_readme_states_the_undertakings_qa_depends_on(self):
        """英語版が、書くと決めた断り書きを含むこと（要求ではないが記録する）。"""
        body = flat(README)
        for phrase in ("not affiliated",
                       "has not been confirmed",       # 旧「確認していません」
                       "Not available yet",            # 旧「準備中」
                       "time zone database of the operating system",
                       "recommended",
                       "two or more EXIF APP1",        # 受け入れない構造
                       "AI assistance",                # 書くと決めた表示
                       "MIT"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_japanese_readme_states_the_same_undertakings(self):
        """**同じ内容を日本語版にも求める**（確認が 2 倍になっており、緩めていない）。"""
        body = flat(README_JA)
        for phrase in ("not affiliated",
                       "確認していません",
                       "準備中",
                       "OS の時刻帯 database",
                       "推奨",
                       "APP1 segment が 2 つ以上ある JPEG",
                       "AI（Anthropic の Claude）の支援",
                       "MIT"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, body)

    def test_readmes_link_to_each_other(self):
        self.assertIn("README.ja.md", read_text(README))
        self.assertIn("README.md", read_text(README_JA))

    def test_no_unverified_comparison(self):
        """確かめていない比較を書かない。"""
        for path in (README, README_JA):
            body = flat(path).lower()
            for phrase in ("the only", "the first", "better than"):
                with self.subTest(path=os.path.basename(path), phrase=phrase):
                    self.assertNotIn(phrase, body)

    def test_free_alternatives_are_not_mentioned(self):
        """無料の代替手段についての記述を、**両方の版から外す**こと。

        **これは以前とは期待値の向きが逆である。** 当時は「無料の代替手段が
        既にあることを、こちらから先に書く」ことが求められており、
        `exiftool` の語が**あること**を確かめていた。**その条件は
        取り消された。**
        """
        for path in (README, README_JA):
            with self.subTest(path=os.path.basename(path)):
                self.assertNotIn("exiftool", flat(path).lower(),
                                 "外すと決めた記述が残っている")


if __name__ == "__main__":
    unittest.main()
