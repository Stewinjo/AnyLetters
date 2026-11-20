"""Tests for dictionary validation, scoring, filters, and difficulty."""

from __future__ import annotations

import logging
import os
import tempfile
import unittest
from unittest import mock

import filter as word_filter
import main


def _repo_root() -> str:
    """Return the repository root that contains ``main.py``."""

    return os.path.dirname(os.path.abspath(main.__file__))


def _write_pair(folder: str, aff_text: str, dic_text: str) -> None:
    """Write an ``index.aff`` / ``index.dic`` pair into ``folder``."""

    with open(os.path.join(folder, "index.aff"), "w", encoding="utf-8") as handle:
        handle.write(aff_text)
    with open(os.path.join(folder, "index.dic"), "w", encoding="utf-8") as handle:
        handle.write(dic_text)


class ScoreAndDisplayTests(unittest.TestCase):
    """Wordle scoring and single-cell character display."""

    def test_score_marks_greens_before_yellows(self) -> None:
        """Duplicate letters consume greens before yellows."""

        self.assertEqual(main.score_guess("baa", "abb"), ["Y", "Y", "B"])
        self.assertEqual(main.score_guess("abb", "abb"), ["G", "G", "G"])
        self.assertEqual(main.score_guess("aab", "abb"), ["G", "B", "G"])

    def test_score_rejects_different_lengths(self) -> None:
        """Mismatched lengths are an error instead of an index failure."""

        with self.assertRaises(ValueError):
            main.score_guess("ab", "abb")

    def test_eszett_stays_one_character(self) -> None:
        """ß must not display as the two-character uppercase SS."""

        self.assertEqual(main._display_char("ß"), "ß")
        self.assertEqual(main._display_char("é"), "É")
        self.assertEqual(main._to_key_char("ß", "de"), "ß")


class DictionaryFlagTests(unittest.TestCase):
    """Hunspell flags and affix additions."""

    def test_flag_modes_and_affix_addition(self) -> None:
        """Numeric, long, and character flags split, and slash flags do not."""

        self.assertEqual(main._split_flags("AbCd", "long"), ("Ab", "Cd"))
        self.assertEqual(main._split_flags("12,13", "num"), ("12", "13"))
        self.assertEqual(main._split_flags("ABC", "char"), ("A", "B", "C"))
        self.assertEqual(main._split_affix_add("innen/xyoc"), "innen")
        self.assertEqual(main._split_affix_add("0/xoc"), "")
        self.assertEqual(main._split_affix_add("0"), "")

    def test_forbidden_needaffix_and_slash_suffix(self) -> None:
        """Misspellings and bare stems are dropped; ``innen/flags`` is applied."""

        aff = (
            "SET UTF-8\n"
            "FORBIDDENWORD d\n"
            "NEEDAFFIX h\n"
            "ONLYINCOMPOUND o\n"
            "SFX S Y 1\n"
            "SFX S 0 s .\n"
            "SFX F Y 1\n"
            "SFX F 0 innen/xy .\n"
        )
        dic = (
            "7\n"
            "cat/S\n"
            "forest\n"
            "news\n"
            "Abblas/h\n"
            "\tThis is a comment that must not become a word\n"
            "Ärger/d\n"
            "Teil/o\n"
            "Ton/F\n"
        )
        logger = logging.getLogger("test-dictionary")
        with tempfile.TemporaryDirectory() as folder:
            _write_pair(folder, aff, dic)
            stems = main._collect_dictionary_word_data(folder, 3, logger)
            plurals = main._collect_dictionary_word_data(folder, 4, logger)
            long = main._collect_dictionary_word_data(folder, 6, logger)
            feminine = main._collect_dictionary_word_data(folder, 8, logger)

        self.assertIn("cat", stems.base_words)
        self.assertIn("cats", plurals.affixed_words)
        self.assertIn("news", plurals.base_words)
        self.assertNotIn("teil", plurals.combined)
        self.assertIn("forest", long.base_words)
        self.assertIn("abblas", long.catalog)
        self.assertNotIn("abblas", long.combined)
        self.assertNotIn("ärger", long.catalog)
        self.assertNotIn("teil", plurals.catalog)
        self.assertIn("toninnen", feminine.affixed_words)
        self.assertNotIn("toninnen/xy", feminine.combined)

    def test_validator_keeps_real_words(self) -> None:
        """Guesses include news and forest, and exclude a forbidden stem."""

        aff = "SET UTF-8\nFORBIDDENWORD d\nNEEDAFFIX h\n"
        dic = "4\nforest\nnews\nAbblas/h\nÄrgeramt/d\n"
        logger = logging.getLogger("test-validator")
        with tempfile.TemporaryDirectory() as folder:
            _write_pair(folder, aff, dic)
            cache_dir = os.path.join(folder, "cache")

            def cache_path(lang: str, word_length: int) -> str:
                os.makedirs(cache_dir, exist_ok=True)
                return os.path.join(cache_dir, f"{lang}_{word_length}.txt")

            with mock.patch("main.cache_path", cache_path):
                validator, data = main.build_validator(folder, [], "de", 6)
                short_validator, _short = main.build_validator(folder, [], "de", 4)
            self.assertTrue(validator("forest"))
            self.assertTrue(short_validator("news"))
            self.assertFalse(validator("news"))
            self.assertFalse(validator("abblas"))
            self.assertFalse(validator("ärgeramt"))
            self.assertIsNotNone(data)
            assert data is not None
            self.assertIn("forest", data.base_words)
            self.assertNotIn("abblas", data.combined)

    def test_numeric_flags_generate_the_suffix(self) -> None:
        """``FLAG num`` keeps multi-digit flags intact."""

        aff = "SET UTF-8\nFLAG num\nSFX 12 Y 1\nSFX 12 0 s .\n"
        dic = "1\ncat/12\n"
        with tempfile.TemporaryDirectory() as folder:
            _write_pair(folder, aff, dic)
            data = main._collect_dictionary_word_data(
                folder, 4, logging.getLogger("test-num")
            )
        self.assertIn("cats", data.affixed_words)
        self.assertIn("cat", data.catalog)

    def test_packaged_german_flags(self) -> None:
        """The bundled German dictionary declares the special flags we honor."""

        root = os.path.join(
            _repo_root(), "external", "dictionaries", "dictionaries", "de"
        )
        aff_path = os.path.join(root, "index.aff")
        dic_path = os.path.join(root, "index.dic")
        if not (os.path.isfile(aff_path) and os.path.isfile(dic_path)):
            self.skipTest("German dictionary submodule is not present")
        rules = main.parse_aff_rules(aff_path)
        self.assertIn("d", rules.forbidden_flags)
        self.assertIn("h", rules.need_affix_flags)
        self.assertIn("o", rules.only_compound_flags)
        entries = {
            word: flags
            for word, flags in main.parse_dic_entries(
                dic_path, rules.encoding, rules.flag_mode
            )
        }
        self.assertIn("d", entries["ährenamt"])
        self.assertIn("h", entries["abblas"])
        self.assertNotIn(
            "this is the dictionary file of the de_de hunspell dictionary",
            entries,
        )


