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
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from lifetime import (
    ESCAPED_QUOTE,
    Color,
    ProcessingError,
    Processor,
    hide_escaped_quotes,
    line_details,
    main,
    max_value,
    mean,
    median,
    min_value,
    output_source_code,
    parse_main_args,
    quartile_rank,
    range_parse,
    unescape,
    unquote_unescape,
)

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
            unescape(
                r"\316\265\316\273\316\273\316\267\316\275\316\271"
                r"\316\272\316\254"
            ),
        )
        self.assertEqual('a"b', unescape("a" + ESCAPED_QUOTE + "b"))
        self.assertEqual('a"b', unquote_unescape('"a\\"b"'))
        self.assertEqual(
            'another file name with "quotes", spaces '
            "\u03b5\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac",
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
                exit_code = main(
                    [
                        "-q",
                        "-f",
                        "--format",
                        "{path} {max(line_churns)} {days(mean(line_ages))}",
                        path,
                    ]
                )
        finally:
            os.unlink(path)
        self.assertEqual(0, exit_code)
        self.assertEqual("f 1 1\n", stdout.getvalue())

    def test_json_metrics_output(self):
        fd, path = tempfile.mkstemp(
            prefix="test-json-metrics-",
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
                exit_code = main(["-q", "-j", path])
        finally:
            os.unlink(path)
        self.assertEqual(0, exit_code)
        data = json.loads(stdout.getvalue())
        self.assertEqual("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", data["commit"])
        self.assertEqual(172800, data["timestamp"])
        self.assertEqual(1, len(data["files"]))
        file_metrics = data["files"][0]
        self.assertEqual("f", file_metrics["path"])
        self.assertEqual([86400], file_metrics["change_lifetimes"])
        self.assertEqual(2, len(file_metrics["lines"]))
        self.assertEqual(
            {
                "line_number": 1,
                "content": "one\n",
                "contents": ["one\n"],
                "birth_timestamp": 86400,
                "birth_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "age": 86400,
                "churn": 0,
                "change_lifetimes": [],
                "delta": None,
                "length": 0,
                "startspace": 0,
                "string": 0,
                "comment": 0,
                "comma": 0,
                "bracket": 0,
                "access": 0,
                "assignment": 0,
                "scope": 0,
                "array": 0,
                "logical": 0,
            },
            file_metrics["lines"][0],
        )
        self.assertEqual("two changed\n", file_metrics["lines"][1]["content"])
        self.assertEqual(["two\n", "two changed\n"], file_metrics["lines"][1]["contents"])
        self.assertEqual(1, file_metrics["lines"][1]["churn"])
        self.assertEqual([86400], file_metrics["lines"][1]["change_lifetimes"])


class FormatterHelperTests(unittest.TestCase):
    def test_color_support(self):
        always = type("Args", (), {"color": "always"})()
        never = type("Args", (), {"color": "never"})()
        self.assertEqual("\033[38;5;33m", Color(always).color(1))
        self.assertEqual("\033[0m", Color(always).color(0))
        self.assertEqual("", Color(never).color(4))

    def test_quartile_rank(self):
        population = [1, 2, 3, 4, 5, 6, 7, 8]
        self.assertEqual(1, quartile_rank(1, population))
        self.assertEqual(2, quartile_rank(3, population))
        self.assertEqual(3, quartile_rank(5, population))
        self.assertEqual(4, quartile_rank(8, population))
        with self.assertRaises(TypeError):
            quartile_rank([1, 2], population)

    def test_aggregate_invocation_types(self):
        cases = [
            ("min", min_value, 1, 1, [[3], [4, 5]], [1, 3, 5]),
            ("max", max_value, 5, 5, [[3], [4, 5]], [1, 3, 5]),
            ("median", median, 3, 3, [[1, 3], [5, 7]], [1, 3, 5]),
            ("mean", mean, 3, 3, [[1, 3], [5, 7]], [1, 3, 5]),
        ]
        for name, func, list_value, tuple_value, nested_value, sample in cases:
            with self.subTest(name=name, invocation="list"):
                self.assertEqual(list_value, func(sample))
            with self.subTest(name=name, invocation="tuple"):
                self.assertEqual(tuple_value, func(tuple(sample)))
            with self.subTest(name=name, invocation="nested"):
                with self.assertRaises(TypeError):
                    func(nested_value)
            with self.subTest(name=name, invocation="scalar"):
                with self.assertRaises(TypeError):
                    func(3)


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
        args = self.parse_git_hot(
            [
                "-q",
                "--debug",
                "g",
                "--dir",
                "out",
                "--format",
                "{line}",
                "--color",
                "always",
                "--color-domain",
                "age",
                "HEAD",
                "--",
                "src/main.py",
            ]
        )
        self.assertTrue(args.quiet)
        self.assertEqual("g", args.debug_options)
        self.assertEqual("out", args.churn_dir)
        self.assertEqual("{line}", args.output_format)
        self.assertEqual("always", args.color)
        self.assertEqual("age", args.color_domain)
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
            self.git_hot_total_commits = self.diff_stream.count("commit ")
            return iter(self.diff_stream.splitlines(True))

    def test_git_hot_path_outputs_reconstructed_file_with_churn_counts(self):
        args = parse_main_args(["-q", "--", "f"], prog="git-hot")
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual("    0  one\n    1  two changed\n", stdout.getvalue())

    def test_git_hot_reports_percentage_progress(self):
        args = parse_main_args(["HEAD"], prog="git-hot")
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual(
            "\rProcessing commits:  50% (1/2)\rProcessing commits: 100% (2/2), done.\n",
            stderr.getvalue(),
        )

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

    def test_git_hot_path_uses_default_coloring(self):
        args = parse_main_args(["-q", "--color", "always", "--", "f"], prog="git-hot")
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertIn("\033[", stdout.getvalue())
        self.assertIn("\033[0m", stdout.getvalue())

    def test_git_hot_path_explicit_color_disables_default_coloring(self):
        args = parse_main_args(
            [
                "-q",
                "--color",
                "always",
                "--format",
                "{color(quartile_rank(churn, file_line_churns))}{line}",
                "--",
                "f",
            ],
            prog="git-hot",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual(
            "\033[38;5;33mone\033[0m\n\033[38;5;9mtwo changed\033[0m\n",
            stdout.getvalue(),
        )

    def test_git_hot_path_supports_color_reset_function(self):
        args = parse_main_args(
            ["-q", "--color", "always", "--format", "{color(4)}{line}{color_reset()}", "--", "f"],
            prog="git-hot",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual(
            "\033[38;5;9mone\033[0m\033[0m\n\033[38;5;9mtwo changed\033[0m\033[0m\n",
            stdout.getvalue(),
        )

    def test_git_hot_file_output_supports_nested_aggregate_expression(self):
        args = parse_main_args(
            [
                "-q",
                "--color",
                "always",
                "--format",
                "{color(quartile_rank(max(file_line_churns), list(map(max, repo_line_churns))))}"
                "{path} {max(file_line_churns)}",
                "HEAD",
            ],
            prog="git-hot",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.TestProcessor(args).run()
        self.assertEqual("\033[38;5;33mf 1\033[0m\n", stdout.getvalue())

    def test_git_hot_closes_and_waits_for_pager(self):
        args = parse_main_args(["-q", "HEAD"], prog="git-hot")
        pager_out = io.StringIO()

        class PagerProc:
            def __init__(self):
                self.wait_called = False

            def wait(self):
                self.wait_called = True

        pager_proc = PagerProc()
        self.TestProcessor.diff_stream = TEST_DIFF_STREAM
        with patch("lifetime.get_paged_output", return_value=(pager_out, pager_proc)):
            self.TestProcessor(args).run()
        self.assertTrue(pager_out.closed)
        self.assertTrue(pager_proc.wait_called)

    def test_git_hot_reports_git_log_errors_before_running_daglp(self):
        args = parse_main_args(["-q", "HEAD"], prog="git-hot")
        completed = subprocess.CompletedProcess(
            ["git", "log"],
            128,
            stdout="",
            stderr="fatal: not a git repository",
        )
        with patch("lifetime.get_paged_output", return_value=(io.StringIO(), None)), patch(
            "subprocess.run", return_value=completed
        ) as run_mock:
            with self.assertRaises(ProcessingError) as raised:
                list(Processor(args).stream_git_history())
        self.assertEqual("fatal: not a git repository", str(raised.exception))
        self.assertEqual(1, run_mock.call_count)

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
            "Error: Invalid file output format string '{missing_name}': "
            "name 'missing_name' is not defined\n",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
