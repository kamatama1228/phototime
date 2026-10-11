"""利用者に見える出力が、すべて英語であること。

**QA 側で独立に書いた。実装側の同じ主題の test（`tests/` にある）は
読み込んでいない。** 日本語の判定も、出力の採り方も、ここで別に実装する。

この file だけは、**subprocess で `python3 -m phototime` を起動する**。
理由は 2 つある。

1. **利用者が実際に受け取る画面を見るため。** 同じ process の中で `cli.main`
   を呼ぶと、`--help` と `--version` が `SystemExit` になり、argparse が
   本物の標準出力に書いてしまうため、全文を押さえられない。
2. **出力の確認を、製品の内部に触らずに行うため。**

「変えてはいけない」と定められたもの（option 名・CSV の列名・action と
reason の値・表の列見出し・終了 code）も、同じ file の中で確かめる。
文言を英語にする過程で壊れていないことを、合格の条件に含める。
"""

import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest

import qasupport as qa
import qastructures

PRODUCT_ROOT = qa.PRODUCT_ROOT

# 日本語とみなす符号位置の範囲（QA が独自に置いた）。
#   ひらがな・カタカナ・半角カタカナ・CJK 統合漢字（拡張 A を含む）・
#   CJK の約物（、。「」〜 など）・全角の英数と記号（＝ ％ など）
_JAPANESE_RANGES = (
    (0x3000, 0x303F),   # CJK の約物
    (0x3040, 0x309F),   # ひらがな
    (0x30A0, 0x30FF),   # カタカナ
    (0x3400, 0x4DBF),   # CJK 統合漢字 拡張 A
    (0x4E00, 0x9FFF),   # CJK 統合漢字
    (0xFF01, 0xFF60),   # 全角形
    (0xFF66, 0xFF9D),   # 半角カタカナ
)


def japanese_characters(text):
    """`text` に含まれる日本語の文字を、出てきた順に返す（重複は除く）。"""
    found = []
    for char in text:
        point = ord(char)
        for low, high in _JAPANESE_RANGES:
            if low <= point <= high:
                if char not in found:
                    found.append(char)
                break
    return found


