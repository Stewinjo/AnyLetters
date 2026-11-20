"""Tests for bakeable defaults used by packaged builds."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import bake_defaults
import main


class BakeDefaultsTests(unittest.TestCase):
    """Writing and reading defaults.json for packaged builds."""

    def test_stock_defaults_fill_missing_file(self) -> None:
        """A missing file still returns the stock language and length."""

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "defaults.json")
            data = bake_defaults.load_defaults(path)
        self.assertEqual(data["lang"], "en")
        self.assertEqual(data["length"], 6)
        self.assertEqual(data["difficulty"], "medium")
        self.assertFalse(data["disable_solution_filters"])
        self.assertEqual(data["exe_name"], "AnyLetters")
        self.assertTrue(data["hide_secret"])

    def test_main_writes_and_requires_solutions(self) -> None:
        """Bake updates defaults and can require a solutions file."""

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "defaults.json")
            solutions = os.path.join(folder, "solutions")
            os.makedirs(solutions)
            with open(
                os.path.join(solutions, "de6.txt"), "w", encoding="utf-8"
            ) as handle:
                handle.write("Hachen\n")

            previous = os.getcwd()
            try:
                os.chdir(folder)
                with mock.patch.object(bake_defaults, "DEFAULTS_PATH", path):
                    code = bake_defaults.main(
                        [
                            "--lang",
                            "de",
                            "--length",
                            "6",
                            "--difficulty",
                            "easy",
                            "--exe-name",
                            "AnyLettersDE",
                            "--require-solutions",
                        ]
                    )
            finally:
                os.chdir(previous)

            self.assertEqual(code, 0)
            with open(path, "r", encoding="utf-8") as handle:
                written = json.load(handle)
            self.assertEqual(written["lang"], "de")
            self.assertEqual(written["length"], 6)
            self.assertEqual(written["difficulty"], "easy")
            self.assertEqual(written["exe_name"], "AnyLettersDE")

    def test_require_solutions_fails_when_missing(self) -> None:
        """--require-solutions exits non-zero without the matching list."""

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "defaults.json")
            previous = os.getcwd()
            try:
                os.chdir(folder)
                with mock.patch.object(bake_defaults, "DEFAULTS_PATH", path):
                    code = bake_defaults.main(
                        ["--lang", "de", "--length", "6", "--require-solutions"]
                    )
            finally:
                os.chdir(previous)
        self.assertEqual(code, 1)

    def test_parser_uses_baked_defaults(self) -> None:
        """Argparse defaults come from the baked dictionary."""

        baked = {
            "lang": "de",
            "length": 8,
            "difficulty": "easy",
            "disable_solution_filters": True,
            "exe_name": "AnyLettersDE",
            "hide_secret": False,
        }
        parser = main._build_arg_parser(baked)
        args = parser.parse_args([])
        self.assertEqual(args.lang, "de")
        self.assertEqual(args.length, 8)
        self.assertEqual(args.difficulty, "easy")
        self.assertTrue(args.disable_solution_filters)
        self.assertFalse(args.hide_secret)
        shown = parser.parse_args(["--show-secret"])
        self.assertFalse(shown.hide_secret)
        hidden = parser.parse_args(["--hide-secret"])
        self.assertTrue(hidden.hide_secret)

    def test_load_baked_defaults_from_resource_path(self) -> None:
        """load_baked_defaults reads the resource-path JSON file."""

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "defaults.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "lang": "en-gb",
                        "length": 5,
                        "difficulty": "hard",
                        "disable_solution_filters": False,
                        "exe_name": "LettersUK",
                        "hide_secret": False,
                    },
                    handle,
                )
            with mock.patch.object(main, "_resource_path", return_value=path):
                loaded = main.load_baked_defaults()
        self.assertEqual(loaded["lang"], "en-gb")
        self.assertEqual(loaded["length"], 5)
        self.assertEqual(loaded["difficulty"], "hard")
        self.assertEqual(loaded["exe_name"], "LettersUK")
        self.assertFalse(loaded["hide_secret"])

    def test_bake_show_secret_flag(self) -> None:
        """--show-secret bakes hide_secret=false."""

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "defaults.json")
            with mock.patch.object(bake_defaults, "DEFAULTS_PATH", path):
                code = bake_defaults.main(["--show-secret"])
            self.assertEqual(code, 0)
            with open(path, "r", encoding="utf-8") as handle:
                written = json.load(handle)
            self.assertFalse(written["hide_secret"])


if __name__ == "__main__":
    unittest.main()
