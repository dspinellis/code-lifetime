#!/usr/bin/env python3
#
# Copyright 1996-2026 Diomidis Spinellis
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from unittest.mock import patch

from lifetime import ESCAPED_QUOTE
from lifetime import hide_escaped_quotes
from lifetime import line_details
from lifetime import main
from lifetime import output_source_code
from lifetime import parse_main_args
from lifetime import Processor
from lifetime import range_parse
from lifetime import unescape
from lifetime import unquote_unescape


TEST_DIFF_STREAM = """commit aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 86400

diff --git a/f b/f
new file mode 100644
index 0000000..1111111
--- /dev/null
+++ b/f
@@ -0,0 +1,2 @@
+one
+two
commit bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 172800

diff --git a/f b/f
index 1111111..2222222 100644
--- a/f
+++ b/f
@@ -2 +2 @@
-two
+two changed
"""


class ConvertedFunctionTests(unittest.TestCase):
    def test_line_details_existing_cases(self):
        cases = [
            ("xx", "2 0 0 0 0 0 0 0 0 0 0"),
            ("'x'", "3 0 1 0 0 0 0 0 0 0 0"),
            ("#x(", "3 0 0 1 0 0 0 0 0 0 0"),
            ("/*(", "3 0 0 1 0 0 0 0 0 0 0"),
            ("//(", "3 0 0 1 0 0 0 0 0 0 0"),
            ("a,b,c", "5 0 0 0 2 0 0 0 0 0 0"),
            ("((", "2 0 0 0 0 2 0 0 0 0 0"),
            ("a.b", "3 0 0 0 0 0 1 0 0 0 0"),
            ("a->b", "4 0 0 0 0 0 1 0 0 0 0"),
            ("1.2", "3 0 0 0 0 0 0 0 0 0 0"),
            ("a=b", "3 0 0 0 0 0 0 1 0 0 0"),
            ("a<<=b", "5 0 0 0 0 0 0 1 0 0 0"),
            ("a*=b", "4 0 0 0 0 0 0 1 0 0 0"),
            ("{", "1 0 0 0 0 0 0 0 1 0 0"),
            (": ", "2 0 0 0 0 0 0 0 1 0 0"),
            ("x:", "2 0 0 0 0 0 0 0 1 0 0"),
            ("[", "1 0 0 0 0 0 0 0 0 1 0"),
            ("==", "2 0 0 0 0 0 0 0 0 0 1"),
            ("a>=", "3 0 0 0 0 0 0 0 0 0 1"),
            ("b<=", "3 0 0 0 0 0 0 0 0 0 1"),
            ("!=", "2 0 0 0 0 0 0 0 0 0 1"),
            ("a<b", "3 0 0 0 0 0 0 0 0 0 1"),
            ("a<<b", "4 0 0 0 0 0 0 0 0 0 0"),
            ("a>b", "3 0 0 0 0 0 0 0 0 0 1"),
            ("!!", "2 0 0 0 0 0 0 0 0 0 2"),
            ("||", "2 0 0 0 0 0 0 0 0 0 1"),
            ("&&", "2 0 0 0 0 0 0 0 0 0 1"),
            ("a and b", "7 0 0 0 0 0 0 0 0 0 1"),
            ("a or b", "6 0 0 0 0 0 0 0 0 0 1"),
            ("not b", "5 0 0 0 0 0 0 0 0 0 1"),
            ("notb", "4 0 0 0 0 0 0 0 0 0 0"),
            ("is not", "6 0 0 0 0 0 0 0 0 0 2"),
            (" x", "2 1 0 0 0 0 0 0 0 0 0"),
            ("   x", "4 3 0 0 0 0 0 0 0 0 0"),
            ("\t", "1 8 0 0 0 0 0 0 0 0 0"),
            ("\t\tx", "3 16 0 0 0 0 0 0 0 0 0"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, str(line_details(text)))

    def test_range_parse(self):
        self.assertEqual((0, 1), range_parse("-1"))
        self.assertEqual((4, 7), range_parse("+5,3"))
        self.assertEqual((0, 0), range_parse("-7,0"))
        self.assertEqual((0, 0), range_parse("-3,0"))
        self.assertEqual((9, 14), range_parse("+10,5"))

    def test_source_suffix_filter(self):
        self.assertTrue(output_source_code("src/main.cpp", True))
        self.assertTrue(output_source_code("lib/module.py", True))
        self.assertFalse(output_source_code("README.md", True))
        self.assertTrue(output_source_code("README.md", False))

    def test_filename_escaping(self):
        self.assertEqual("a\tb\nc", unescape(r"a\tb\nc"))
        self.assertEqual("a b", unescape(r"a\040b"))
        self.assertEqual(
            "\u03b5\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac",
            unescape(r"\316\265\316\273\316\273\316\267\316\275\316\271\316\272\316\254"),
        )
        self.assertEqual('a"b', unescape("a" + ESCAPED_QUOTE + "b"))
        self.assertEqual('a"b', unquote_unescape('"a\\"b"'))
        self.assertEqual(
            'another file name with "quotes", spaces \u03b5\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac',
            unquote_unescape(
                r'"another file name with \"quotes\", spaces '
                r'\316\265\316\273\316\273\316\267\316\275\316\271\316\272\316\254"'
            ),
        )

    def test_hide_escaped_quotes(self):
        self.assertEqual('a' + ESCAPED_QUOTE + 'b"', hide_escaped_quotes('a\\"b"'))

    def test_file_stats_output(self):
        fd, path = tempfile.mkstemp(
            prefix="test-file-stats-",
            suffix=".log",
            dir=os.getcwd(),
        )
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(TEST_DIFF_STREAM)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["-q", "-f", path])
        finally:
            os.unlink(path)
        self.assertEqual(0, exit_code)
        self.assertEqual("    1     1     1 f\n", stdout.getvalue())

    def test_file_stats_custom_format(self):
        fd, path = tempfile.mkstemp(
            prefix="test-file-stats-",
            suffix=".log",
            dir=os.getcwd(),
        )
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(TEST_DIFF_STREAM)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["-q", "-f", "--format", "{path} {max(line_churns)} {days(mean(line_ages))}", path])
        finally:
            os.unlink(path)
        self.assertEqual(0, exit_code)
        self.assertEqual("f 1 1\n", stdout.getvalue())


