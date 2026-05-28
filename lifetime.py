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
#
#
# Parse the output of
# git log -M -m --pretty=tformat:'commit %H %ct' --topo-order --reverse -U0
# to track the lifetime of individual lines
#

import argparse
import builtins
import datetime
import json
import os
import re
import shutil
import shlex
import statistics
import subprocess
import sys
from typing import Iterator, Dict

VERSION = "0.1"
ESCAPED_QUOTE = "\001"

class Color():
    def __init__(self, args):
        color_mode = getattr(args, "color", None)
        if color_mode == "always":
            self.use_color = True
        elif color_mode == "never":
            self.use_color = False
        else:
            self.use_color = sys.stdout.isatty()

    @staticmethod
    def _ansi_fg(n: int) -> str:
        """Return an ANSI escape setting foreground color to n."""
        return f"\033[38;5;{n}m"

    def reset(self) -> str:
        """Reset any set color."""
        if not self.use_color:
            return ""
        else:
            return "\033[0m"

    def get(self, quartile: int) -> str:
        """Return a coloring string associated with the specified quartile."""
        if not self.use_color:
            return ""
        if quartile <= 0:
            return self.reset()
        if quartile == 1:         # Bottom 25th percentile
            return self._ansi_fg(33)   # Light blue; cold; few
        elif quartile == 2:       # 25th-50th percentile
            return self._ansi_fg(10)   # Green; some
        elif quartile == 3:       # 50th to 75th percentile
            return self._ansi_fg(11)   # Yellow; many
        else:                     # Top 25th  percentile
            return self._ansi_fg(9)    # Bright red; red-hot; tons

    def color(self, quartile: int) -> str:
        return self.get(quartile)

    def wrap(self, text: str, quartile: int) -> str:
        prefix = self.color(quartile)
        if not prefix:
            return text
        return f"{prefix}{text}{self.reset()}"


class ProcessingError(Exception):
    """Fatal processing error reported without an exception trace."""

class FileDetails:
    """Details tracked for a file while processing the diff stream."""

    def __init__(self, path, lines=None, binary=False, change_lifetimes=None):
        self.path = path
        self.lines = list(lines) if lines is not None else []
        self.binary = binary
        self.change_lifetimes = list(change_lifetimes) if change_lifetimes is not None else []

    def copy(self, path=None, change_lifetimes=None):
        return FileDetails(
            self.path if path is None else path,
            [line.copy() for line in self.lines],
            self.binary,
            self.change_lifetimes if change_lifetimes is None else change_lifetimes,
        )


class LineDetails:
    """Details about a line's content, lifetime metadata, and composition."""

    def __init__(
        self,
        content="",
        birth_timestamp=None,
        birth_hash=None,
        content_history=None,
        churn_count=0,
        change_lifetimes=None,
        delta=None,
        length=0,
        startspace=0,
        string=0,
        comment=0,
        comma=0,
        bracket=0,
        access=0,
        assignment=0,
        scope=0,
        array=0,
        logical=0,
    ):
        self.content = content
        self.birth_timestamp = birth_timestamp
        self.birth_hash = birth_hash
        self.content_history = list(content_history) if content_history is not None else [content]
        self.churn_count = churn_count
        self.change_lifetimes = list(change_lifetimes) if change_lifetimes is not None else []
        self.delta = delta
        self.length = length
        self.startspace = startspace
        self.string = string
        self.comment = comment
        self.comma = comma
        self.bracket = bracket
        self.access = access
        self.assignment = assignment
        self.scope = scope
        self.array = array
        self.logical = logical

    def __str__(self):
        return (
            f"{self.length} {self.startspace} {self.string} {self.comment} "
            f"{self.comma} {self.bracket} {self.access} {self.assignment} "
            f"{self.scope} {self.array} {self.logical}"
        )

    def copy(self):
        return LineDetails(
            content=self.content,
            birth_timestamp=self.birth_timestamp,
            birth_hash=self.birth_hash,
            content_history=self.content_history,
            churn_count=self.churn_count,
            change_lifetimes=self.change_lifetimes,
            delta=self.delta,
            length=self.length,
            startspace=self.startspace,
            string=self.string,
            comment=self.comment,
            comma=self.comma,
            bracket=self.bracket,
            access=self.access,
            assignment=self.assignment,
            scope=self.scope,
            array=self.array,
            logical=self.logical,
        )

    def render_record(self, args):
        parts = [str(self.birth_timestamp)]
        if self.delta is not None:
            parts.append(str(self.delta))
        if args.line_details:
            parts.extend(["L", str(self)])
        elif args.tokens:
            parts.append(self.content.rstrip("\n"))
        return " ".join(parts)

    def render_deleted(self, args, death_timestamp):
        return f"{self.render_record(args)} {death_timestamp}"

    def render_alive(self, args):
        if args.compressed:
            return self.render_record(args)
        return f"{self.render_record(args)} alive NA"

class InputReader:
    def __init__(self):
        self.line_number = 0
        self._index = 0
        self._current = None
        self._close_current = False

    @classmethod
    def from_paths(cls, paths):
        """Construct an object to return lines from the specified paths."""
        instance = cls()
        instance.paths = paths
        instance.line_iterator = None
        return instance

    @classmethod
    def from_iterator(cls, iterator):
        """Construct an object to return lines from the specified iterator."""
        instance = cls()
        instance.paths = None
        instance.line_iterator = iterator
        return instance

    def close(self):
        if self._current is not None and self._close_current:
            self._current.close()
        self._current = None
        self._close_current = False

    def _open_next(self):
        self.close()
        if self._index >= len(self.paths):
            return False
        path = self.paths[self._index]
        self._index += 1
        self._current = open(path, "r", encoding="utf-8", errors="surrogateescape", newline="")
        self._close_current = True
        return True

    def _read_raw_from_paths(self):
        """Return the next read line from the files specified in paths."""
        while True:
            if self._current is None:
                if self.paths:
                    if not self._open_next():
                        return None
                else:
                    self._current = utf8_stdin()
                    self._close_current = False
            line = self._current.readline()
            if line != "":
                self.line_number += 1
                return line
            if not self.paths:
                return None
            if not self._open_next():
                return None

    def _read_raw_from_iterator(self):
        """Return the next read line from the line_iterator iterator."""
        line = next(self.line_iterator, "")
        if line != "":
            self.line_number += 1
            return line
        return None

    def read_raw(self):
        """Return the next read line, including the trailing newline."""
        if self.paths is not None:
            return self._read_raw_from_paths()
        else:
            return self._read_raw_from_iterator()

    def read_chomp(self):
        """Return the next read line, without any trailing newling."""
        line = self.read_raw()
        return None if line is None else chomp(line)


def chomp(line):
    return line[:-1] if line.endswith("\n") else line


