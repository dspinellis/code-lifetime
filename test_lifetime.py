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

import unittest

from lifetime import ESCAPED_QUOTE
from lifetime import hide_escaped_quotes
from lifetime import line_details
from lifetime import output_source_code
from lifetime import range_parse
from lifetime import unescape
from lifetime import unquote_unescape


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


if __name__ == "__main__":
    unittest.main()