class GitHotArgumentParsingTests(unittest.TestCase):
    def parse_git_hot(self, argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return parse_main_args(argv, prog="git-hot")

    def test_git_hot_invocation_forms(self):
        cases = [
            ([], None, None),
            (["HEAD"], "HEAD", None),
            (["--", "src/main.py"], None, "src/main.py"),
            (["HEAD", "src/main.py"], "HEAD", "src/main.py"),
            (["HEAD", "--", "src/main.py"], "HEAD", "src/main.py"),
        ]
        for argv, expected_ref, expected_path in cases:
            with self.subTest(argv=argv):
                args = self.parse_git_hot(argv)
                self.assertEqual(expected_ref, args.ref)
                self.assertEqual(expected_path, args.path)
                self.assertFalse(args.quiet)
                self.assertIsNone(args.debug_options)
                self.assertIsNone(args.churn_dir)

    def test_git_hot_indicative_arguments(self):
        args = self.parse_git_hot(["-q", "--debug", "g", "--dir", "out", "--format", "{line}", "HEAD", "--", "src/main.py"])
        self.assertTrue(args.quiet)
        self.assertEqual("g", args.debug_options)
        self.assertEqual("out", args.churn_dir)
        self.assertEqual("{line}", args.output_format)
        self.assertEqual("HEAD", args.ref)
        self.assertEqual("src/main.py", args.path)

        args = self.parse_git_hot(["--quiet", "-D", "HS", "-d", "recons", "--", "src/main.py"])
        self.assertTrue(args.quiet)
        self.assertEqual("HS", args.debug_options)
        self.assertEqual("recons", args.churn_dir)
        self.assertIsNone(args.ref)
        self.assertEqual("src/main.py", args.path)

    def test_git_hot_rejects_multiple_paths_after_separator(self):
        with self.assertRaises(SystemExit) as raised:
            self.parse_git_hot(["HEAD", "--", "src/main.py", "src/other.py"])
        self.assertEqual(2, raised.exception.code)

    def test_git_hot_rejects_path_before_separator(self):
        with self.assertRaises(SystemExit) as raised:
            self.parse_git_hot(["HEAD", "src/main.py", "--", "src/other.py"])
        self.assertEqual(2, raised.exception.code)

    def test_git_hot_help_exits_cleanly(self):
        with self.assertRaises(SystemExit) as raised:
            self.parse_git_hot(["--help"])
        self.assertEqual(0, raised.exception.code)


class GitHotOutputTests(unittest.TestCase):
    class TestProcessor(Processor):
        diff_stream = ""

        def stream_git_history(self, file=None):
            return iter(self.diff_stream.splitlines(True))

    def test_git_hot_path_outputs_reconstructed_file_with_churn_counts(self):
        args = parse_main_args(["-q", "--", "f"], prog="git-hot")
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual("    0  one\n    1  two changed\n", stdout.getvalue())

    def test_git_hot_path_uses_custom_format(self):
        args = parse_main_args(
            ["-q", "--format", "{days(age)} {isodate(birthtime)} {hash[:7]} {line}", "--", "f"],
            prog="git-hot",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual(
            "1 1970-01-02 aaaaaaa one\n0 1970-01-03 bbbbbbb two changed\n",
            stdout.getvalue(),
        )

    def test_git_hot_reports_line_format_errors(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.argv", ["git-hot"]), patch.object(
            Processor, "stream_git_history", return_value=iter(TEST_DIFF_STREAM.splitlines(True))
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["-q", "--format", "{1/0} {line}", "--", "f"])
        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(
            "Error: Invalid line output format string '{1/0} {line}': division by zero\n",
            stderr.getvalue(),
        )

    def test_git_hot_reports_file_format_errors(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("sys.argv", ["git-hot"]), patch.object(
            Processor, "stream_git_history", return_value=iter(TEST_DIFF_STREAM.splitlines(True))
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["-q", "--format", "{missing_name}", "HEAD"])
        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertEqual(
            "Error: Invalid file output format string '{missing_name}': name 'missing_name' is not defined\n",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