class DifficultyAndFilterTests(unittest.TestCase):
    """Secret pools and blacklist matching."""

    def test_difficulty_pools_keep_real_english_words(self) -> None:
        """Endings alone do not remove chaos, forest, or sacred."""

        data = main.DictionaryWordData(
            base_words={"forest", "news", "chaos", "sacred", "running"},
            affixed_words={"cats"},
            catalog={"forest", "new", "news", "chaos", "sacred", "run", "cat"},
        )
        medium = set(main._select_solution_words(data, "en", "medium"))
        hard = set(main._select_solution_words(data, "en", "hard"))
        chaos = set(main._select_solution_words(data, "en", "chaos"))
        easy = set(main._select_solution_words(data, "en", "easy"))

        self.assertEqual(easy, medium)
        for word in ("forest", "chaos", "sacred"):
            self.assertIn(word, medium)
        self.assertNotIn("news", medium)
        self.assertNotIn("running", medium)
        self.assertFalse(main._looks_past_tense_en("seed", {"se", "seed"}))
        self.assertTrue(main._looks_past_tense_en("hoped", {"hop", "hoped"}))
        self.assertFalse(main._looks_past_tense_en("lied", {"ly", "lied"}))
        self.assertNotIn("cats", medium)
        self.assertIn("news", hard)
        self.assertIn("running", hard)
        self.assertNotIn("cats", hard)
        self.assertIn("cats", chaos)
        self.assertIn("news", chaos)

    def test_german_inflection_heuristic_is_narrow(self) -> None:
        """A trailing e or er is not enough to call a German word a plural."""

        catalog = {"freundin", "katz", "katze", "auto", "kind"}
        self.assertTrue(main._should_exclude_inflected("freundinnen", "de", catalog))
        self.assertTrue(main._should_exclude_inflected("autos", "de-at", catalog))
        self.assertFalse(main._should_exclude_inflected("katze", "de", catalog))
        self.assertFalse(main._should_exclude_inflected("kind", "de", catalog))

    def test_country_fold_and_english_words(self) -> None:
        """Umlaut countries match, and ordinary English endings stay eligible."""

        german = word_filter.apply_language_filters(
            "de",
            ["Ägypten", "Österreich", "Haus", "Türkei", "Dänemark"],
            set(),
        )
        self.assertEqual(german, ["Haus"])

        english = word_filter.apply_language_filters(
            "en",
            ["canvas", "chaos", "sacred", "forest", "egypt", "news"],
            set(),
        )
        for word in ("canvas", "chaos", "sacred", "forest", "news"):
            self.assertIn(word, english)
        self.assertNotIn("egypt", english)

    def test_keyboard_includes_language_letters(self) -> None:
        """German keys stay present and accented solution letters are added."""

        letters = main._extra_keyboard_letters("de", ["café", "straße"])
        self.assertEqual(letters[:4], ["Ä", "Ö", "Ü", "ß"])
        self.assertIn("É", letters)

    def test_difficulty_option_spelling(self) -> None:
        """The documented flag and the old misspelling both select difficulty."""

        parser = main._build_arg_parser(
            {
                "lang": "en",
                "length": 6,
                "difficulty": "medium",
                "disable_solution_filters": False,
            }
        )
        self.assertEqual(parser.parse_args(["--difficulty", "hard"]).difficulty, "hard")
        self.assertEqual(parser.parse_args(["--diffiuclty", "easy"]).difficulty, "easy")
        self.assertEqual(parser.parse_args([]).difficulty, "medium")
        self.assertIn("--difficulty", parser.format_help())

    def test_cache_names_include_version(self) -> None:
        """Old unversioned cache files are not reused after parser changes."""

        self.assertEqual(word_filter.CACHE_VERSION, "3")
        self.assertTrue(
            main.cache_path("en", 7).endswith(f"en_7_v{word_filter.CACHE_VERSION}.txt")
        )
        solution = word_filter.solution_cache_path("en", 6, "chaos", use_filters=False)
        self.assertTrue(solution.endswith("en_6_chaos_raw_v3.txt"))


if __name__ == "__main__":
    unittest.main()