def run_module(argv, cwd=None):
    """`python3 -m phototime` を subprocess で起動する。

    戻り値は (終了 code, 標準出力, 標準エラー)。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = PRODUCT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", "phototime"] + [str(a) for a in argv],
        cwd=cwd or PRODUCT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return (completed.returncode,
            completed.stdout.decode("utf-8"),
            completed.stderr.decode("utf-8"))


class _EnglishAssertions(unittest.TestCase):

    def assert_english(self, text, label):
        found = japanese_characters(text)
        self.assertEqual(
            found, [],
            "%s に日本語の文字がある: %r\n--- 全文 ---\n%s"
            % (label, found, text))

    def assert_says_something(self, text, label):
        """「空だから日本語が無い」で通ってしまうのを防ぐ。"""
        self.assertTrue(text.strip(), "%s が空である" % label)


class TheDetectorItself(_EnglishAssertions):
    """判定器に歯があることを先に示す（negative control）。"""

    def test_it_catches_every_kind_of_japanese(self):
        for sample in ("ひらがな", "カタカナ", "漢字", "中止", "警告",
                       "対象 3 件", "、", "。", "「」", "ｶﾅ", "＝"):
            with self.subTest(sample=sample):
                self.assertTrue(japanese_characters(sample),
                                "%r を日本語と判定できていない" % sample)

    def test_it_accepts_what_the_tool_actually_prints(self):
        for sample in ("Aborted: the --report path is inside",
                       "DRY RUN: no file is changed (pass --apply to write)",
                       "3 files / skipped 1 / would_update 2",
                       "path  source  source_kind  action  reason",
                       "2023:05:04 12:34:56  +09:00", ""):
            with self.subTest(sample=sample):
                self.assertEqual(japanese_characters(sample), [])


class HelpIsEnglish(_EnglishAssertions):
    """求められた確認の 1 つ目: `--help` の全文。"""

    def test_help_has_no_japanese(self):
        code, out, err = run_module(["--help"])
        self.assertEqual(code, 0, err)
        self.assert_says_something(out, "--help の標準出力")
        self.assert_english(out, "--help の標準出力")
        self.assert_english(err, "--help の標準エラー")

    def test_short_help_is_the_same_text(self):
        _code, long_out, _e = run_module(["--help"])
        code, short_out, _err = run_module(["-h"])
        self.assertEqual(code, 0)
        self.assertEqual(short_out, long_out)

    def test_version_is_english(self):
        code, out, err = run_module(["--version"])
        self.assertEqual(code, 0, err)
        self.assert_says_something(out + err, "--version の出力")
        self.assert_english(out + err, "--version の出力")

    def test_argparse_own_error_is_english(self):
        """argparse 自身が出す使い方の誤りも、利用者に見える出力である。"""
        code, out, err = run_module(["--no-such-option"])
        self.assertEqual(code, 2)
        self.assert_says_something(err, "未知の option への応答")
        self.assert_english(out + err, "未知の option への応答")

    def test_help_still_states_the_two_facts_it_has_to(self):
        """英語にしても、述べるべき事実を落としていないこと。"""
        _code, out, _err = run_module(["--help"])
        low = out.lower()
        self.assertIn("dry run", low, "既定が dry run であることが --help に無い")
        for word in ("guess", "--shift", "--assume-tz"):
            self.assertIn(word, low,
                          "オフセットを推定しない旨の記述が崩れている: %r" % word)


class OptionNamesAreUnchanged(_EnglishAssertions):
    """変えてはいけないもの: option 名 13 件。"""

    EXPECTED = [
        "--apply", "--dry-run", "--report", "--shift", "--assume-tz",
        "--recursive", "--no-xmp", "--no-mtime", "--rename", "--journal",
        "--undo", "--version", "--help",
    ]

    def test_help_lists_exactly_these_option_names(self):
        _code, out, _err = run_module(["--help"])
        present = set(re.findall(r"--[a-z][a-z0-9-]*", out))
        for name in self.EXPECTED:
            self.assertIn(name, present, "option が --help から消えた: %s" % name)
        extra = present - set(self.EXPECTED)
        self.assertEqual(extra, set(),
                         "見覚えのない option が増えている: %r" % (extra,))


class AbortsAreEnglish(_EnglishAssertions):
    """求められた確認の 2 つ目: 中止の message。**終了 code は変えない。**"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        photo = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        self.before = qa.snapshot(self.root)

    def check_abort(self, argv, label):
        code, out, err = run_module(argv)
        self.assertEqual(code, 2, "%s: 終了 code 2 で中止するはず (%r)"
                         % (label, err))
        self.assert_says_something(err, "%s の標準エラー" % label)
        self.assert_english(out + err, "%s の出力" % label)
        self.assertIn("aborted", err.lower(),
                      "%s: 中止したことを述べていない: %r" % (label, err))
        self.assertEqual(qa.snapshot(self.root), self.before,
                         "%s: 中止したのに対象 directory が変わった" % label)
        return err

    def test_malformed_shift(self):
        # **利用者が打ち込んだ値そのものは、この test の対象外である。**
        # 中止の message は入力をそのまま引用する（`--shift 9時間` と打てば
        # 日本語が出る）。それは製品の文言ではないため、ASCII の誤入力で見る。
        err = self.check_abort([self.root, "--shift", "9h"], "--shift の形式誤り")
        self.assertIn("--shift", err)

    def test_malformed_shift_quotes_what_the_user_typed(self):
        """引用部分は入力のままであること（英語化で消されていないこと）。"""
        code, _out, err = run_module([self.root, "--shift", "9h"])
        self.assertEqual(code, 2)
        self.assertIn("9h", err, "入力した値が引用されていない: %r" % err)

    def test_unresolvable_assume_tz(self):
        err = self.check_abort([self.root, "--assume-tz", "Not/AZone"],
                               "--assume-tz の解決失敗")
        self.assertIn("--assume-tz", err)
        self.assertIn("--shift", err,
                      "--shift を使うよう案内していない: %r" % err)

    def test_report_inside_target(self):
        err = self.check_abort(
            [self.root, "--report", os.path.join(self.root, "plan.csv")],
            "--report が対象の内側")
        self.assertIn("--report", err)

    def test_journal_cannot_be_created(self):
        """journal を作れない場合（存在しない directory の下を指す）。"""
        err = self.check_abort(
            [self.root, "--shift", "+09:00", "--apply",
             "--journal", os.path.join(self.outside, "nope", "undo.json")],
            "journal を作れない")
        self.assertIn("journal", err.lower())

    def test_journal_inside_target(self):
        self.check_abort(
            [self.root, "--shift", "+09:00", "--apply",
             "--journal", os.path.join(self.root, "undo.json")],
            "--journal が対象の内側")

    def test_other_aborts_are_english_too(self):
        """名指しされた 4 つ以外の中止も、同じ画面に出る。"""
        cases = [
            ([], "directory を省いた"),
            ([os.path.join(self.outside, "nope")], "存在しない directory"),
            ([os.path.join(self.root, "20230504_123456.jpg")], "file を指した"),
            ([self.root, "--apply", "--dry-run"], "--apply と --dry-run"),
            ([self.root, "--shift", "+09:00",
              "--assume-tz", "UTC"], "--shift と --assume-tz"),
            (["--undo", os.path.join(self.outside, "missing.json")],
             "journal が無い --undo"),
        ]
        for argv, label in cases:
            with self.subTest(label=label):
                code, out, err = run_module(argv)
                self.assertEqual(code, 2, "%s: 終了 code が 2 でない" % label)
                self.assert_says_something(err, "%s の標準エラー" % label)
                self.assert_english(out + err, "%s の出力" % label)


