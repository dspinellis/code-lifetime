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
import os
import re
import shutil
import sys
import unittest

VERSION = "0.1"
ESCAPED_QUOTE = "\001"


class LifetimeError(Exception):
    """Fatal processing error reported without an exception trace."""


class LifetimeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise LifetimeError(f"argument error: {message}")


class FileDetails:
    """Details tracked for a file while processing the diff stream."""

    def __init__(self, path, lines=None, binary=False):
        self.path = path
        self.lines = list(lines) if lines is not None else []
        self.binary = binary

    def copy(self, path=None):
        return FileDetails(self.path if path is None else path, self.lines, self.binary)


class LineDetails:
    """Details about a line's composition."""

    def __init__(
        self,
        length,
        startspace,
        string,
        comment,
        comma,
        bracket,
        access,
        assignment,
        scope,
        array,
        logical,
    ):
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


class InputReader:
    def __init__(self, paths):
        self.paths = paths
        self.line_number = 0
        self._index = 0
        self._current = None
        self._close_current = False

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

    def read_raw(self):
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

    def read_chomp(self):
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
    raise LifetimeError("Expecting a diff range")


# Return true if we are supposed to output details regarding the specified file
# (if no -s option was passed or the file contains source code)
def output_source_code(name, source_only=False):
    if not source_only:
        return True
    # Keep tokenize.pl:tokenize, lifetime.pl:output_source_code, repo-metrics-report.sh, analyze-moves.sh in sync
    return (
        re.search(
            r"\.(C|c|cc|cpp|cs|cxx|hh|hpp|h\+\+|c\+\+|h|H|hxx|java|((php[3457s]?)|pht|php-s)|py)$",
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
    return str(
        LineDetails(
            length,
            startspace,
            string,
            comment,
            comma,
            bracket,
            access,
            assignment,
            scope,
            array,
            logical,
        )
    )


def str_equal(expected, obtained):
    if expected != obtained:
        raise AssertionError(f"Expected\t[{expected}]\nObtained\t[{obtained}]")


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


def test_line_details():
    # l s s c c b a a s a l
    str_equal("2 0 0 0 0 0 0 0 0 0 0", line_details("xx"))
    str_equal("3 0 1 0 0 0 0 0 0 0 0", line_details("'x'"))
    str_equal("3 0 0 1 0 0 0 0 0 0 0", line_details("#x("))
    str_equal("3 0 0 1 0 0 0 0 0 0 0", line_details("/*("))
    str_equal("3 0 0 1 0 0 0 0 0 0 0", line_details("//("))
    str_equal("5 0 0 0 2 0 0 0 0 0 0", line_details("a,b,c"))
    str_equal("2 0 0 0 0 2 0 0 0 0 0", line_details("(("))
    str_equal("3 0 0 0 0 0 1 0 0 0 0", line_details("a.b"))
    str_equal("4 0 0 0 0 0 1 0 0 0 0", line_details("a->b"))
    str_equal("3 0 0 0 0 0 0 0 0 0 0", line_details("1.2"))
    str_equal("3 0 0 0 0 0 0 1 0 0 0", line_details("a=b"))
    str_equal("5 0 0 0 0 0 0 1 0 0 0", line_details("a<<=b"))
    str_equal("4 0 0 0 0 0 0 1 0 0 0", line_details("a*=b"))
    str_equal("1 0 0 0 0 0 0 0 1 0 0", line_details("{"))
    str_equal("2 0 0 0 0 0 0 0 1 0 0", line_details(": "))
    str_equal("2 0 0 0 0 0 0 0 1 0 0", line_details("x:"))
    str_equal("1 0 0 0 0 0 0 0 0 1 0", line_details("["))
    str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details("=="))
    str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details("a>="))
    str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details("b<="))
    str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details("!="))
    str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details("a<b"))
    str_equal("4 0 0 0 0 0 0 0 0 0 0", line_details("a<<b"))
    str_equal("3 0 0 0 0 0 0 0 0 0 1", line_details("a>b"))
    str_equal("2 0 0 0 0 0 0 0 0 0 2", line_details("!!"))
    str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details("||"))
    str_equal("2 0 0 0 0 0 0 0 0 0 1", line_details("&&"))
    str_equal("7 0 0 0 0 0 0 0 0 0 1", line_details("a and b"))
    str_equal("6 0 0 0 0 0 0 0 0 0 1", line_details("a or b"))
    str_equal("5 0 0 0 0 0 0 0 0 0 1", line_details("not b"))
    str_equal("4 0 0 0 0 0 0 0 0 0 0", line_details("notb"))
    str_equal("6 0 0 0 0 0 0 0 0 0 2", line_details("is not"))
    str_equal("2 1 0 0 0 0 0 0 0 0 0", line_details(" x"))
    str_equal("4 3 0 0 0 0 0 0 0 0 0", line_details("   x"))
    str_equal("1 8 0 0 0 0 0 0 0 0 0", line_details("\t"))
    str_equal("3 16 0 0 0 0 0 0 0 0 0", line_details("\t\tx"))