def utf8_stdin():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="surrogateescape", newline="")
        return sys.stdin
    return open(
        sys.stdin.fileno(),
        "r",
        encoding="utf-8",
        errors="surrogateescape",
        newline="",
        closefd=False,
    )


# Return undef or true depending on whether the specified
# debug option is set
def debug_option(options, opt):
    if options is None:
        return False
    return re.search(re.escape(opt), options) is not None


# Return a diff range as a [start, end) interval
def range_parse(diff_range):
    match = re.search(r"[+-](\d+),(\d+)$", diff_range)
    if match:
        start = int(match.group(1))
        count = int(match.group(2))
        if count == 0:
            return (0, 0)
        return (start - 1, start + count - 1)
    match = re.search(r"[+-](\d+)$", diff_range)
    if match:
        start = int(match.group(1))
        return (start - 1, start)
    raise ProcessingError("Expecting a diff range")


# Return true if we are supposed to output details regarding the specified file
# (if no -s option was passed or the file contains source code)
def output_source_code(name, source_only=False):
    if not source_only:
        return True
    # Keep tokenize.pl:tokenize, lifetime.pl:output_source_code, repo-metrics-report.sh, analyze-moves.sh in sync
    return (
        re.search(
            r"\.(C|c|cc|cpp|cs|cxx|go|hh|hpp|h\+\+|c\+\+|h|H|hxx|java|((php[3457s]?)|pht|php-s)|py|rs)$",
            name,
        )
        is not None
    )


# Change escaped quotes into \001 so that the real ones can be used as delimiters
def hide_escaped_quotes(text):
    return re.sub(r'([^\\])\\"', r"\1" + ESCAPED_QUOTE, text)


# Fix filename with embedded quotes and escapes
def unquote_unescape(name):
    if '"' not in name:
        return name
    name = re.sub(r'([^\\])\\"', r"\1" + ESCAPED_QUOTE, name)
    name = name.replace('"', "")
    return unescape(name)


# Remove escapes and escaped quotes from the passed file name
def unescape(name):
    def octal(match):
        data = bytes(
            int(part[1:], 8) for part in re.findall(r"\\[0-7]{3}", match.group(0))
        )
        return data.decode("utf-8", errors="surrogateescape")

    name = name.replace(ESCAPED_QUOTE, '"')
    name = name.replace(r"\t", "\t")
    name = name.replace(r"\n", "\n")
    name = name.replace(r"\"", '"')
    name = re.sub(r"(?:\\[0-7]{3})+", octal, name)
    name = name.replace(r"\\", "\\")  # Must be last
    return name


def count_pattern(pattern, text):
    return len(re.findall(pattern, text))


# Return details about the line's composition
# The values returned appear in the end of this function
def line_details(line):
    text = line
    length = len(text)

    # Count and remove strings
    string = 0
    while True:
        text, count = re.subn(r'"[^"]*"', "", text, count=1)
        if count == 0:
            break
        string += 1
    while True:
        text, count = re.subn(r"'[^']*'", "", text, count=1)
        if count == 0:
            break
        string += 1

    # Remove comments
    comment = 0
    for pattern in (r"/\*.*", r"#.*", r"//.*"):
        new_text, count = re.subn(pattern, "", text, count=1)
        if count:
            text = new_text
            comment = 1
            break

    # Spaces (and expanded tabs) at the beginning of the line
    text = text.expandtabs(8)
    match = re.match(r"^( *)", text)
    startspace = len(match.group(1))

    comma = count_pattern(r",", text)
    bracket = count_pattern(r"\(", text)
    access = count_pattern(r"\.[^0-9]|->", text)
    assignment = count_pattern(r"[^<>!~=]=[^=]|<<=|>>=", text)
    scope = count_pattern(r"\{|(:\s*$)", text)
    # String (done earlier)
    # Structure member access (combined with access)
    # * can be pointer dereference or multiplication; ignore
    # "if" ignore
    array = count_pattern(r"\[", text)
    # Comments (done earlier)
    logical = count_pattern(
        r"==|[^>]>=|[^<]<=|!=|[^<]<[^<]|[^>\-]>[^>]|\!|\|\||\&\&|\bor\b|\band\b|\bnot\b|\bis\b",
        text,
    )
    return LineDetails(
        content=line,
        length=length,
        startspace=startspace,
        string=string,
        comment=comment,
        comma=comma,
        bracket=bracket,
        access=access,
        assignment=assignment,
        scope=scope,
        array=array,
        logical=logical,
    )


def print_stderr_line(text):
    try:
        print(text, file=sys.stderr)
    except UnicodeEncodeError:
        encoding = sys.stderr.encoding or "utf-8"
        data = f"{text}\n".encode(encoding, errors="backslashreplace")
        if hasattr(sys.stderr, "buffer"):
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()
        else:
            sys.stderr.write(data.decode(encoding, errors="replace"))


def round_days(seconds):
    return int((seconds / 86400.0) + 0.5)


def days(seconds):
    return round_days(seconds)


def isodate(epoch_seconds):
    return datetime.datetime.utcfromtimestamp(epoch_seconds).strftime("%Y-%m-%d")


def utf8_surrogateescape_text():
    """Return subprocess text-mode arguments matching the repo's I/O policy."""
    return {
        "text": True,
        "encoding": "utf-8",
        "errors": "surrogateescape",
    }


def require_flat_values(values):
    """Return a flat homogeneous sequence or raise for nested values."""
    if not isinstance(values, (list, tuple)):
        raise TypeError("aggregate functions require a flat sequence")
    # Values are assumed to be homogeneous, so sampling the first is enough.
    if values and isinstance(values[0], (list, tuple)):
            raise TypeError("nested sequences require explicit aggregation")
    return values


def median(values):
    """Return the integer median of a flat sequence."""
    ordered = sorted(require_flat_values(values))
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return int((ordered[middle - 1] + ordered[middle]) / 2.0)


def mean(values):
    """Return the integer mean of a flat sequence."""
    values = require_flat_values(values)
    if not values:
        return 0
    return int(sum(values) / len(values))


def max_value(values):
    """Return the maximum value in a flat sequence."""
    values = require_flat_values(values)
    return 0 if not values else builtins.max(values)


def min_value(values):
    """Return the minimum value in a flat sequence."""
    values = require_flat_values(values)
    return 0 if not values else builtins.min(values)


def quartile_rank(value, population):
    """Rank value in the population's quartiles using statistical cut points."""
    if isinstance(value, (list, tuple)):
        raise TypeError("quartile rank requires a scalar value")
    values = require_flat_values(population)
    if not values:
        return 1
    if len(values) == 1:
        return 1
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    if value <= quartiles[0]:
        return 1
    if value <= quartiles[1]:
        return 2
    if value <= quartiles[2]:
        return 3
    return 4