class WarningsAreEnglish(_EnglishAssertions):
    """求められた確認の 3 つ目: 警告文。**述べるべき事実を保っていること。**"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")

    def test_datetime_tag_absent_warning(self):
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.build_jpeg(exif=None), mtime=1000000000)
        before = qa.read_file(path)

        code, out, err = run_module([self.root, "--apply",
                                     "--journal", self.journal])
        self.assertEqual(code, 0, err)
        self.assert_says_something(err, "tag が無い file の警告")
        self.assert_english(out + err, "tag が無い file の出力")

        low = err.lower()
        self.assertIn("warning", low)
        self.assertIn("does not add tags", low,
                      "「tag を追加しない」旨が英語の警告に無い: %r" % err)
        self.assertIn("xmp sidecar", low,
                      "「XMP sidecar に書く」旨が英語の警告に無い: %r" % err)
        # 「EXIF を変えず sidecar を作る」ことも、あわせて確かめる。
        self.assertEqual(qa.read_file(path), before, "EXIF が変更されている")
        self.assertTrue(os.path.isfile(path + ".xmp"), ".xmp が作られていない")

    def test_offset_tag_absent_warning(self):
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", with_offset=False),
                 mtime=1000000000)
        code, out, err = run_module([self.root, "--shift", "+09:00", "--apply",
                                     "--journal", self.journal])
        self.assertEqual(code, 0, err)
        self.assert_says_something(err, "offset tag が無い file の警告")
        self.assert_english(out + err, "offset tag が無い file の出力")
        low = err.lower()
        self.assertIn("does not add tags", low)
        self.assertIn("xmp sidecar", low)

    def test_interrupted_journal_warning(self):
        """末尾が欠けた journal を `--undo` したときの警告。"""
        for index in range(3):
            name = "2023050%d_120000.jpg" % (index + 1)
            qa.write(os.path.join(self.root, name),
                     qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                     mtime=1000000000)
        code, _out, err = run_module([self.root, "--shift", "+09:00", "--apply",
                                      "--journal", self.journal])
        self.assertEqual(code, 0, err)

        with open(self.journal, "rb") as handle:
            raw = handle.read()
        lines = raw.split(b"\n")
        torn = b"\n".join(lines[:-2]) + b"\n" + lines[-2][: len(lines[-2]) // 2]
        with open(self.journal, "wb") as handle:
            handle.write(torn)

        code, out, err = run_module(["--undo", self.journal])
        self.assertEqual(code, 0, err)
        self.assert_says_something(err, "途中で終わった journal の警告")
        self.assert_english(out + err, "途中で終わった journal の出力")
        self.assertIn("warning", err.lower())
        self.assertIn("journal", err.lower())

    def test_undo_completion_line(self):
        path = os.path.join(self.root, "20230504_123456.jpg")
        qa.write(path, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        run_module([self.root, "--shift", "+09:00", "--apply",
                    "--journal", self.journal])
        code, out, err = run_module(["--undo", self.journal])
        self.assertEqual(code, 0, err)
        self.assert_says_something(out, "--undo の完了行")
        self.assert_english(out + err, "--undo の出力")


class EveryScreenIsEnglish(_EnglishAssertions):
    """求められた確認の 4 つ目（dry-run の標準出力）を、広げたもの。

    **1 つの directory に、CSV に出得る action と reason をできる限り
    並べたうえで**、既定の実行・`--apply`・`--report`・`--rename`・
    `--recursive` の画面を一通り集め、**そのどれにも日本語が無いこと**を見る。
    名指しされた 4 か所だけを見ると、まだ日本語が残っている画面を
    取りこぼすため。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.outside = tempfile.mkdtemp()
        self.journal = os.path.join(self.outside, "undo.json")
        self.report = os.path.join(self.outside, "plan.csv")

        # (1) sidecar があり、offset の明示が要る file（instant）
        sidecar_photo = os.path.join(self.root, "sidecar.jpg")
        qa.write(sidecar_photo, qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        qa.write_sidecar(sidecar_photo, qa.EPOCH_20230504)
        # (2) file 名が情報源（wallclock）
        qa.write(os.path.join(self.root, "20230504_123456.jpg"),
                 qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)
        # (3) EXIF が無く、file 名も日時でない（mtime が情報源）
        qa.write(os.path.join(self.root, "nodate.jpg"),
                 qa.build_jpeg(exif=None), mtime=1000000000)
        # (4) 壊れた JPEG（skip される）
        qa.write(os.path.join(self.root, "broken.jpg"), b"not a jpeg at all",
                 mtime=1000000000)
        # (5) 空 file
        qa.write(os.path.join(self.root, "empty.jpg"), b"", mtime=1000000000)
        # (6) EXIF の APP1 が 2 つ（unsupported_structure）
        qa.write(os.path.join(self.root, "two_exif.jpg"),
                 qastructures.jpeg([qastructures.exif_app1(),
                                    qastructures.exif_app1()]),
                 mtime=1000000000)
        # (7) 下位 directory（--recursive のとき）
        os.makedirs(os.path.join(self.root, "sub"))
        qa.write(os.path.join(self.root, "sub", "20220101_000000.jpg"),
                 qa.plain_jpeg("2001:01:01 00:00:00", "+00:00"),
                 mtime=1000000000)

    def screens(self):
        """利用者が見得る画面を集める。(label, 終了 code, 全文) の列。"""
        runs = [
            ("既定（dry-run）", [self.root]),
            ("dry-run ＋ --shift", [self.root, "--shift", "+09:00"]),
            ("dry-run ＋ --assume-tz", [self.root, "--assume-tz", "UTC"]),
            ("--recursive", [self.root, "--recursive", "--shift", "+09:00"]),
            ("--report", [self.root, "--shift", "+09:00",
                          "--report", self.report]),
            ("--no-xmp ＋ --no-mtime",
             [self.root, "--shift", "+09:00", "--no-xmp", "--no-mtime"]),
            ("空の directory", [self.outside]),
        ]
        for label, argv in runs:
            code, out, err = run_module(argv)
            yield label, code, out + err

    def test_every_dry_run_screen_is_english(self):
        for label, code, text in self.screens():
            with self.subTest(label=label):
                self.assertEqual(code, 0, "%s: 終了 code 0 のはず" % label)
                self.assert_says_something(text, "%s の出力" % label)
                self.assert_english(text, "%s の出力" % label)

    def test_apply_rename_and_undo_screens_are_english(self):
        code, out, err = run_module(
            [self.root, "--shift", "+09:00", "--apply", "--rename",
             "--recursive", "--journal", self.journal])
        self.assertEqual(code, 0, err)
        self.assert_says_something(out, "--apply の標準出力")
        self.assert_english(out + err, "--apply の出力")

        code, out2, err2 = run_module(["--undo", self.journal])
        self.assertEqual(code, 0, err2)
        self.assert_says_something(out2, "--undo の標準出力")
        self.assert_english(out2 + err2, "--undo の出力")

    def test_dry_run_still_says_it_changes_nothing(self):
        """英語にしても、「変更しない」ことを述べ続けていること。"""
        before = qa.snapshot(self.root)
        code, out, _err = run_module([self.root, "--shift", "+09:00"])
        self.assertEqual(code, 0)
        self.assertIn("dry run", out.lower(),
                      "dry run である旨が標準出力に無い: %r" % out)
        self.assertIn("--apply", out,
                      "書き換えるには --apply が要る旨が無い: %r" % out)
        self.assertEqual(qa.snapshot(self.root), before,
                         "dry-run で対象 directory が変わった")

    def test_summary_line_still_counts(self):
        """集計行が英語になっても、件数を述べていること。"""
        code, out, _err = run_module([self.root, "--shift", "+09:00"])
        self.assertEqual(code, 0)
        last = [line for line in out.strip().splitlines() if line.strip()][-1]
        self.assert_english(last, "集計行")
        # 下位 directory は --recursive を付けない限り対象外。root 直下は 6 枚。
        top_level = len([n for n in os.listdir(self.root)
                         if os.path.isfile(os.path.join(self.root, n))
                         and not n.endswith(".json")])
        self.assertEqual(top_level, 6, "fixture の前提が崩れている")
        self.assertRegex(last, r"^6 files\b",
                         "集計行が対象の総数を述べていない: %r" % last)

    def test_table_headers_and_csv_columns_are_unchanged(self):
        """変えてはいけないもの: 表の列見出しと CSV の列名。

        **両者は別物である**（CSV は機械が読むため固定、標準出力の表は人が
        読むための短い見出し）。どちらももともと英語であり、どちらも
        変えないことが求められている。
        """
        code, out, _err = run_module([self.root, "--shift", "+09:00",
                                      "--report", self.report])
        self.assertEqual(code, 0)
        self.assertEqual(
            qa.read_csv_rows(self.report)[0],
            ["path", "source", "source_kind", "before_datetime",
             "after_datetime", "before_offset", "after_offset",
             "action", "reason"])

        header = [line for line in out.splitlines() if line.strip()][1]
        self.assertEqual(
            header.split(),
            ["file", "source", "kind", "before", "after", "offset",
             "action", "reason"],
            "標準出力の表の列見出しが変わった: %r" % header)

    def test_action_and_reason_values_are_unchanged(self):
        """変えてはいけないもの: action と reason の値。

        **値が英語の識別子のままであること**（文言の英語化に巻き込まれて
        文章になっていないこと）を、CSV の全行について見る。
        """
        code, _out, _err = run_module([self.root, "--recursive",
                                       "--report", self.report])
        self.assertEqual(code, 0)
        rows = qa.rows_by_name(self.report)
        observed_actions = set()
        observed_reasons = set()
        for name, row in rows.items():
            with self.subTest(file=name):
                self.assertRegex(row["action"], r"^[a-z][a-z_]*$",
                                 "action が識別子でない: %r" % row["action"])
                # CSV の reason は、理由が無いとき空欄である（以前からの
                # 挙動。表のほうは "-" を入れる）。空欄も識別子扱いで通す。
                self.assertRegex(row["reason"], r"^([a-z][a-z_]*)?$",
                                 "reason が識別子でない: %r" % row["reason"])
            observed_actions.add(row["action"])
            observed_reasons.add(row["reason"])

        # 既知の値だけが出ていること（新しい値を作っていないこと）。
        known_actions = {"would_update", "would_write_xmp", "skipped",
                         "updated", "wrote_xmp", "none", "no_change"}
        known_reasons = {"offset_required", "unsupported_structure",
                         "exif_tag_absent", "unreadable_jpeg", "no_source",
                         "no_change", "empty_file", "not_a_jpeg", "-", ""}
        self.assertTrue(observed_actions <= known_actions,
                        "見覚えのない action: %r" % (observed_actions
                                                     - known_actions,))
        self.assertTrue(observed_reasons <= known_reasons,
                        "見覚えのない reason: %r" % (observed_reasons
                                                     - known_reasons,))
        # fixture が本当に複数の経路を通っていること（test が無意味でないこと）。
        self.assertGreaterEqual(len(observed_reasons), 3,
                                "1 種類の経路しか通っていない: %r"
                                % (observed_reasons,))
        self.assertIn("offset_required", observed_reasons)
        self.assertIn("unsupported_structure", observed_reasons)


class NoJapaneseStringLiteralsInTheProduct(_EnglishAssertions):
    """**実行して出した画面だけでは、まだ足りない。**

    通らなかった経路の message には、日本語が残っていても気づけない。
    そこで、製品の全 module を構文木として読み、**docstring 以外の文字列
    定数**に日本語が無いことを見る。comment と docstring は対象外である
    （日本語のまま残してよいと決まっている）。

    名指しされた 5 file に限らず、`phototime/` の全 module を見る。
    """

    def source_files(self):
        package = os.path.join(PRODUCT_ROOT, "phototime")
        for name in sorted(os.listdir(package)):
            if name.endswith(".py"):
                yield os.path.join(package, name)

    def test_the_scan_sees_every_module(self):
        names = {os.path.basename(p) for p in self.source_files()}
        self.assertGreaterEqual(len(names), 9, "走査した module が少なすぎる")
        for expected in ("cli.py", "report.py", "runner.py", "journal.py",
                         "tzpolicy.py"):
            self.assertIn(expected, names)

    def test_no_japanese_in_any_string_literal(self):
        for path in self.source_files():
            with self.subTest(module=os.path.basename(path)):
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
                docstrings = set()
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Module, ast.ClassDef,
                                         ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        doc = ast.get_docstring(node, clean=False)
                        if doc is not None:
                            docstrings.add(id(node.body[0].value))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Constant):
                        continue
                    if not isinstance(node.value, str):
                        continue
                    if id(node) in docstrings:
                        continue
                    found = japanese_characters(node.value)
                    self.assertEqual(
                        found, [],
                        "%s:%d の文字列定数に日本語がある: %r"
                        % (os.path.basename(path), node.lineno, node.value))


if __name__ == "__main__":
    unittest.main()