class LifetimeParser:
    def __init__(self, args):
        self.args = args
        self.reader = InputReader(args.input_files)
        self.out = sys.stderr if args.redirect_output else sys.stdout
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
        self.current_line = None

    def debug_option(self, opt):
        return debug_option(self.args.debug_options, opt)

    def debug_printer(self, enabled):
        return self.print_out if enabled else self.noop_print_out

    def print_out(self, text, end="\n"):
        print(text, end=end, file=self.out)

    def noop_print_out(self, text, end="\n"):
        pass

    def run(self):
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
        if self.debug_reconstruction or self.args.churn_dir:
            self.reconstruct()
        else:
            self.dump_alive()

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
        # Report progress
        if not self.debug_reconstruction and not self.args.quiet:
            print(f"commit {self.hash} {self.timestamp}", file=sys.stderr)

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
        self.oref = list(old_file.lines) if old_file is not None else []
        if self.old == self.new:
            self.nref = self.oref
        elif new_file is not None:
            self.nref = list(new_file.lines)
        else:
            self.nref = []

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
                self.cc.append({"op": "set", "path": to_path, "lines": list(source.lines), "binary": source.binary})
                self.oref = list(self.flt.get(self.old, FileDetails(self.old)).lines)
                self.nref = self.oref
                continue
            match = re.match(r"^copy to (.*)", line)
            if match:
                to_path = unquote_unescape(match.group(1))
                self.op = "copy"
                if from_path is None:
                    self.bail_out("Missing copy from")
                source = self.flt.get(from_path, FileDetails(from_path))
                self.cc.append({"op": "set", "path": to_path, "lines": list(source.lines), "binary": source.binary})
                if self.args.growth_file and self.output_source_code(to_path):
                    self.loc += len(source.lines)
                self.nref = list(self.flt.get(self.old, FileDetails(self.old)).lines)
                continue
            if line.startswith("commit "):
                self.current_line = line
                return "commit"
            if line.startswith("diff --git "):
                self.current_line = line
                return "diff"
            if line.startswith("new file mode "):
                self.cc.append({"op": "set", "path": self.old, "lines": [], "binary": False})
                continue
            if line.startswith("deleted file mode "):
                self.op = "del"
                self.cc.append({"op": "del", "path": self.old})
                # Print death times of deleted file's lines
                if not self.debug_reconstruction and not self.args.churn_dir and self.output_source_code(self.old):
                    for line_record in self.flt.get(self.old, FileDetails(self.old)).lines:
                        if self.args.compressed:
                            self.print_out(line_record)
                        else:
                            self.delete_records.append(f"{line_record} {self.timestamp}")
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
        except LifetimeError:
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
        delete_range = []  # Churn count and content of deleted lines
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
                if self.debug_reconstruction:
                    # Verify that the -removed line matches the previous +recorded one.
                    if self.oref[pos][1:] != line[1:]:
                        self.bail_out(f"Expecting at({i} + {old_offset}) {self.oref[pos]}")
                elif self.args.churn_dir:
                    delete_range.append(self.oref[pos])
                elif output:
                    if self.args.compressed:
                        self.print_out(self.oref[pos])
                    else:
                        self.delete_records.append(f"{self.oref[pos]} {self.timestamp}")
            else:
                print(
                    f"Warning: {self.hash} line {self.reader.line_number} unknown line {self.old}:{i + 1}",
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
        for i in range(new_start, new_end):
            if line is None or not line.startswith("+"):
                self.current_line = chomp(line) if line is not None else None
                self.bail_out("Expecting an added line")
            if self.debug_reconstruction:
                add.append(line)
            elif self.args.churn_dir:
                if old_end - old_start == new_end - new_start:
                    # Increment count for single-line change.
                    match = re.match(r"^(\d+)\t(.*)", delete_range[line_count])
                    line_count += 1
                    churn_count = int(match.group(1)) + 1
                else:
                    churn_count = 0
                add.append(f"{churn_count}\t{line[1:]}")
            elif self.args.line_details:
                add.append(f"{self.timestamp} L {line_details(line[1:])}")
            elif self.args.tokens:
                tokinfo = re.sub(r"^.(.*)\n", r"\1", line)
                add.append(f"{self.timestamp} {tokinfo}")
            else:
                add.append(self.timestamp)
            if not binary and output:
                self.loc += 1
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
        for record in self.delete_records:
            print(record, end=eol, file=self.out)
        self.delete_records = []

        self.commit_changes()
        if self.growth_file is not None:
            print(f"{self.timestamp} {self.loc}", file=self.growth_file)
        self.prev_loc = self.loc

    # Reconstruct the state of the Git tree based on the log
    def reconstruct(self):
        base_dir = self.args.churn_dir if self.args.churn_dir is not None else "RECONSTRUCTION"
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
                for line in details.lines:
                    out.write(line if self.args.churn_dir else line[1:])

    # Print birth timestamps of files that are still alive
    def dump_alive(self):
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
                print(line, end=eol, file=self.out)

    def bail_out(self, expect):
        context = self.current_line
        if context is None:
            context = "EOF"
        raise LifetimeError(
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
                    for index, line in enumerate(lines):
                        if self.args.tokens or self.args.line_details:
                            lines[index] = re.sub(
                                rf"^{re.escape(self.timestamp)} ([A-Z])",
                                f"{self.timestamp} {delta} " + r"\1",
                                line,
                            )
                        elif line == self.timestamp:
                            lines[index] = f"{line} {delta}"
                self.flt[rec["path"]] = FileDetails(rec["path"], lines, rec.get("binary", False))
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
            self.cc.append({"op": "set", "path": self.old, "lines": self.oref, "binary": old_binary})
        self.cc.append({"op": "set", "path": self.new, "lines": self.nref, "binary": new_binary})

    def output_source_code(self, name):
        return output_source_code(name, self.args.source_only)


class LineDetailsTests(unittest.TestCase):
    def test_line_details(self):
        test_line_details()

    def test_range_parse(self):
        self.assertEqual((0, 1), range_parse("-1"))
        self.assertEqual((4, 7), range_parse("+5,3"))
        self.assertEqual((0, 0), range_parse("-7,0"))

    def test_unescape(self):
        self.assertEqual('a"b', unescape("a" + ESCAPED_QUOTE + "b"))
        self.assertEqual("a\tb\nc", unescape(r"a\tb\nc"))
        self.assertEqual("a b", unescape(r"a\040b"))

    def test_output_source_code(self):
        self.assertTrue(output_source_code("main.c", True))
        self.assertTrue(output_source_code("tool.py", True))
        self.assertFalse(output_source_code("README.md", True))


def build_argument_parser():
    parser = LifetimeArgumentParser(
        usage="%(prog)s [options ...] [input file ...]",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=None,
    )
    parser.add_argument("-c", dest="compressed", action="store_true", help='Output in "compressed" format')
    parser.add_argument("-C", dest="churn_dir", metavar="dir", help="Reconstruct source lines preceded by churn counts")
    parser.add_argument("-d", dest="delta", action="store_true", help="Report the LoC delta")
    parser.add_argument("-D", dest="debug_options", metavar="opts", help="Debug as specified by the letters in opts")
    parser.add_argument("-e", dest="end_hash", metavar="SHA", help="End processing after the specified commit hash")
    parser.add_argument("-E", dest="redirect_output", action="store_true", help="Redirect output to stderr")
    parser.add_argument("-g", dest="growth_file", metavar="file", help="Create a growth file")
    parser.add_argument("-h", "--help", action="help", help="Print usage information and exit")
    parser.add_argument("-l", dest="line_details", action="store_true", help="Associate line composition details")
    parser.add_argument("-q", dest="quiet", action="store_true", help="Quiet progress output")
    parser.add_argument("-s", dest="source_only", action="store_true", help="Report only source code files")
    parser.add_argument("-t", dest="tokens", action="store_true", help="Show tokens with lifetime")
    parser.add_argument("input_files", nargs="*")
    return parser


def main(argv=None):
    parser = build_argument_parser()
    try:
        args = parser.parse_args(argv)
        if debug_option(args.debug_options, "u"):
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(LineDetailsTests)
            result = unittest.TextTestRunner(stream=sys.stdout, verbosity=1).run(suite)
            return 0 if result.wasSuccessful() else 1
        parser_instance = LifetimeParser(args)
        parser_instance.run()
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except (Exception) as exc:
        print_stderr_line(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
