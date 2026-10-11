"""`--help` が、README に書いた option をすべて含む。

逆向き（`--help` にあって README に無い option が無いこと）も確かめる。
README が公開時の唯一の説明であり、食い違えば利用者は誤った option を打つ。
"""

import os
import re
import unittest

import support
from phototime import cli

README = os.path.join(support.PRODUCT_ROOT, "README.md")
README_JA = os.path.join(support.PRODUCT_ROOT, "README.ja.md")

_OPTION_PATTERN = re.compile(r"--[a-z][a-z0-9-]*")


def _options_in(text):
    return set(_OPTION_PATTERN.findall(text))


class HelpAndReadmeAgree(unittest.TestCase):

    def setUp(self):
        with open(README, "r", encoding="utf-8") as handle:
            self.readme = handle.read()
        self.help_text = cli.build_parser().format_help()

    def test_readme_lists_at_least_the_known_options(self):
        """README 側の走査が空振りでないことを先に確かめる。"""
        found = _options_in(self.readme)
        for option in ("--apply", "--dry-run", "--report", "--shift",
                       "--assume-tz", "--undo", "--journal"):
            self.assertIn(option, found)

    def test_help_contains_every_option_in_the_readme(self):
        missing = sorted(_options_in(self.readme) - _options_in(self.help_text))
        self.assertEqual(missing, [],
                         "README にあるが --help に無い option")

    def test_readme_contains_every_option_in_the_help(self):
        missing = sorted(_options_in(self.help_text) - _options_in(self.readme))
        self.assertEqual(missing, [],
                         "--help にあるが README に無い option")

    def test_both_readmes_list_the_same_options(self):
        """英語版と日本語版で option 名が食い違わないこと。"""
        with open(README_JA, "r", encoding="utf-8") as handle:
            readme_ja = handle.read()
        self.assertEqual(_options_in(self.readme), _options_in(readme_ja))


class ReadmeStatesWhatIsUnverified(unittest.TestCase):
    """README に必ず書くと決めた記載が、両方の版にあること。

    `README.md` が英語版、`README.ja.md` が日本語版である。**同じことを両方の版に
    求める。**
    """

    def setUp(self):
        with open(README, "r", encoding="utf-8") as handle:
            self.readme = handle.read()
        with open(README_JA, "r", encoding="utf-8") as handle:
            self.readme_ja = handle.read()

    def test_mentions_that_sidecar_reading_is_unverified(self):
        self.assertIn("XMP sidecar", self.readme)
        self.assertIn("has not been confirmed", self.readme)
        self.assertIn("確認していません", self.readme_ja)

    def test_does_not_mention_free_alternatives(self):
        """**無料の代替手段に、自分から触れない。**

        聞かれたら答えるが、README から持ち出すことはしない。
        """
        for body in (self.readme, self.readme_ja):
            self.assertNotIn("exiftool", body)
            self.assertNotIn("置き換わるものではありません", body)

    def test_makes_no_unverified_comparison(self):
        """確かめていない比較を書かない。"""
        for body in (self.readme, self.readme_ja):
            lowered = body.lower()
            for phrase in ("the only", "the first", "better than", "fastest",
                           "唯一", "初めての", "より優れ"):
                self.assertNotIn(phrase, lowered)

    def test_mentions_the_timezone_database_dependency(self):
        self.assertIn("time zone\ndatabase of the operating system", self.readme)
        self.assertIn("OS の時刻帯 database", self.readme_ja)

    def test_states_it_is_not_affiliated(self):
        self.assertIn("not affiliated with", self.readme)
        self.assertIn("not affiliated with", self.readme_ja)

    def test_does_not_promise_support(self):
        self.assertIn("No promise of support", self.readme)
        self.assertNotIn("issue には必ず答えます", self.readme_ja)

    def test_paid_part_has_no_price_or_date(self):
        self.assertIn("Not available yet", self.readme)
        self.assertIn("準備中", self.readme_ja)

    def test_states_that_ai_assistance_was_used(self):
        """AI 支援の表示。"""
        self.assertIn("written with AI assistance", self.readme)
        self.assertIn("AI（Anthropic の Claude）の支援", self.readme_ja)

    def test_the_two_readmes_link_to_each_other(self):
        self.assertIn("README.ja.md", self.readme)
        self.assertIn("README.md", self.readme_ja)

    def test_both_readmes_state_the_two_exif_app1_limitation(self):
        """EXIF の APP1 が 2 つ以上ある JPEG を扱わないことを、既知の制限に書く。"""
        self.assertIn("two or more EXIF APP1 segments is skipped", self.readme)
        self.assertIn("EXIF の APP1 segment が 2 つ以上ある JPEG は skip",
                      self.readme_ja)


if __name__ == "__main__":
    unittest.main()