def evaluate_format(fmt, context, description):
    try:
        return eval(f"f{fmt!r}", {"__builtins__": {}}, context)
    except Exception as exc:
        raise ProcessingError(
            f"Invalid {description} format string {fmt!r}: {exc}"
        ) from None


class LineFormatter:
    def __init__(self, fmt, color, color_domain="churn"):
        self.fmt = fmt
        self.color = color
        self.color_domain = color_domain
        self.explicit_color = "color(" in fmt
        self.current_timestamp = 0
        self.file_change_lifetimes = []
        self.file_line_churns = []
        self.file_line_ages = []
        self.file_line_change_lifetimes = []
        self.repo_line_churns = []
        self.repo_line_ages = []
        self.repo_line_change_lifetimes = []

    def bind_repo(self, repo_line_churns, repo_line_ages, repo_line_change_lifetimes):
        self.repo_line_churns = repo_line_churns
        self.repo_line_ages = repo_line_ages
        self.repo_line_change_lifetimes = repo_line_change_lifetimes

    def bind_file(self, details, current_timestamp, repo_line_churns, repo_line_ages, repo_line_change_lifetimes):
        """Bind the current file and repo populations for line formatting."""
        self.current_timestamp = current_timestamp
        self.file_change_lifetimes = details.change_lifetimes
        self.file_line_churns = [line.churn_count for line in details.lines]
        self.file_line_ages = [current_timestamp - line.birth_timestamp for line in details.lines]
        self.file_line_change_lifetimes = [list(line.change_lifetimes) for line in details.lines]
        self.bind_repo(repo_line_churns, repo_line_ages, repo_line_change_lifetimes)

    def default_quartile(self, line, age):
        """Color a reconstructed line against the current file's populations."""
        if self.color_domain == "age":
            return quartile_rank(age, self.file_line_ages)
        if self.color_domain == "lifetime":
            return quartile_rank(
                median(line.change_lifetimes),
                list(map(median, self.file_line_change_lifetimes)),
            )
        return quartile_rank(line.churn_count, self.file_line_churns)

    def format(self, line):
        age = 0 if line.birth_timestamp is None else int(self.current_timestamp - line.birth_timestamp)
        context = {
            "churn": line.churn_count,
            "age": age,
            "hash": line.birth_hash,
            "change_lifetimes": line.change_lifetimes,
            "lifetime_median": median(self.file_change_lifetimes),
            "lifetime_mean": mean(self.file_change_lifetimes),
            "birthtime": line.birth_timestamp,
            "line": line.content.rstrip("\n"),
            "file_line_churns": self.file_line_churns,
            "file_line_ages": self.file_line_ages,
            "file_line_change_lifetimes": self.file_line_change_lifetimes,
            "repo_line_churns": self.repo_line_churns,
            "repo_line_ages": self.repo_line_ages,
            "repo_line_change_lifetimes": self.repo_line_change_lifetimes,
            "days": days,
            "isodate": isodate,
            "max": max_value,
            "min": min_value,
            "median": median,
            "mean": mean,
            "quartile_rank": quartile_rank,
            "color": self.color.color,
            "color_reset": self.color.reset,
            "list": list,
            "map": map,
        }
        rendered = evaluate_format(self.fmt, context, "line output")
        if self.explicit_color:
            if self.color.use_color:
                rendered += self.color.reset()
        elif self.color.use_color:
            rendered = self.color.wrap(rendered, self.default_quartile(line, age))
        return rendered + "\n"


class FileFormatter:
    def __init__(self, fmt, color, color_domain="churn"):
        self.fmt = fmt
        self.color = color
        self.color_domain = color_domain
        self.explicit_color = "color(" in fmt
        self.repo_line_churns = []
        self.repo_line_ages = []
        self.repo_line_change_lifetimes = []

    def bind_repo(self, repo_line_churns, repo_line_ages, repo_line_change_lifetimes):
        self.repo_line_churns = repo_line_churns
        self.repo_line_ages = repo_line_ages
        self.repo_line_change_lifetimes = repo_line_change_lifetimes

    def default_quartile(self, churns, change_lifetimes, ages):
        """Color a file-metrics line against the repository's file populations."""
        if self.color_domain == "age":
            return quartile_rank(
                median(ages),
                list(map(median, self.repo_line_ages)),
            )
        if self.color_domain == "lifetime":
            return quartile_rank(
                median(list(map(median, change_lifetimes))),
                [
                    median(list(map(median, file_change_lifetimes)))
                    for file_change_lifetimes in self.repo_line_change_lifetimes
                ],
            )
        return quartile_rank(
            max_value(churns),
            list(map(max_value, self.repo_line_churns)),
        )

    def format(self, path, churns, change_lifetimes, ages):
        context = {
            "path": path,
            "churn": churns,
            "change_lifetime": change_lifetimes,
            "changed_lifetime": change_lifetimes,
            "line_age": ages,
            "line_churns": churns,
            "line_change_lifetimes": change_lifetimes,
            "line_ages": ages,
            "file_line_churns": churns,
            "file_line_change_lifetimes": change_lifetimes,
            "file_line_ages": ages,
            "repo_line_churns": self.repo_line_churns,
            "repo_line_ages": self.repo_line_ages,
            "repo_line_change_lifetimes": self.repo_line_change_lifetimes,
            "max": max_value,
            "min": min_value,
            "median": median,
            "mean": mean,
            "days": days,
            "quartile_rank": quartile_rank,
            "color": self.color.color,
            "color_reset": self.color.reset,
            "list": list,
            "map": map,
        }
        rendered = evaluate_format(self.fmt, context, "file output")
        if self.explicit_color:
            if self.color.use_color:
                rendered += self.color.reset()
        elif self.color.use_color:
            rendered = self.color.wrap(rendered, self.default_quartile(churns, change_lifetimes, ages))
        return rendered

def get_paged_output(use_color=False):
    """Return a stream that outputs to a color-supporting pager
    as specified by Git configuration."""
    use_pager = sys.stdout.isatty()

    if not use_pager:
        return sys.stdout, None

    pager = subprocess.check_output(
        ["git", "var", "GIT_PAGER"],
        **utf8_surrogateescape_text(),
    ).strip()

    env = os.environ.copy()

    if use_color:
        # Ensure less(1) will pass-through color escapes
        pager_cmd = shlex.split(pager)
        pager_exe = pager_cmd[0]

        if os.path.basename(pager_exe) == "less":
            env["LESS"] = env.get("LESS", "") + " -R"

    p = subprocess.Popen(
        pager,
        stdin=subprocess.PIPE,
        env=env,
        shell=True,
        **utf8_surrogateescape_text(),
    )

    return p.stdin, p


class Processor:
    def __init__(self, args):
        self.args = args
        self.git_hot_cli = not hasattr(args, "input_files")
        self.pager_proc = None
        self.git_hot_total_commits = None
        self.git_hot_completed_commits = 0
        self.git_hot_progress_active = False
        if hasattr(args, "input_files"):
            # lifetime.py CLI: Read the output of difflog.sh.
            self.reader = InputReader.from_paths(args.input_files)
            # Other processing specific to lifetime.py CLI
            self.out = sys.stderr if args.redirect_output else sys.stdout
        else:
            # git-hot CLI: Invoke Git commands to obtain input.
            # With path specified report churn for that file.
            # Otherwise report metrics for all files and, optionally,
            # report in the specified directory churn for all files.
            self.reader = InputReader.from_iterator(
                self.stream_git_history(args.path))
            self.args.file_metrics = (args.path is None)
            self.args.growth_file = None
            self.args.compressed = False
            self.args.source_only = False
            self.args.line_details = False
            self.args.tokens = False
            self.args.delta = False
            self.args.json_metrics = False
            self.args.end_hash = False

        self.color = Color(args)
        if self.git_hot_cli:
            self.out, self.pager_proc = get_paged_output(self.color.use_color)
        else:
            self.out = sys.stderr if args.redirect_output else sys.stdout
        self.line_formatter = LineFormatter(
            self.args.output_format
            or ("{churn:>{5}d}  {line}"
                if self.args.churn_dir or self.selected_file_details_mode()
                else "{line}")
        , self.color, getattr(self.args, "color_domain", "churn"))

        self.file_formatter = FileFormatter(self.args.output_format
            or "{max(churn):5d} {days(median(changed_lifetime)):5d} "
            "{days(median(line_age)):5d} {path}",
            self.color,
            getattr(self.args, "color_domain", "churn"),
        )

        self.growth_file = None

        self.loc = 0
        self.prev_loc = 0

        # Reconstruct the repository contents from its log -D R
        self.debug_reconstruction = self.debug_option("R")
        self.debug_print_reconstruction = self.debug_printer(self.debug_reconstruction)
        # Show results of splicing operations -D S
        self.debug_splice = self.debug_option("S")
        self.debug_print_splice = self.debug_printer(self.debug_splice)
        # Show each commit SHA, timestamp header -D H
        self.debug_commit_header = self.debug_option("H")
        self.debug_print_commit_header = self.debug_printer(self.debug_commit_header)
        # Show diff headers -D D
        self.debug_diff_header = self.debug_option("D")
        self.debug_print_diff_header = self.debug_printer(self.debug_diff_header)
        # Show diff extended headers -D E
        self.debug_diff_extended = self.debug_option("E")
        self.debug_print_diff_extended = self.debug_printer(self.debug_diff_extended)
        # Show range headers -D @
        self.debug_range_header = self.debug_option("@")
        self.debug_print_range_header = self.debug_printer(self.debug_range_header)
        # Show commit set changes -D C
        self.debug_commit_changes = self.debug_option("C")
        self.debug_print_commit_changes = self.debug_printer(self.debug_commit_changes)
        # Show push to change set operations -D P
        self.debug_push_cc = self.debug_option("P")
        self.debug_print_push_cc = self.debug_printer(self.debug_push_cc)

        # Show LoC change processing -D L
        self.debug_loc = self.debug_option("L")
        self.debug_print_loc = self.debug_printer(self.debug_loc)

        # Show Git invocations -D g
        self.debug_git = self.debug_option("g")
        self.debug_print_git = self.debug_printer(self.debug_git)

        # Old and new changed files
        self.old = None
        self.new = None
        # One of inplace, copy, rename, del
        self.op = None

        # Details of current commit
        self.commit = None
        self.hash = None
        self.timestamp = None

        # File line timestamps (or contents when debugging through reconstruction)
        self.flt = {}

        # Commit changes. To preserve the isolation between changes performed
        # during a commit, all changes are recorded here and then atomically
        # committed at the end.
        # Each record has:
        #   op {set, del}
        #   path
        #   lines
        self.cc = []

        # Records of deleted lines
        # Output at the end of a commit in order to report
        # commit size, if needed
        self.delete_records = []

        # Number of lines added to new file
        self.added_lines = 0
        # Number of lines removed from old and new file
        self.removed_lines = 0
        # Reference to copy of the old and new file contents
        self.oref = None
        self.nref = None
        self.oref_change_lifetimes = None
        self.nref_change_lifetimes = None
        self.current_line = None

    def debug_option(self, opt):
        return debug_option(self.args.debug_options, opt)

    def debug_printer(self, enabled):
        return self.print_out if enabled else self.noop_print_out

    def print_out(self, text, end="\n"):
        print(text, end=end, file=self.out)

    def noop_print_out(self, text, end="\n"):
        pass

    def report_progress(self):
        if self.args.quiet or self.debug_reconstruction:
            return
        if self.git_hot_cli and self.git_hot_total_commits:
            self.git_hot_completed_commits += 1
            percent = int((self.git_hot_completed_commits * 100) / self.git_hot_total_commits)
            print(
                f"\rProcessing commits: {percent:3d}% ({self.git_hot_completed_commits}/{self.git_hot_total_commits})",
                end="",
                file=sys.stderr,
                flush=True,
            )
            self.git_hot_progress_active = True
            return
        print(f"commit {self.hash} {self.timestamp}", file=sys.stderr)

    def report_progress_done(self):
        """Finish the progress reporting output."""
        if self.git_hot_progress_active:
            print(", done.", file=sys.stderr, flush=True)
            self.git_hot_progress_active = False

    def checked_command_output(self, args):
        """Return command stdout, raising ProcessingError with stderr on failure."""
        self.debug_print_git(f"Run: {' '.join(args)}")
        completed = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **utf8_surrogateescape_text(),
        )
        if completed.returncode != 0:
            raise ProcessingError(completed.stderr.rstrip() or f"Command failed: {' '.join(args)}")
        return completed.stdout

    def run(self):
        try:
            if self.args.growth_file:
                self.growth_file = open(
                    self.args.growth_file,
                    "w",
                    encoding="utf-8",
                    errors="surrogateescape",
                    newline="",
                )

            state = "commit"
            self.current_line = self.reader.read_chomp()
            if self.current_line is None:
                return

            while True:
                if state == "commit":
                    state = self.process_commit_state()
                elif state == "diff":
                    state = self.process_diff_state()
                elif state == "range":
                    state = self.process_range_state()
                elif state == "EOF":
                    break
                else:
                    self.bail_out(f"Invalid state {state}")

            self.process_last_commit()
            if self.json_metrics_mode():
                self.dump_json_metrics()
            elif self.debug_reconstruction or self.args.churn_dir:
                self.reconstruct()
            elif self.dump_selected_file_details():
                pass
            elif self.args.file_metrics:
                self.dump_file_metrics()
            else:
                self.dump_alive()
        finally:
            self.reader.close()
            if self.growth_file is not None:
                self.growth_file.close()
            self.report_progress_done()
            if self.pager_proc:
                self.out.close()
                self.pager_proc.wait()

    def file_commits(self, file: str) -> Dict[str, str]:
        """Return a dictionary from commit SHAs to the corresponding file name."""

        args = [
            "git",
            "log",
            "-C", "-C", "-M", "-M",
            "--name-only",
            "--pretty=format:%H",
            "--follow",
            "--",
            file,
        ]
        sha_to_file: Dict[str, str] = dict()
        line_number = 0
        for line in self.checked_command_output(args).splitlines():
            line = line.strip()
            if line_number % 3 == 0:  # SHA record
                sha = line
            elif line_number % 3 == 1:  # file name
                sha_to_file[sha] = line
            line_number += 1

        return sha_to_file

    def stream_git_history(self, file: str=None) -> Iterator[str]:
        """
        Yields lines from `git show` / `git diff` for commits touching `file`,
        in topo order (daglp assumed installed), taking into account renames.
        """

        # Obtaim map for this file's commits to the corresponding file name.
        # The file name may differ due to renames.
        if file:
            sha_to_file = self.file_commits(file)

        # Create the longest path through all the repo's commits.
        # git-log | daglp

        log_output = self.checked_command_output(
            ["git", "log", "--topo-order", "--pretty=format:%H %at %P"]
        )
        self.debug_print_git("Run: daglp")
        daglp = subprocess.run(
            ["daglp"],
            input=log_output,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **utf8_surrogateescape_text(),
        )
        if daglp.returncode != 0:
            raise ProcessingError(daglp.stderr.rstrip() or "daglp failed")

        commit_path = []
        for line in daglp.stdout.splitlines():
            parts = line.strip().split()
            sha, ts = parts[0], parts[1]
            file_name = sha_to_file.get(sha, None) if file else None
            if file and not file_name:
                continue
            commit_path.append((sha, ts, file_name))
        self.git_hot_total_commits = len(commit_path)

        prev_sha = None
        prev_file_name = None

        for sha, ts, file_name in commit_path:

            # Get the diff for this commit
            if prev_sha is None:
                # --- first commit ---
                args = [
                        "git",
                        "show",
                        "--pretty=tformat:commit %H %at",
                        "--topo-order",
                        "--reverse",
                        "-U0",
                        sha,
                        "--",
                    ]
                if file:
                    args += file_name
            else:
                # No --pretty commit header here, so construct it manually.
                yield f"commit {sha} {ts}\n"
                yield "\n"

                # --- diff with prev_sha ---
                args = [
                        "git",
                        "-c", "diff.renameLimit=30000",
                        "diff",
                        "-m", "-M", "-C", "-U0",
                        f"{prev_sha}..{sha}",
                        "--",
                    ]
                if file:
                    args += [file_name, prev_file_name]
            diff = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                **utf8_surrogateescape_text(),
            )
            self.debug_print_git(f"Run: {' '.join(args)}")

            # --- stream output ---
            for out_line in diff.stdout:
                self.debug_print_git(f"Line {self.reader.line_number}: {out_line}", end="")
                yield out_line

            diff.wait()
            prev_sha = sha
            if file:
                prev_file_name = file_name

    def process_commit_state(self):
        if self.hash is not None:
            self.process_last_commit()
        fields = self.current_line.split()
        if len(fields) < 3 or fields[0] != "commit":
            self.bail_out("Expecting commit")
        self.commit, self.hash, self.timestamp = fields[0], fields[1], fields[2]
        if self.args.compressed:
            self.print_out(f"commit {self.hash} {self.timestamp}")
        else:
            self.debug_print_commit_header(f"commit {self.hash} {self.timestamp}")
        self.report_progress()

        # Separator
        line = self.reader.read_raw()
        if line is None:
            return "EOF"
        if re.match(r"^$", line):
            line = self.reader.read_raw()
            if line is None:
                return "EOF"
            if line.startswith("diff "):
                self.current_line = chomp(line)
                return "diff"
            if line.startswith("commit "):
                # This happens on an empty commit with git diff
                self.current_line = chomp(line)
                return "commit"
            self.current_line = chomp(line)
            self.bail_out("Expecting diff, commit, or EOF")
        if line.startswith("commit "):
            # This happens on an empty commit
            self.current_line = chomp(line)
            return "commit"
        self.current_line = chomp(line)
        self.bail_out("Expecting an empty line or commit")
        return "EOF"

    def process_diff_state(self):
        # Diff header
        line = hide_escaped_quotes(self.current_line)
        match = (
            re.match(r"^diff --git a/([^ ]*) b/(.*)", line)
            or re.match(r'^diff --git "a/((?:[^"\\]|\\.)*)" "b/((?:[^"\\]|\\.)*)"', line)
            or re.match(r'^diff --git a/([^ ]*) "b/((?:[^"\\]|\\.)*)"', line)
            or re.match(r'^diff --git "a/((?:[^"\\]|\\.)*)" b/(.*)', line)
            or re.match(r"^diff --git a/(.*) b/(.*)", line)
        )
        if not match:
            self.bail_out("Expecting a diff command")
        self.old = match.group(1)
        self.new = match.group(2)
        if '"' in line:
            self.old = unescape(self.old)
            self.new = unescape(self.new)

        self.debug_print_diff_header(self.current_line)
        self.debug_print_diff_header(f"old=[{self.old}] new=[{self.new}]")

        old_file = self.flt.get(self.old)
        new_file = self.flt.get(self.new)
        self.oref = [line.copy() for line in old_file.lines] if old_file is not None else []
        self.oref_change_lifetimes = list(old_file.change_lifetimes) if old_file is not None else []
        if self.old == self.new:
            self.nref = self.oref
            self.nref_change_lifetimes = self.oref_change_lifetimes
        elif new_file is not None:
            self.nref = [line.copy() for line in new_file.lines]
            self.nref_change_lifetimes = list(new_file.change_lifetimes)
        else:
            self.nref = []
            self.nref_change_lifetimes = []

        state = "EOF"
        # Read the "extended header lines" to handle copies and renames
        from_path = None
        self.op = "inplace"
        while True:
            raw = self.reader.read_raw()
            if raw is None:
                return state
            self.debug_print_diff_extended("diff extended header: " + raw, end="")
            line = chomp(raw)
            if line.startswith("--- "):
                # Start of a file difference
                # --- a/main.c

                # +++ b/main.c
                self.reader.read_raw()

                # Range
                self.current_line = self.reader.read_chomp()
                state = "range"
                self.added_lines = 0
                self.removed_lines = 0
                return state
            match = re.match(r"^(copy|rename) from (.*)", line)
            if match:
                from_path = unquote_unescape(match.group(2))
                continue
            match = re.match(r"^rename to (.*)", line)
            if match:
                to_path = unquote_unescape(match.group(1))
                self.op = "rename"
                if from_path is None:
                    self.bail_out("Missing rename from")
                source = self.flt.get(from_path, FileDetails(from_path))
                self.cc.append({"op": "del", "path": from_path})
                self.cc.append(
                    {
                        "op": "set",
                        "path": to_path,
                        "lines": [line.copy() for line in source.lines],
                        "binary": source.binary,
                        "change_lifetimes": list(source.change_lifetimes),
                    }
                )
                self.oref = [line.copy() for line in self.flt.get(self.old, FileDetails(self.old)).lines]
                self.oref_change_lifetimes = list(
                    self.flt.get(self.old, FileDetails(self.old)).change_lifetimes
                )
                self.nref = self.oref
                self.nref_change_lifetimes = self.oref_change_lifetimes
                continue
            match = re.match(r"^copy to (.*)", line)
            if match:
                to_path = unquote_unescape(match.group(1))
                self.op = "copy"
                if from_path is None:
                    self.bail_out("Missing copy from")
                source = self.flt.get(from_path, FileDetails(from_path))
                self.cc.append(
                    {
                        "op": "set",
                        "path": to_path,
                        "lines": [line.copy() for line in source.lines],
                        "binary": source.binary,
                        "change_lifetimes": [],
                    }
                )
                if self.args.growth_file and self.output_source_code(to_path):
                    self.loc += len(source.lines)
                self.nref = [line.copy() for line in self.flt.get(self.old, FileDetails(self.old)).lines]
                self.nref_change_lifetimes = []
                continue
            if line.startswith("commit "):
                self.current_line = line
                return "commit"
            if line.startswith("diff --git "):
                self.current_line = line
                return "diff"
            if line.startswith("new file mode "):
                self.cc.append(
                    {"op": "set", "path": self.old, "lines": [], "binary": False, "change_lifetimes": []}
                )
                continue
            if line.startswith("deleted file mode "):
                self.op = "del"
                self.cc.append({"op": "del", "path": self.old})
                # Print death times of deleted file's lines
                if (
                    not self.debug_reconstruction
                    and not self.args.churn_dir
                    and not self.json_metrics_mode()
                    and self.output_source_code(self.old)
                ):
                    for line_record in self.flt.get(self.old, FileDetails(self.old)).lines:
                        if self.args.compressed:
                            self.print_out(line_record.render_record(self.args))
                        else:
                            self.delete_records.append(line_record.render_deleted(self.args, self.timestamp))
                continue
            if re.match(r"^Binary files ([^ ]*) and ([^ ]*) differ", line):
                current = self.flt.get(self.old)
                if current is None:
                    current = FileDetails(self.old)
                    self.flt[self.old] = current
                current.binary = True
                raw = self.reader.read_raw()
                if raw is None:
                    return "EOF"
                if raw.startswith("commit "):
                    self.current_line = chomp(raw)
                    return "commit"
                if raw.startswith("diff --git "):
                    self.current_line = chomp(raw)
                    return "diff"
                self.current_line = chomp(raw)
                self.bail_out("Expected diff, commit, or EOF")
        return state

    def process_range_state(self):
        # Ranges within files
        self.debug_print_range_header(self.current_line)
        fields = self.current_line.split()
        if len(fields) < 3:
            self.bail_out("Expecting a diff range")
        at1, old_range, new_range = fields[0], fields[1], fields[2]
        at2 = fields[3] if len(fields) > 3 else None
        if at1 != "@@" or at2 != "@@":
            self.bail_out("Expecting a diff range")
        try:
            old_start, old_end = range_parse(old_range)
            new_start, new_end = range_parse(new_range)
        except ProcessingError:
            self.bail_out("Expecting a diff range")

        line = self.reader.read_raw()
        new_offset = self.added_lines - self.removed_lines
        if self.oref is self.nref:
            old_offset = new_offset
        else:
            old_offset = -self.removed_lines
        old_file = self.flt.get(self.old)
        binary = old_file.binary if old_file is not None else False
        output = self.output_source_code(self.old)
        deleted_lines = []
        for i in range(old_start, old_end):
            if binary:
                line = self.reader.read_raw()
                continue
            if line is None or not line.startswith("-"):
                self.current_line = chomp(line) if line is not None else None
                self.bail_out("Expecting a removed line")
            if output:
                self.loc -= 1
            pos = i + old_offset
            if 0 <= pos < len(self.oref):
                deleted_line = self.oref[pos]
                if self.debug_reconstruction:
                    # Verify that the -removed line matches the previous +recorded one.
                    if deleted_line.content != line[1:]:
                        self.bail_out(f"Expecting at({i} + {old_offset}) {deleted_line.content}")
                elif output and not self.json_metrics_mode():
                    if self.args.compressed:
                        self.print_out(deleted_line.render_record(self.args))
                    else:
                        self.delete_records.append(deleted_line.render_deleted(self.args, self.timestamp))
                deleted_lines.append(deleted_line.copy())
                self.oref_change_lifetimes.append(int(self.timestamp) - deleted_line.birth_timestamp)
            else:
                print(
                    f"Warning: {self.hash} line {self.reader.line_number} unencountered line {self.old}:{i + 1}",
                    file=sys.stderr,
                )
            line = self.reader.read_raw()
        remove_len = old_end - old_start
        self.debug_print_splice(f"before oref={len(self.oref) - 1} ns={old_start} len={remove_len}")
        if not binary and remove_len != 0:
            del self.oref[old_start + old_offset : old_start + old_offset + remove_len]
            if self.oref is not self.nref:
                del self.nref[old_start + new_offset : old_start + new_offset + remove_len]
        self.debug_print_splice(f"after oref={len(self.oref) - 1}")
        if line is not None and line.startswith("\\ No newline at end of file"):
            line = self.reader.read_raw()
        add = []
        line_count = 0
        equal_length_change = old_end - old_start == new_end - new_start
        for i in range(new_start, new_end):
            if line is None or not line.startswith("+"):
                self.current_line = chomp(line) if line is not None else None
                self.bail_out("Expecting an added line")
            if equal_length_change and line_count < len(deleted_lines):
                prior_line = deleted_lines[line_count]
                churn_count = prior_line.churn_count + 1
                change_lifetimes = list(prior_line.change_lifetimes)
                change_lifetimes.append(int(self.timestamp) - prior_line.birth_timestamp)
                content_history = prior_line.content_history + [line[1:]]
            else:
                churn_count = 0
                change_lifetimes = []
                content_history = None
            new_line = LineDetails(
                content=line[1:],
                birth_timestamp=int(self.timestamp),
                birth_hash=self.hash,
                content_history=content_history,
                churn_count=churn_count,
                change_lifetimes=change_lifetimes,
            )
            if self.args.line_details:
                counts = line_details(line[1:])
                new_line.length = counts.length
                new_line.startspace = counts.startspace
                new_line.string = counts.string
                new_line.comment = counts.comment
                new_line.comma = counts.comma
                new_line.bracket = counts.bracket
                new_line.access = counts.access
                new_line.assignment = counts.assignment
                new_line.scope = counts.scope
                new_line.array = counts.array
                new_line.logical = counts.logical
            add.append(new_line)
            if not binary and output:
                self.loc += 1
            line_count += 1
            line = self.reader.read_raw()
        add_len = new_end - new_start
        self.debug_print_splice(f"before nref={len(self.nref) - 1} ns={new_start} len={add_len}")
        if not binary and add_len > 0:
            self.nref[new_start:new_start] = add
        self.added_lines += add_len
        self.removed_lines += remove_len
        self.debug_print_splice(f"after nref={len(self.nref) - 1}")
        if line is not None and line.startswith("\\ No newline at end of file"):
            line = self.reader.read_raw()
        if line is None:
            self.push_to_cc()
            return "EOF"
        if line.startswith("@@ "):
            self.current_line = chomp(line)
            return "range"
        if line.startswith("diff --git "):
            self.current_line = chomp(line)
            self.push_to_cc()
            return "diff"
        if line.startswith("commit "):
            self.current_line = chomp(line)
            self.push_to_cc()
            return "commit"
        self.current_line = chomp(line)
        self.bail_out("Expected diff, @@, commit, or EOF")
        return "EOF"

    # Write the commit's effect on the project's LOC value
    def process_last_commit(self):
        if self.hash is None:
            return
        delta = self.loc - self.prev_loc

        self.debug_print_loc(f"prev_loc={self.prev_loc} loc={self.loc} delta={delta}")

        # Print records of deleted lines
        eol = f" {delta}\n" if self.args.delta else "\n"
        if not self.args.file_metrics and not self.selected_file_details_mode() and not self.json_metrics_mode():
            for record in self.delete_records:
                print(record, end=eol, file=self.out)
        self.delete_records = []

        self.commit_changes()
        if self.growth_file is not None:
            print(f"{self.timestamp} {self.loc}", file=self.growth_file)
        self.prev_loc = self.loc

    # Reconstruct the state of the Git tree based on the log
    def reconstruct(self):
        base_dir = self.args.churn_dir or "RECONSTRUCTION"
        shutil.rmtree(base_dir, ignore_errors=True)
        for path, details in self.flt.items():
            if path == "/dev/null":
                continue
            if details is None:
                continue
            full_path = os.path.join(base_dir, *path.split("/"))
            directory = os.path.dirname(full_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(full_path, "w", encoding="utf-8", errors="surrogateescape", newline="") as out:
                self.write_reconstructed_lines(out, details)

    def write_reconstructed_lines(self, out, details):
        current_timestamp = int(self.timestamp) if self.timestamp is not None else 0
        repo_line_churns, repo_line_ages, repo_line_change_lifetimes = self.repo_line_populations(current_timestamp)
        self.line_formatter.bind_file(
            details,
            current_timestamp,
            repo_line_churns,
            repo_line_ages,
            repo_line_change_lifetimes,
        )
        for line in details.lines:
            out.write(self.line_formatter.format(line))

    def dump_selected_file_details(self):
        """Write the reconstructed contents of a selected git-hot path to stdout."""
        if not self.selected_file_details_mode():
            return False
        for path, details in self.flt.items():
            if path == "/dev/null" or details is None:
                continue
            self.write_reconstructed_lines(self.out, details)
        return True

    def dump_alive(self):
        """Print birth timestamps of files that are still alive."""
        if self.args.compressed:
            self.print_out("END")
            eol = "\n"
        else:
            eol = " alive NA\n"

        # For each file
        for path, details in self.flt.items():
            if path == "/dev/null":
                continue
            if details is None:
                continue
            if not self.output_source_code(path):
                continue
            for line in details.lines:
                print(line.render_record(self.args), end=eol, file=self.out)

    def dump_file_metrics(self):
        current_timestamp = int(self.timestamp)
        repo_line_churns, repo_line_ages, repo_line_change_lifetimes = self.repo_line_populations(current_timestamp)
        self.file_formatter.bind_repo(repo_line_churns, repo_line_ages, repo_line_change_lifetimes)
        for path in sorted(self.flt):
            if path == "/dev/null":
                continue
            details = self.flt[path]
            if details is None:
                continue
            if not self.output_source_code(path):
                continue
            churns = [line.churn_count for line in details.lines]
            change_lifetimes = list(details.change_lifetimes)
            ages = [current_timestamp - line.birth_timestamp for line in details.lines]
            print(
                self.file_formatter.format(path, churns, change_lifetimes, ages),
                file=self.out,
            )

    def dump_json_metrics(self):
        """Write all collected file and line metrics as JSON."""
        current_timestamp = int(self.timestamp) if self.timestamp is not None else 0
        files = []
        for path in sorted(self.flt):
            if path == "/dev/null":
                continue
            details = self.flt[path]
            if details is None:
                continue
            if not self.output_source_code(path):
                continue
            files.append(self.json_file_metrics(path, details, current_timestamp))
        json.dump(
            {
                "commit": self.hash,
                "timestamp": current_timestamp,
                "files": files,
            },
            self.out,
            ensure_ascii=False,
            indent=2,
        )
        print(file=self.out)

    def json_file_metrics(self, path, details, current_timestamp):
        """Return JSON-serializable metrics for a single tracked file."""
        return {
            "path": path,
            "binary": details.binary,
            "change_lifetimes": list(details.change_lifetimes),
            "lines": [
                self.json_line_metrics(index, line, current_timestamp)
                for index, line in enumerate(details.lines, start=1)
            ],
        }

    def json_line_metrics(self, line_number, line, current_timestamp):
        """Return JSON-serializable metrics for a single tracked line."""
        return {
            "line_number": line_number,
            "content": line.content,
            "contents": list(line.content_history),
            "birth_timestamp": line.birth_timestamp,
            "birth_hash": line.birth_hash,
            "age": current_timestamp - line.birth_timestamp,
            "churn": line.churn_count,
            "change_lifetimes": list(line.change_lifetimes),
            "delta": line.delta,
            "length": line.length,
            "startspace": line.startspace,
            "string": line.string,
            "comment": line.comment,
            "comma": line.comma,
            "bracket": line.bracket,
            "access": line.access,
            "assignment": line.assignment,
            "scope": line.scope,
            "array": line.array,
            "logical": line.logical,
        }

    def repo_line_populations(self, current_timestamp):
        repo_line_churns = []
        repo_line_ages = []
        repo_line_change_lifetimes = []
        for path, details in self.flt.items():
            if path == "/dev/null" or details is None:
                continue
            repo_line_churns.append([line.churn_count for line in details.lines])
            repo_line_ages.append([current_timestamp - line.birth_timestamp for line in details.lines])
            repo_line_change_lifetimes.append([list(line.change_lifetimes) for line in details.lines])
        return repo_line_churns, repo_line_ages, repo_line_change_lifetimes

    def bail_out(self, expect):
        context = self.current_line
        if context is None:
            context = "EOF"
        raise ProcessingError(
            f"commit {self.hash} {self.timestamp}; line {self.reader.line_number}: "
            f"unexpected {context} ({expect})"
        )

    # Commit the commit changes recorded in @cc
    def commit_changes(self):
        for rec in self.cc:
            self.debug_print_commit_changes(f"Change ({rec['op']}) {rec['path']}")
            if rec["op"] == "set":
                lines = rec["lines"]
                # Mark lines coming from commits with the commit's size
                if self.args.delta:
                    delta = self.loc - self.prev_loc
                    for line in lines:
                        line.delta = delta
                self.flt[rec["path"]] = FileDetails(
                    rec["path"],
                    lines,
                    rec.get("binary", False),
                    rec.get("change_lifetimes", self.flt.get(rec["path"], FileDetails(rec["path"])).change_lifetimes),
                )
            elif rec["op"] == "del":
                self.flt.pop(rec["path"], None)
            else:
                self.bail_out(f"Unknown change record {rec['op']}")
        self.cc = []

        # Check if used has specified to stop at this commit.
        if self.args.end_hash is not None and self.args.end_hash == self.hash:
            self.reconstruct()
            raise SystemExit(0)

    # Push the old and new references to the change set
    def push_to_cc(self):
        self.debug_print_push_cc(f"op={self.op} {self.old} {self.new}")
        if self.op == "del":
            return
        old_binary = self.flt.get(self.old).binary if self.old in self.flt else False
        new_binary = self.flt.get(self.new).binary if self.new in self.flt else old_binary
        if self.oref is not self.nref and self.op != "copy":
            self.cc.append(
                {
                    "op": "set",
                    "path": self.old,
                    "lines": self.oref,
                    "binary": old_binary,
                    "change_lifetimes": self.oref_change_lifetimes,
                }
            )
        self.cc.append(
            {
                "op": "set",
                "path": self.new,
                "lines": self.nref,
                "binary": new_binary,
                "change_lifetimes": self.nref_change_lifetimes,
            }
        )

    def output_source_code(self, name):
        return output_source_code(name, self.args.source_only)

    def selected_file_details_mode(self):
        return getattr(self.args, "path", None) is not None and not self.args.churn_dir

    def json_metrics_mode(self):
        return getattr(self.args, "json_metrics", False)

def lifetime_argument_parser():
    """Return a CLI parser for the original script used for research"""
    parser = argparse.ArgumentParser(
        prog="lifetime",
        description="Explore line lifetime and churn"
    )
    parser.add_argument("-c", dest="compressed", action="store_true", help='Output in a compressed format: line death times can be obtained from commit markers and alive lines appear after a line marked END.')
    parser.add_argument("-C", dest="churn_dir", metavar="dir", help="Reconstruct source files with lines preceded by churn count")
    parser.add_argument("-d", dest="delta", action="store_true", help="Report the LoC delta")
    parser.add_argument("-e", dest="end_hash", metavar="SHA", help="End processing after the specified commit hash")
    parser.add_argument("-E", dest="redirect_output", action="store_true", help="Redirect output to stderr")
    parser.add_argument("-f", dest="file_metrics", action="store_true", help="List current files with churn and age metrics")
    parser.add_argument("-g", dest="growth_file", metavar="file", help="Create a file with total LoC for each commit")
    parser.add_argument("-j", dest="json_metrics", action="store_true", help="Output collected file and line metrics as JSON")
    parser.add_argument("-l", dest="line_details", action="store_true", help="Output number of token types contained in each line")
    parser.add_argument("-s", dest="source_only", action="store_true", help="Report only source code files")
    parser.add_argument("-t", dest="tokens", action="store_true", help="Show tokens with lifetime")
    parser.add_argument("--format", dest="output_format",
                        default=None,
                        help="Format output using a Python f-string",
                        )
    parser.add_argument("input_files", nargs="*")
    return parser


def git_hot_argument_parser():
    """Return a CLI parser for the git-hot Git extension."""

    parser = argparse.ArgumentParser(
        prog="git-hot",
        description="Report code lifetime and churn.",
        usage="%(prog)s [-h] [-d dir] [-q] [ref] [[--] path]",
        add_help=True,
    )

    parser.add_argument(
        "-d", "--dir",
        metavar="dir",
        dest="churn_dir",
        help="Reconstruct source files with lines preceded by churn count",
    )

    parser.add_argument(
        "--format",
        dest="output_format",
        default=None,
        help="Format file output using a Python f-string",
    )

    parser.add_argument(
        "ref",
        nargs="?",
        default=None,
        help="Git reference",
    )

    parser.add_argument(
        "path",
        nargs="?",
        help="Report line details for the specified file",
    )
    return parser

def parse_main_args(argv=None, prog=None):
    """Parse command-line arguments for the selected CLI variant."""

    # The program offers two different CLIs. Choose based on invocation name.
    prog = prog or sys.argv[0]
    if "git-hot" in prog:
        parser = git_hot_argument_parser()
        git_hot = True
    else:
        parser = lifetime_argument_parser()
        git_hot = False

    parser.add_argument("-q", "--quiet", dest="quiet", action="store_true",
                        help="Quiet progress output")
    parser.add_argument("-D", "--debug", dest="debug_options", metavar="opts",
                        help="Debug as specified by the letters in opts")
    parser.add_argument(
        "--color",
        choices=["always", "never"],
        default=None,
        help="Control colored output",
    )

    parser.add_argument(
        "--color-domain",
        choices=["churn", "age", "lifetime"],
        default="churn",
        help="Color lines by churn, age, or lifetime",
    )


    # Custom argument parsing for the Git "[ref] [[--] path]" convention
    argv = sys.argv[1:] if argv is None else list(argv)

    if git_hot and "--" in argv:
        idx = argv.index("--")
        pre = argv[:idx]
        post = argv[idx + 1:]

        if len(post) > 1:
            parser.error("at most one path allowed after --")

        args = parser.parse_args(pre)

        if getattr(args, "path", None) is not None:
            parser.error("path specified before --")

        args.path = post[0] if post else None
        return args

    return parser.parse_args(argv)


def main(argv=None):
    try:
        args = parse_main_args(argv)
        processor = Processor(args)
        processor.run()
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except ProcessingError as exc:
        print_stderr_line(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
