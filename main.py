"""AnyLetters – a variable-length word game with dictionary validation.

This module implements AnyLetters, a Wordle-style game that supports a variable
word length, configurable solutions and validates guesses using `.dic` and `.aff`.

Author: stewinjo
"""

# pylint: disable=too-many-lines

__version__ = "1.1.0"

import argparse
import codecs
import json
import logging
import os
import random
import re
import sys
import tkinter as tk
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from tkinter import font as tkfont
import unicodedata

from style import (
    BUTTON_BORDER_WIDTH,
    CELL_LABEL_HEIGHT,
    CELL_LABEL_WIDTH,
    COLORS,
    Layout,
    compute_layout,
    load_fonts,
)
from filter import (
    CACHE_VERSION,
    apply_language_filters,
    clear_filtered_solution_cache,
    load_filtered_solution_cache,
    save_filtered_solution_cache,
)

USED_SOLUTIONS: set[str] = set()
_MAX_WORD_LENGTH = 30
_DEFAULTS_FILENAME = "defaults.json"
_STOCK_DEFAULTS = {
    "lang": "en",
    "length": 6,
    "difficulty": "medium",
    "disable_solution_filters": False,
    "exe_name": "AnyLetters",
    "hide_secret": True,
}


def _resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and PyInstaller.

    Args:
        relative_path: Relative path from script directory.

    Returns:
        Absolute path to the resource.
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        # pylint: disable=protected-access
        base_path = sys._MEIPASS
    except AttributeError:
        # Running as script, use directory of main.py
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def _dictionaries_root() -> str:
    """Return the absolute path to the dictionaries submodule root."""
    return os.path.normpath(
        _resource_path(os.path.join("external", "dictionaries", "dictionaries"))
    )


def _available_dictionary_codes() -> dict[str, str]:
    """Return mapping of normalized language codes to canonical directory names."""
    root = _dictionaries_root()
    if not os.path.isdir(root):
        return {}

    mapping: dict[str, str] = {}
    for entry in sorted(os.listdir(root)):
        entry_path = os.path.join(root, entry)
        if not os.path.isdir(entry_path):
            continue
        aff_path = os.path.join(entry_path, "index.aff")
        dic_path = os.path.join(entry_path, "index.dic")
        if os.path.isfile(aff_path) and os.path.isfile(dic_path):
            mapping[entry.lower()] = entry
    return mapping


def _print_available_languages() -> int:
    """Print available language codes from the dictionaries submodule."""
    mapping = _available_dictionary_codes()
    if not mapping:
        print(
            "No dictionaries found. Ensure the dictionaries submodule is initialized "
            "with 'git submodule update --init --recursive'.",
            file=sys.stderr,
        )
        return 1

    print("Available dictionaries:")
    for canonical in sorted(mapping.values(), key=str.lower):
        print(f"  {canonical}")
    return 0


def _find_matching_dict_pairs(directory: str) -> list[tuple[str, str]]:
    """Find all matching .aff/.dic file pairs by base name.

    Args:
        directory: Directory path to search.

    Returns:
        List of (aff_path, dic_path) tuples for matching pairs.
    """
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"Dictionary directory '{directory}' does not exist.")

    pairs: list[tuple[str, str]] = []
    aff_files: dict[str, str] = {}
    dic_files: dict[str, str] = {}

    for name in os.listdir(directory):
        name_lower = name.lower()
        base_name = os.path.splitext(name)[0]
        full_path = os.path.normpath(os.path.join(directory, name))

        if name_lower.endswith(".aff"):
            aff_files[base_name] = full_path
        elif name_lower.endswith(".dic"):
            dic_files[base_name] = full_path

    # Match pairs by base name
    for base_name, aff_path in aff_files.items():
        if base_name in dic_files:
            pairs.append((aff_path, dic_files[base_name]))

    return pairs


def _load_dictionary_components(
    dict_pairs: list[tuple[str, str]], logger: logging.Logger
) -> tuple["AffRules", list[tuple[str, tuple[str, ...]]]]:
    """Load affix rules and dictionary entries from matching pairs."""

    combined_rules = AffRules()
    all_entries: list[tuple[str, tuple[str, ...]]] = []

    for aff_path, dic_path in dict_pairs:
        rules = parse_aff_rules(aff_path)
        for flag, rule_list in rules.sfx.items():
            combined_rules.sfx.setdefault(flag, []).extend(rule_list)
        for flag, rule_list in rules.pfx.items():
            combined_rules.pfx.setdefault(flag, []).extend(rule_list)
        combined_rules.forbidden_flags.update(rules.forbidden_flags)
        combined_rules.need_affix_flags.update(rules.need_affix_flags)
        combined_rules.only_compound_flags.update(rules.only_compound_flags)

        entries = parse_dic_entries(dic_path, rules.encoding, rules.flag_mode)
        all_entries.extend(entries)
        logger.info(
            "Loaded dictionary pair: %s/%s (%d entries)",
            os.path.basename(aff_path),
            os.path.basename(dic_path),
            len(entries),
        )

    return combined_rules, all_entries


def _normalize_word(word: str) -> str:
    """Normalize word to NFC Unicode and lowercase.

    Args:
        word: Word to normalize.

    Returns:
        Normalized word in NFC form and lowercase.
    """
    return unicodedata.normalize("NFC", word).lower()


def _is_letter_word(word: str) -> bool:
    """Return True when every character is a letter.

    Args:
        word: Candidate token.

    Returns:
        True for alphabetic words, including accented letters and ß.
    """

    return bool(word) and word.isalpha()


def _display_char(ch: str) -> str:
    """Return the one-cell label for a typed character.

    Python uppercases ß to the two-character string ``SS``. The board stores
    one character per cell, so ß is shown as ß.

    Args:
        ch: Character to display.

    Returns:
        A single display character when the uppercase form is one character.
    """

    if not ch:
        return ch
    if ch.casefold() == "ß":
        return "ß"
    upper = ch.upper()
    if len(upper) == 1:
        return upper
    return ch


def _split_flags(flags: str, mode: str) -> tuple[str, ...]:
    """Split a Hunspell flag field.

    Args:
        flags: Flag field from a dictionary entry, without the leading slash.
        mode: ``char``, ``long``, or ``num``.

    Returns:
        Individual flag tokens. Empty when ``flags`` is empty.
    """

    if not flags:
        return ()
    if mode == "num":
        return tuple(part for part in flags.split(",") if part)
    if mode == "long":
        pair_length = len(flags) - (len(flags) % 2)
        return tuple(flags[index : index + 2] for index in range(0, pair_length, 2))
    return tuple(flags)


def _split_affix_add(add_field: str) -> str:
    """Return the letters an affix rule appends.

    Hunspell writes continuation flags after a slash, as in ``innen/xyoc``.
    Those flags are not part of the spelling.

    Args:
        add_field: Add column from an SFX or PFX rule.

    Returns:
        Letters to append. Empty when the column is ``0``.
    """

    add = add_field.split("/", 1)[0]
    if add == "0":
        return ""
    return add


def _python_encoding(name: str) -> str:
    """Return a Python codec name for a Hunspell ``SET`` value.

    Args:
        name: Encoding token from the affix file.

    Returns:
        A codec ``codecs.lookup`` accepts, or ``utf-8`` when it does not.
    """

    cleaned = name.strip().replace("_", "-")
    if cleaned.lower() in {"utf8", "utf-8"}:
        cleaned = "utf-8"
    try:
        codecs.lookup(cleaned)
    except LookupError:
        return "utf-8"
    return cleaned


def _read_text(path: str, encoding: str) -> str:
    """Read a dictionary file, trying fallback encodings if needed.

    Args:
        path: File to read.
        encoding: Preferred encoding, usually from the affix ``SET`` line.

    Returns:
        File text without a leading byte-order mark.
    """

    for candidate in (encoding, "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=candidate) as handle:
                return handle.read().lstrip("\ufeff")
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().lstrip("\ufeff")


def _read_aff_text(path: str) -> tuple[str, str]:
    """Read an affix file and detect its ``SET`` encoding.

    Args:
        path: Path to the ``.aff`` file.

    Returns:
        Tuple of file text and the Python encoding name.
    """

    with open(path, "rb") as handle:
        raw = handle.read()
    encoding = "utf-8"
    head = raw[:4000].decode("ascii", errors="ignore")
    for line in head.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "SET":
            encoding = _python_encoding(parts[1])
            break
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        encoding = "utf-8"
    return text.lstrip("\ufeff"), encoding


def _affix_condition_matches(cond: str, stem: str, *, at_end: bool) -> bool:
    """Return True when a Hunspell condition matches ``stem``.

    Conditions are a small regular-expression subset. An invalid pattern does
    not reject the candidate.

    Args:
        cond: Condition from the affix rule. ``.`` matches any character.
        stem: Stem the condition is checked against.
        at_end: True for suffixes, which must match the end of the stem.

    Returns:
        True when the condition matches or cannot be compiled.
    """

    if not cond:
        return True
    try:
        if at_end:
            return re.search(cond + r"$", stem) is not None
        return re.match(r"^" + cond, stem) is not None
    except re.error:
        return True


def read_solutions_file(solutions_path: str) -> list[str]:
    """Read non-empty lines from a solutions file.

    Args:
        solutions_path: Path to solutions file (e.g., solutions/de6.txt or solutions/en6.txt).

    Returns:
        List of non-empty words from the file. Returns empty list if file not found.
    """
    path = os.path.normpath(_resource_path(solutions_path))

    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [w for w in (line.strip() for line in f) if w]


def pick_random_solution(candidates: list[str], word_length: int) -> str:
    """Pick a random solution of the specified length from the candidates.

    Args:
        candidates: List of candidate words.
        word_length: Required word length.

    Returns:
        Randomly selected word of specified length.

    Raises:
        ValueError: If no candidates match the required length.
    """
    filtered = list(w for w in candidates if len(w) == word_length)
    if not filtered:
        raise ValueError(
            f"No solutions of length {word_length} found in the solution list."
        )
    return random.choice(filtered)


def pick_unused_solution(candidates: list[str], word_length: int) -> str | None:
    """Pick a random solution not used yet during this session.

    Args:
        candidates: List of candidate words.
        word_length: Required word length.

    Returns:
        Randomly selected unused word, or None if all have been used.
    """
    remaining = list(
        w for w in candidates if len(w) == word_length and w not in USED_SOLUTIONS
    )
    if not remaining:
        return None
    return random.choice(remaining)


def parse_dic_entries(
    dic_path: str,
    encoding: str = "utf-8",
    flag_mode: str = "char",
) -> list[tuple[str, tuple[str, ...]]]:
    """Parse .dic entries into (base_word, flags).

    The first numeric line is the Hunspell word count and is skipped. Leading
    tab comments, morphological fields after a tab, and non-letter tokens are
    ignored.

    Args:
        dic_path: Path to the .dic file.
        encoding: Encoding declared by the matching affix file.
        flag_mode: Hunspell ``FLAG`` mode: ``char``, ``long``, or ``num``.

    Returns:
        List of (normalized word, flag tokens).

    Raises:
        OSError: If the file cannot be read.
    """

    entries: list[tuple[str, tuple[str, ...]]] = []
    first = True
    for line in _read_text(dic_path, encoding).splitlines():
        # Morphological data after a tab is not part of the word.
        head = line.split("\t", 1)[0].strip()
        if not head or any(ch.isspace() for ch in head):
            continue
        if first:
            first = False
            if head.isdigit():
                continue
        if "/" in head:
            base, flags = head.split("/", 1)
            flags = flags.split()[0] if flags.split() else ""
        else:
            base, flags = head, ""
        base_norm = _normalize_word(base)
        if not _is_letter_word(base_norm):
            continue
        entries.append((base_norm, _split_flags(flags, flag_mode)))
    return entries


class AffRules:  # pylint: disable=too-few-public-methods
    """Suffix and prefix rules plus the flags that cannot stand alone."""

    def __init__(self) -> None:
        """Initialize empty rule tables and special-flag sets."""
        self.sfx: dict[str, list[tuple[str, str, str]]] = {}
        self.pfx: dict[str, list[tuple[str, str, str]]] = {}
        self.flag_mode = "char"
        self.encoding = "utf-8"
        self.forbidden_flags: set[str] = set()
        self.need_affix_flags: set[str] = set()
        self.only_compound_flags: set[str] = set()

    def add_rule(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, is_suffix: bool, flag: str, strip: str, add: str, cond: str
    ) -> None:
        """Add an affix rule.

        Args:
            is_suffix: True for a suffix (SFX), False for a prefix (PFX).
            flag: Flag token that selects this rule group.
            strip: Characters to remove from the base word.
            add: Characters to append or prepend after stripping.
            cond: Condition pattern matched against the stem.
        """

        store = self.sfx if is_suffix else self.pfx
        store.setdefault(flag, []).append((strip, add, cond))

    def blocks_standalone(self, flags: tuple[str, ...]) -> bool:
        """Return True when the base word is not a legal standalone guess.

        Args:
            flags: Flag tokens attached to a dictionary entry.

        Returns:
            True for forbidden words, compound-only stems, and stems that
            require an affix.
        """

        flag_set = set(flags)
        if flag_set & self.forbidden_flags:
            return True
        if flag_set & self.only_compound_flags:
            return True
        if flag_set & self.need_affix_flags:
            return True
        return False

    def can_generate(self, flags: tuple[str, ...]) -> bool:
        """Return True when affixes may be applied to this entry.

        Forbidden words and compound-only stems are not expanded. Stems that
        merely need an affix are expanded, and the bare stem is rejected
        separately.

        Args:
            flags: Flag tokens attached to a dictionary entry.

        Returns:
            True when suffix or prefix rules may be applied.
        """

        flag_set = set(flags)
        if flag_set & self.forbidden_flags:
            return False
        if flag_set & self.only_compound_flags:
            return False
        return True


def _remember_special_flags(
    pending: dict[str, list[str]], tag: str, raw_flag: str
) -> bool:
    """Store a special-flag directive until ``FLAG`` mode is known.

    Args:
        pending: Lists of raw flag tokens keyed by directive name.
        tag: Affix-file directive.
        raw_flag: Flag token as written in the file.

    Returns:
        True when ``tag`` was a special-flag directive.
    """

    key = {
        "FORBIDDENWORD": "forbidden",
        "NEEDAFFIX": "need",
        "PSEUDOROOT": "need",
        "ONLYINCOMPOUND": "compound",
    }.get(tag)
    if key is None:
        return False
    pending[key].append(raw_flag)
    return True


def parse_aff_rules(aff_path: str) -> AffRules:
    """Parse affix rules and standalone-word flags from an ``.aff`` file.

    Header lines (``SFX flag Y count``) are ignored. Rule lines contribute
    strip, add, and condition. A slash in the add column marks continuation
    flags and is not treated as letters. ``FLAG``, ``FORBIDDENWORD``,
    ``NEEDAFFIX`` / ``PSEUDOROOT``, and ``ONLYINCOMPOUND`` are honored.

    Args:
        aff_path: Path to the .aff file.

    Returns:
        Parsed rules. Empty when the file is missing.

    Raises:
        OSError: If the file cannot be read.
    """

    rules = AffRules()
    if not os.path.isfile(aff_path):
        return rules

    text, encoding = _read_aff_text(aff_path)
    rules.encoding = encoding
    pending: dict[str, list[str]] = {"forbidden": [], "need": [], "compound": []}
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        parts = stripped.split()
        tag = parts[0]
        if tag == "SET" and len(parts) >= 2:
            rules.encoding = _python_encoding(parts[1])
            continue
        if tag == "FLAG" and len(parts) >= 2:
            mode = parts[1].lower()
            if mode == "num":
                rules.flag_mode = "num"
            elif mode == "long":
                rules.flag_mode = "long"
            else:
                rules.flag_mode = "char"
            continue
        if len(parts) >= 2 and _remember_special_flags(pending, tag, parts[1]):
            continue
        if tag not in ("SFX", "PFX") or len(parts) < 5:
            continue
        # Header lines look like: SFX A Y 2
        if parts[2] in ("Y", "N"):
            continue
        strip = "" if parts[2] == "0" else parts[2]
        add = _split_affix_add(parts[3])
        rules.add_rule(tag == "SFX", parts[1], strip, add, parts[4])

    rules.forbidden_flags.update(
        flag
        for raw in pending["forbidden"]
        for flag in _split_flags(raw, rules.flag_mode)
    )
    rules.need_affix_flags.update(
        flag for raw in pending["need"] for flag in _split_flags(raw, rules.flag_mode)
    )
    rules.only_compound_flags.update(
        flag
        for raw in pending["compound"]
        for flag in _split_flags(raw, rules.flag_mode)
    )
    return rules


def _apply_one_affix(
    base: str,
    strip: str,
    add: str,
    cond: str,
    word_length: int,
    *,
    is_suffix: bool,
) -> str | None:
    """Return one affixed spelling, or None when the rule does not apply.

    Args:
        base: Base word.
        strip: Characters to remove before adding.
        add: Characters to add.
        cond: Hunspell condition for the remaining stem.
        word_length: Required length of the result.
        is_suffix: True when the rule is a suffix.

    Returns:
        The affixed word, or None when it does not fit this rule and length.
    """

    if is_suffix:
        if strip and base.endswith(strip):
            stem = base[: -len(strip)]
        elif strip:
            return None
        else:
            stem = base
        if not _affix_condition_matches(cond, stem, at_end=True):
            return None
        candidate = stem + add
    else:
        if strip and base.startswith(strip):
            stem = base[len(strip) :]
        elif strip:
            return None
        else:
            stem = base
        if not _affix_condition_matches(cond, stem, at_end=False):
            return None
        candidate = add + stem
    if candidate == base or len(candidate) != word_length:
        return None
    if not candidate.isalpha():
        return None
    return candidate


def _generate_affixed_candidates(
    base: str,
    flags: tuple[str, ...],
    rules: AffRules,
    word_length: int,
) -> Iterator[str]:
    """Yield words formed by one suffix or one prefix.

    Args:
        base: Base word.
        flags: Flag tokens that select affix rules.
        rules: Parsed affix rules.
        word_length: Required length.

    Yields:
        Affixed words of ``word_length`` that contain only letters.
    """

    for flag in flags:
        for strip, add, cond in rules.sfx.get(flag, []):
            candidate = _apply_one_affix(
                base, strip, add, cond, word_length, is_suffix=True
            )
            if candidate:
                yield candidate
        for strip, add, cond in rules.pfx.get(flag, []):
            candidate = _apply_one_affix(
                base, strip, add, cond, word_length, is_suffix=False
            )
            if candidate:
                yield candidate


def expand_with_affixes(
    entries: list[tuple[str, tuple[str, ...]]],
    rules: AffRules,
    word_length: int,
) -> set[str]:
    """Generate words by applying one prefix or one suffix.

    Forbidden entries and compound-only stems are not expanded. The bare base
    words are not included here; callers decide which bases can stand alone.

    Args:
        entries: List of (base word, flag tokens).
        rules: Parsed affix rules.
        word_length: Target word length.

    Returns:
        Affixed words of the target length.
    """

    result: set[str] = set()
    for base, flags in entries:
        if not rules.can_generate(flags):
            continue
        result.update(_generate_affixed_candidates(base, flags, rules, word_length))
    return result


@dataclass(slots=True)
class DictionaryWordData:
    """Container for dictionary-derived candidate words and metadata."""

    base_words: set[str]
    affixed_words: set[str]
    catalog: set[str]

    @property
    def combined(self) -> set[str]:
        """Return the union of base and affixed word candidates."""

        return self.base_words | self.affixed_words


def _collect_dictionary_word_data(
    dict_folder: str,
    word_length: int,
    logger: logging.Logger,
) -> DictionaryWordData:
    """Collect standalone bases, affixed forms, and a stem catalog.

    Forbidden words and compound-only stems are dropped. Stems marked
    ``NEEDAFFIX`` stay in the catalog so inflections can be recognized, and
    they are omitted from the standalone base list.

    Args:
        dict_folder: Directory of matching ``.aff`` / ``.dic`` pairs.
        word_length: Target word length for bases and affixed forms.
        logger: Logger used while the dictionary files are loaded.

    Returns:
        Bases, affixed forms, and the catalog of stems.

    Raises:
        ValueError: If the dictionary files contain no usable entries.
        FileNotFoundError: If ``dict_folder`` does not exist.
    """

    dict_pairs = _find_matching_dict_pairs(dict_folder)
    combined_rules, all_entries = _load_dictionary_components(dict_pairs, logger)
    if not all_entries:
        raise ValueError(
            f"Dictionary files in '{dict_folder}' do not contain any entries."
        )

    blocked_source = combined_rules.forbidden_flags | combined_rules.only_compound_flags
    base_words: set[str] = set()
    catalog: set[str] = set()
    for base, flags in all_entries:
        if set(flags) & blocked_source:
            continue
        catalog.add(base)
        if len(base) == word_length and not combined_rules.blocks_standalone(flags):
            base_words.add(base)

    affixed_words = expand_with_affixes(all_entries, combined_rules, word_length)
    affixed_words.difference_update(base_words)
    return DictionaryWordData(
        base_words=base_words,
        affixed_words=affixed_words,
        catalog=catalog,
    )


def cache_path(lang: str, word_length: int) -> str:
    """Generate cache file path for a language and word length.

    Args:
        lang: Language code (e.g., 'de').
        word_length: Target word length.

    Returns:
        Path to the cache file in cache/ directory.
    """
    # Cache directory is created in user's working directory (not bundled)
    cache_dir = os.path.normpath(os.path.join("cache"))
    if not os.path.isdir(cache_dir):
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            pass
    return os.path.normpath(
        os.path.join(cache_dir, f"{lang}_{word_length}_v{CACHE_VERSION}.txt")
    )


def load_cache(lang: str, word_length: int) -> set[str]:
    """Load cached word list from disk.

    Args:
        lang: Language code.
        word_length: Target word length.

    Returns:
        Set of cached words, empty set if cache doesn't exist or read fails.

    Raises:
        UnicodeDecodeError: If cache file is not valid UTF-8.
        OSError: If cache file cannot be read.
    """
    path = cache_path(lang, word_length)
    if not os.path.isfile(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {w for line in f if (w := line.strip())}


def save_cache(lang: str, word_length: int, words: set[str]) -> None:
    """Save word list to cache file.

    Args:
        lang: Language code.
        word_length: Target word length.
        words: Set of words to cache.

    Raises:
        OSError: If cache file cannot be written.
    """
    path = cache_path(lang, word_length)
    with open(path, "w", encoding="utf-8") as f:
        for w in sorted(words):
            f.write(w + "\n")
    logging.getLogger("anyletters").info(
        "Cache written: %s (%d words)", path, len(words)
    )


def clear_cache(lang: str | None = None) -> None:
    """Delete cached validator word lists, optionally scoped by language code."""

    cache_dir = os.path.normpath(os.path.join("cache"))
    if not os.path.isdir(cache_dir):
        return

    target_prefix = None
    if lang:
        normalized = lang.strip().lower()
        if normalized:
            target_prefix = f"{normalized}_"

    for entry in os.listdir(cache_dir):
        entry_path = os.path.join(cache_dir, entry)
        if not os.path.isfile(entry_path):
            continue
        entry_lower = entry.lower()
        if not entry_lower.endswith(".txt"):
            continue
        if target_prefix is not None and not entry_lower.startswith(target_prefix):
            continue
        try:
            os.remove(entry_path)
        except OSError:
            continue

    if target_prefix is None:
        try:
            os.rmdir(cache_dir)
        except OSError:
            pass


def _transliterate_german(word: str) -> str:
    """Convert German umlauts and ß to ASCII equivalents.

    Args:
        word: Word that may contain German characters.

    Returns:
        Word with ä→ae, ö→oe, ü→ue, ß→ss replacements.
    """
    m = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    return "".join(m.get(ch, ch) for ch in word)


def _filter_solutions_by_length(solutions: list[str], word_length: int) -> list[str]:
    """Filter solutions list to words of specified length.

    Args:
        solutions: Full list of solution words.
        word_length: Required word length.

    Returns:
        Filtered list of words matching length.
    """
    return list(w for w in solutions if len(w) == word_length)


def _select_solution_words(
    data: DictionaryWordData,
    lang: str,
    difficulty: str,
) -> list[str]:
    """Choose the secret-word pool for a difficulty.

    Easy and medium use standalone lemmas and drop obvious inflections.
    Hard keeps every standalone lemma, including irregular plurals that are
    their own dictionary entries. Chaos also includes generated inflections.

    Args:
        data: Dictionary bases, affixed forms, and the stem catalog.
        lang: Language code.
        difficulty: One of ``easy``, ``medium``, ``hard``, or ``chaos``.

    Returns:
        Sorted candidate secrets.
    """

    normalized = (difficulty or "medium").lower()
    if normalized == "chaos":
        pool = set(data.combined)
    elif normalized == "hard":
        pool = set(data.base_words) or set(data.combined)
    else:
        pool = {
            word
            for word in data.base_words
            if not _should_exclude_inflected(word, lang, data.catalog)
        }
        if not pool:
            pool = set(data.base_words) or set(data.combined)
    return sorted(pool)


def _load_or_build_filtered_solutions(
    lang: str,
    word_length: int,
    dict_folder: str,
    logger: logging.Logger,
    difficulty: str,
    *,
    enable_filters: bool = True,
    data: DictionaryWordData | None = None,
) -> list[str]:
    """Load or generate the secret list for a language and difficulty.

    Args:
        lang: Language code.
        word_length: Target word length.
        dict_folder: Directory of dictionary files.
        logger: Logger for cache and filter messages.
        difficulty: Difficulty that selects the secret pool.
        enable_filters: When True, apply blacklist and profanity filters.
        data: Dictionary data already built for the validator, if any.

    Returns:
        Secret candidates of ``word_length``.

    Raises:
        ValueError: If the dictionary produces no candidates.
    """

    cached = load_filtered_solution_cache(
        lang,
        word_length,
        difficulty,
        use_filters=enable_filters,
    )
    cached = [word for word in cached if len(word) == word_length]
    if cached:
        logger.info(
            "Loaded solution cache for %s/%s/%s (%d words)",
            lang,
            word_length,
            difficulty,
            len(cached),
        )
        return cached

    if data is None:
        data = _collect_dictionary_word_data(dict_folder, word_length, logger)

    selected = _select_solution_words(data, lang, difficulty)
    if not selected:
        raise ValueError(
            "Dictionary candidate list empty for language "
            f"'{lang}' and length {word_length}."
        )

    if enable_filters:
        filtered = apply_language_filters(
            lang,
            selected,
            data.catalog,
            enable_filters=True,
        )
        if not filtered:
            logger.warning(
                "Filtered solution list empty for %s/%s; "
                "falling back to the unfiltered %s pool.",
                lang,
                word_length,
                difficulty,
            )
            filtered = selected
    else:
        filtered = selected
        logger.info(
            "Generated %d dictionary candidates for %s/%s without language filters.",
            len(filtered),
            lang,
            word_length,
        )

    save_filtered_solution_cache(
        lang,
        word_length,
        filtered,
        difficulty,
        use_filters=enable_filters,
    )
    logger.info(
        "Built solution cache for %s/%s/%s (%d words)",
        lang,
        word_length,
        difficulty,
        len(filtered),
    )
    return filtered


def _looks_plural_en(  # pylint: disable=too-many-return-statements,too-many-branches
    word: str, catalog: set[str]
) -> bool:
    """Heuristic to detect English plural forms using dictionary presence."""

    w = word.lower()
    if len(w) <= 3:
        return False
    if w.endswith("ies") and len(w) > 3:
        stem = w[:-3] + "y"
        if stem in catalog:
            return True
    if w.endswith("ves") and len(w) > 3:
        base_f = w[:-3] + "f"
        base_fe = w[:-3] + "fe"
        if base_f in catalog or base_fe in catalog:
            return True
    plural_suffixes = ("ses", "xes", "zes", "ches", "shes")
    if w.endswith(plural_suffixes):
        stem = w[:-2]
        if stem in catalog:
            return True
    if w.endswith("men") and len(w) > 3:
        stem = w[:-3] + "man"
        if stem in catalog:
            return True
    if w.endswith("es") and len(w) > 2:
        stem = w[:-2]
        if stem in catalog:
            return True
    if w.endswith("s") and len(w) > 2 and not w.endswith(("ss", "us", "is", "ous")):
        stem = w[:-1]
        if stem in catalog:
            return True
    return False


def _looks_past_tense_en(word: str, catalog: set[str]) -> bool:
    """Return True for an English past form whose stem is a real word.

    Two-letter remainders are ignored. Otherwise ``seed`` and ``need`` look
    like past forms whenever a short token such as ``se`` is in the dictionary.

    Args:
        word: Candidate secret.
        catalog: Dictionary stems of any length.

    Returns:
        True when the word is long enough and the recovered stem is listed.
    """

    lowered = word.lower()
    if len(lowered) <= 4:
        return False
    if lowered.endswith("ied"):
        stem = lowered[:-3] + "y"
        if len(stem) >= 3 and stem in catalog:
            return True
    if lowered.endswith("ed"):
        stem = lowered[:-2]
        if len(stem) >= 3 and stem in catalog:
            return True
    return False


def _looks_gerund_en(word: str, catalog: set[str]) -> bool:
    """Return True when an English word looks like an ``-ing`` form.

    Args:
        word: Candidate secret.
        catalog: Dictionary stems of any length.

    Returns:
        True for forms such as ``running`` whose stem is in the catalog.
        Short words such as ``king`` and ``spring`` are kept.
    """

    lowered = word.lower()
    if len(lowered) <= 5 or not lowered.endswith("ing"):
        return False
    stem = lowered[:-3]
    if len(stem) >= 3 and stem in catalog:
        return True
    if len(stem) >= 4 and stem[-1] == stem[-2] and stem[:-1] in catalog:
        return True
    return len(stem) >= 3 and (stem + "e") in catalog


def _looks_plural_de(word: str, catalog: set[str]) -> bool:
    """Return True for a likely German plural, not every word with a short ending.

    Args:
        word: Candidate secret.
        catalog: Dictionary stems of any length.

    Returns:
        True for ``-innen`` plurals and ``-s`` plurals whose singular is listed.
    """

    lowered = word.lower()
    if len(lowered) <= 4:
        return False
    if lowered.endswith("innen") and len(lowered) > 6:
        stem = lowered[:-5] + "in"
        if stem in catalog:
            return True
    if lowered.endswith("s") and not lowered.endswith("ss"):
        stem = lowered[:-1]
        if len(stem) >= 4 and stem in catalog:
            return True
    return False


def _looks_past_tense_de(word: str, catalog: set[str]) -> bool:
    """Return True for a likely German past participle with a ``ge-`` prefix.

    Args:
        word: Candidate secret.
        catalog: Dictionary stems of any length.

    Returns:
        True when ``ge`` + stem + ``t`` has ``stem + en`` in the catalog.
    """

    lowered = word.lower()
    if len(lowered) <= 5 or not lowered.startswith("ge") or not lowered.endswith("t"):
        return False
    stem = lowered[2:-1]
    return bool(stem) and (stem + "en") in catalog


def _should_exclude_inflected(word: str, lang: str, catalog: set[str]) -> bool:
    """Return True when an easy or medium secret should skip this inflection.

    Args:
        word: Candidate secret.
        lang: Language code. Regional codes such as ``en-gb`` use the base.
        catalog: Dictionary stems of any length.

    Returns:
        True when the word looks inflected for English or German.
    """

    if not catalog:
        return False
    normalized = (lang or "").lower()
    if normalized.startswith("en"):
        return (
            _looks_plural_en(word, catalog)
            or _looks_past_tense_en(word, catalog)
            or _looks_gerund_en(word, catalog)
        )
    if normalized.startswith("de"):
        return _looks_plural_de(word, catalog) or _looks_past_tense_de(word, catalog)
    return False


def build_validator(
    dict_folder: str, solutions: list[str], lang: str, word_length: int
) -> tuple[Callable[[str], bool], DictionaryWordData | None]:
    """Create a callable that validates whether a guess is a real word.

    Generates or loads a per-language, per-length cache. Forbidden words,
    compound-only stems, and bare ``NEEDAFFIX`` stems are not accepted.
    Generated inflections are accepted so guesses such as plurals still work
    when the secret list is narrower.

    Args:
        dict_folder: Directory containing .dic and .aff files.
        solutions: Solution words that are always accepted at this length.
        lang: Language code (for example, ``de`` or ``de-at``).
        word_length: Target word length.

    Returns:
        The validator and, when the dictionary was just parsed, its word data.
        The word data is ``None`` when a guess cache was loaded.
    """

    logger = logging.getLogger("anyletters")
    logger.info("Using dictionary folder: %s", dict_folder)

    allowed_len = {_normalize_word(w) for w in solutions if len(w) == word_length}
    backend_name = "solutions-only"
    data: DictionaryWordData | None = None

    cached_words = load_cache(lang, word_length)
    if cached_words:
        allowed_len = cached_words
        backend_name = "cache-only"
        logger.info(
            "Loaded cache for %s/%s: %d words", lang, word_length, len(cached_words)
        )
    else:
        data = _collect_dictionary_word_data(dict_folder, word_length, logger)
        allowed_len = data.combined
        save_cache(lang, word_length, allowed_len)
        logger.info(
            "Built cache for %s/%s: base=%d affixed=%d total=%d",
            lang,
            word_length,
            len(data.base_words),
            len(data.affixed_words),
            len(allowed_len),
        )
        backend_name = ".dic/.aff cache"

    allowed_len |= {_normalize_word(w) for w in solutions if len(w) == word_length}

    def is_valid(word: str) -> bool:
        """Check if word is valid according to dictionary and solutions.

        Args:
            word: Word to validate.

        Returns:
            True if the word is accepted.
        """

        normalized = _normalize_word(word)
        if normalized in allowed_len:
            return True
        if _is_german_lang(lang):
            alternate = _transliterate_german(normalized)
            if alternate in allowed_len:
                logger.info(
                    "Accepted via transliteration: '%s' -> '%s'", word, alternate
                )
                return True
        logger.info("Dictionary rejected: %s", word)
        return False

    setattr(is_valid, "backend", backend_name)
    setattr(is_valid, "allowed_words", allowed_len)
    return is_valid, data


def score_guess(guess: str, target: str) -> list[str]:
    """Score a guess against the target using Wordle-like rules.

    Returns a list of markers of the same length as the input words:
    - 'G' for correct letter in the correct position (green).
    - 'Y' for correct letter in the wrong position (yellow).
    - 'B' for absent letter (black).

    Duplicate handling follows Wordle rules by first marking greens, then
    allocating remaining counts for yellows.

    Args:
        guess: Guessed word.
        target: Target word to match against.

    Returns:
        List of marker characters ('G', 'Y', 'B') for each position.

    Raises:
        ValueError: If ``guess`` and ``target`` have different lengths.
    """

    if len(guess) != len(target):
        raise ValueError(
            f"Guess length {len(guess)} does not match target length {len(target)}."
        )
    length = len(target)
    result = ["B"] * length
    remaining: dict[str, int] = {}
    for i in range(length):
        g = guess[i]
        t = target[i]
        if g == t:
            result[i] = "G"
        else:
            remaining[t] = remaining.get(t, 0) + 1
    for i in range(length):
        if result[i] == "G":
            continue
        g = guess[i]
        count = remaining.get(g, 0)
        if count > 0:
            result[i] = "Y"
            remaining[g] = count - 1
    return result


def _create_cell_label(
    parent: tk.Widget, text: str, bg: str, font: tkfont.Font
) -> tk.Label:
    """Create a standardized cell label for guess/input/keyboard cells.

    Args:
        parent: Parent widget.
        text: Initial text to display.
        bg: Background color.
        font: Font object to use.

    Returns:
        Configured Label widget.
    """
    return tk.Label(
        parent,
        text=text,
        width=CELL_LABEL_WIDTH,
        height=CELL_LABEL_HEIGHT,
        bg=bg,
        fg=COLORS.primary_text,
        font=font,
    )


def _clear_input_cells(input_labels: list[tk.Label]) -> None:
    """Clear all input cell labels.

    Args:
        input_labels: List of label widgets to clear.
    """
    for lbl in input_labels:
        lbl.configure(text="")


def _is_german_lang(lang: str) -> bool:
    """Check if language is German.

    Args:
        lang: Language code string.

    Returns:
        True if language is German or a regional variant (case-insensitive).
    """
    normalized = (lang or "").lower()
    return normalized == "de" or normalized.startswith("de-")


def _to_key_char(ch: str, lang: str) -> str:
    """Map an input character to its keyboard label.

    Args:
        ch: Input character.
        lang: Language code. German keeps ß as a single key.

    Returns:
        Keyboard label for ``ch``.
    """

    if _is_german_lang(lang) and ch.casefold() == "ß":
        return "ß"
    return _display_char(ch)


def _extra_keyboard_letters(lang: str, words: list[str]) -> list[str]:
    """Return extra keyboard keys for letters outside A-Z.

    German always gets Ä, Ö, Ü, and ß. Other letters are taken from the
    current secret list, most frequent first, so accented languages stay
    typeable without building a key for every rare character.

    Args:
        lang: Language code.
        words: Words that may be chosen as secrets.

    Returns:
        Extra key labels, German letters first.
    """

    extras: list[str] = []
    seen: set[str] = set()
    if _is_german_lang(lang):
        for label in ("Ä", "Ö", "Ü", "ß"):
            extras.append(label)
            seen.add(label)
    counts: Counter[str] = Counter()
    for word in words:
        for ch in set(word):
            label = _display_char(ch)
            if not label.isalpha() or "A" <= label <= "Z" or label in seen:
                continue
            counts[label] += 1
    for label, _count in counts.most_common(36):
        extras.append(label)
        seen.add(label)
    return extras


def _log_secret_choice(
    logger: logging.Logger,
    secret_norm: str,
    *,
    hide_secret: bool,
    backend: str | None = None,
) -> None:
    """Log a newly chosen secret, optionally omitting the word itself.

    Args:
        logger: Application logger.
        secret_norm: Normalized secret word.
        hide_secret: When True, log only the length. When False, include the word.
        backend: Optional validator backend label for the first deal.
    """

    if hide_secret:
        if backend is None:
            logger.info("New secret selected (length %d).", len(secret_norm))
        else:
            logger.info(
                "Secret selected (length %d). Validator backend: %s",
                len(secret_norm),
                backend,
            )
        return
    if backend is None:
        logger.info("New secret selected: '%s'.", secret_norm)
    else:
        logger.info(
            "Secret selected: '%s' (length %d). Validator backend: %s",
            secret_norm,
            len(secret_norm),
            backend,
        )


def play_gui(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches,too-many-statements
    word_length: int,
    solutions_path: str,
    dict_folder: str,
    lang: str,
    difficulty: str,
    use_solution_filters: bool = True,
    hide_secret: bool = True,
) -> None:
    """Run the game using a Tkinter GUI.

    Displays a window with input cells, keyboard, and guess history.

    Args:
        word_length: Required word length for guesses.
        solutions_path: Path to solutions file (e.g., solutions/de6.txt).
        dict_folder: Folder containing .dic and .aff files.
        lang: Language code (e.g., 'de').
        difficulty: Difficulty preset ("easy", "medium", "hard", "chaos").
        use_solution_filters: Whether to apply language filters to dictionary-derived solutions.
        hide_secret: When False, log the chosen secret word on generation.
    """
    logger = logging.getLogger("anyletters")
    solutions_file_found = os.path.isfile(solutions_path)
    all_solutions = read_solutions_file(solutions_path)

    validator, dict_data = build_validator(
        dict_folder, all_solutions, lang, word_length
    )
    backend = getattr(validator, "backend", "Unknown")
    difficulty = difficulty.lower()
    logger.info("Difficulty selected: %s", difficulty)
    logger.info(
        "Solution filters %s",
        "enabled" if use_solution_filters else "disabled",
    )

    solutions_by_len = _filter_solutions_by_length(all_solutions, word_length)
    if not (solutions_file_found and solutions_by_len):
        filtered_solutions = _load_or_build_filtered_solutions(
            lang,
            word_length,
            dict_folder,
            logger,
            difficulty,
            enable_filters=use_solution_filters,
            data=dict_data,
        )
        if solutions_file_found:
            logger.warning(
                "Solutions file '%s' contains no words of length %d; "
                "using %d dictionary words instead.",
                solutions_path,
                word_length,
                len(filtered_solutions),
            )
        all_solutions = list(filtered_solutions)
        solutions_by_len = list(filtered_solutions)

    if not solutions_by_len:
        raise ValueError(
            f"No solutions of length {word_length} found and "
            f"no dictionary words available for language '{lang}' "
            f"with length {word_length}."
        )

    # Pick an unused secret if possible, otherwise any
    chosen = pick_unused_solution(all_solutions, word_length)
    secret = (
        chosen
        if chosen is not None
        else pick_random_solution(all_solutions, word_length)
    )
    secret_norm = _normalize_word(secret)
    secret_counts = Counter(secret_norm)
    _log_secret_choice(logger, secret_norm, hide_secret=hide_secret, backend=backend)

    root = tk.Tk()
    root.title(f"AnyLetters ({word_length})")
    root.configure(bg=COLORS.background)

    fonts = load_fonts(root, _resource_path)
    font_cell = fonts.cell
    font_count = fonts.count
    footer_font = fonts.footer
    body_font = fonts.body

    layout_state: dict[str, Layout] = {"current": compute_layout(font_cell)}

    def current_layout() -> Layout:
        """Return the layout scaled for the current font sizes."""
        return layout_state["current"]

    container = tk.Frame(root, bg=COLORS.background)
    container.pack(fill=tk.BOTH, expand=True)

    colorblind_var = tk.IntVar(value=0)

    def is_colorblind() -> bool:
        """Return True if colorblind mode is enabled."""
        return bool(colorblind_var.get())

    def color_for_marker(marker: str, for_keyboard: bool = False) -> str:
        """Return color for marker honoring colorblind mode."""
        if marker == "G":
            return COLORS.alternate_correct if is_colorblind() else COLORS.correct
        if marker == "Y":
            return COLORS.present
        return COLORS.dark_gray if for_keyboard else COLORS.cell_background

    # Prepare input buffers
    input_labels: list[tk.Label] = []
    input_chars: list[str] = []

    status_var = tk.StringVar()
    status_label = tk.Label(
        container,
        textvariable=status_var,
        fg=COLORS.status_text,
        bg=COLORS.background,
        font=body_font,
    )
    layout = current_layout()
    status_label.pack(
        padx=layout.outer_padding,
        pady=(0, layout.status_padding_bottom),
        anchor="w",
    )

    # Keyboard-like letter status (A-Z)
    keyboard_frame = tk.Frame(container, bg=COLORS.background)
    keyboard_frame.pack(
        fill=tk.X,
        padx=layout.outer_padding,
        pady=(0, layout.keyboard_padding_bottom),
    )
    letter_labels: dict[str, tk.Label] = {}
    letter_count_labels: dict[str, tk.Label] = {}
    letter_key_frames: dict[str, tk.Frame] = {}
    letters = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    rows = [letters[:13], letters[13:]]
    extra_letters = _extra_keyboard_letters(lang, solutions_by_len)
    for start in range(0, len(extra_letters), 13):
        rows.append(extra_letters[start : start + 13])
    for row_letters in rows:
        row_frame = tk.Frame(keyboard_frame, bg=COLORS.background)
        row_frame.pack()
        for ch in row_letters:
            # Start with a lighter gray; will turn darker when letter is guessed absent.
            key_container = tk.Frame(
                row_frame, bg=COLORS.light_gray, bd=0, highlightthickness=0
            )
            key_container.pack(
                side=tk.LEFT,
                padx=layout.key_padx,
                pady=layout.key_pady,
            )
            lbl = _create_cell_label(key_container, ch, COLORS.light_gray, font_cell)
            lbl.pack()
            count_lbl = tk.Label(
                key_container,
                text="",
                fg=COLORS.primary_text,
                bg=COLORS.light_gray,
                font=font_count,
                padx=0,
                pady=0,
                borderwidth=0,
                highlightthickness=0,
            )
            count_lbl.place(
                x=layout.count_label_offset_x,
                y=layout.count_label_offset_y,
                anchor="nw",
            )
            letter_labels[ch] = lbl
            letter_count_labels[ch] = count_lbl
            letter_key_frames[ch] = key_container

    multiletter_shown: set[str] = set()
    footer = tk.Frame(container, bg=COLORS.background)
    footer.pack(side=tk.BOTTOM, fill=tk.X)
    version_label = tk.Label(
        footer,
        text=f"v{__version__}",
        fg=COLORS.footer_text,
        bg=COLORS.background,
        font=footer_font,
    )
    version_label.pack(
        side=tk.RIGHT,
        padx=(0, layout.footer_version_padx),
        pady=layout.footer_version_pady,
    )

    guess_history: list[tuple[list[tk.Label], list[str]]] = []
    letter_state: dict[str, str] = {}
    colorblind_button: tk.Checkbutton | None = None
    restart_row: tk.Frame | None = None
    restart_button: tk.Button | None = None

    def apply_easy_hint() -> None:
        """Reveal a random solution letter when easy mode is active."""

        if difficulty != "easy":
            return
        if not secret_norm:
            return
        candidates = [
            ch for ch in secret_norm if _to_key_char(ch, lang) in letter_labels
        ]
        if not candidates:
            return
        hint_char = random.choice(candidates)
        key_char = _to_key_char(hint_char, lang)
        label = letter_labels.get(key_char)
        if label is None:
            return
        letter_state[key_char] = "Y"
        color = color_for_marker("Y", for_keyboard=True)
        label.configure(bg=color)
        key_frame = letter_key_frames.get(key_char)
        if key_frame is not None:
            key_frame.configure(bg=color)
        count_label = letter_count_labels.get(key_char)
        if count_label is not None:
            count_label.configure(bg=color)
        status_var.set(f"Hint: {key_char.upper()} is in the word.")

    def measure_cell_dimensions() -> tuple[int, int]:
        """Return the current rendered width and height of a guess/input cell."""

        root.update_idletasks()
        if input_labels:
            lbl = input_labels[0]
            width = lbl.winfo_width() or lbl.winfo_reqwidth()
            height = lbl.winfo_height() or lbl.winfo_reqheight()
            return width, height
        sample = _create_cell_label(container, "", COLORS.cell_background, font_cell)
        sample.update_idletasks()
        width = sample.winfo_reqwidth()
        height = sample.winfo_reqheight()
        sample.destroy()
        return width, height

    def update_restart_button_size(layout: Layout) -> None:
        """Resize restart button container to align with the guess row width."""

        if restart_button is None:
            return
        restart_container = restart_button.master
        if not isinstance(restart_container, tk.Frame):
            return

        cell_width, cell_height = measure_cell_dimensions()
        total_width = word_length * (cell_width + 2 * layout.cell_padx)
        total_height = (
            cell_height
            + 2 * layout.restart_button_internal_pady
            + 2 * BUTTON_BORDER_WIDTH
        )

        restart_container.pack_propagate(False)
        restart_container.configure(
            width=total_width + 2 * BUTTON_BORDER_WIDTH,
            height=total_height,
        )
        restart_button.configure(
            padx=layout.restart_button_internal_padx,
            pady=layout.restart_button_internal_pady,
        )

    def apply_layout(  # pylint: disable=too-many-nested-blocks
        layout: Layout,
    ) -> None:
        """Apply scaled padding and spacing across the UI."""

        status_label.pack_configure(
            padx=layout.outer_padding,
            pady=(0, layout.status_padding_bottom),
        )
        keyboard_frame.pack_configure(
            padx=layout.outer_padding,
            pady=(0, layout.keyboard_padding_bottom),
        )
        canvas.pack_configure(
            padx=layout.outer_padding,
            pady=(0, layout.outer_padding),
        )
        footer.pack_configure()
        version_label.pack_configure(
            padx=(0, layout.footer_version_padx),
            pady=layout.footer_version_pady,
        )
        if colorblind_button is not None:
            colorblind_button.configure(
                padx=layout.colorblind_internal_padx,
                pady=layout.colorblind_internal_pady,
            )
            colorblind_button.pack_configure(
                padx=layout.colorblind_pack_padx,
                pady=layout.colorblind_pack_pady,
            )

        for key_frame in letter_key_frames.values():
            key_frame.pack_configure(
                padx=layout.key_padx,
                pady=layout.key_pady,
            )
        for count_lbl in letter_count_labels.values():
            count_lbl.place_configure(
                x=layout.count_label_offset_x,
                y=layout.count_label_offset_y,
            )

        if input_row.winfo_manager() == "pack":
            input_row.pack_configure(
                padx=layout.guess_row_padx,
                pady=layout.guess_row_pady,
            )
        for lbl in input_labels:
            lbl.pack_configure(padx=layout.cell_padx)

        for child in guesses_frame.winfo_children():
            child.pack_configure(
                padx=layout.guess_row_padx,
                pady=layout.guess_row_pady,
            )
            for inner in child.winfo_children():
                if isinstance(inner, tk.Frame):
                    for widget in inner.winfo_children():
                        if isinstance(widget, tk.Label) and widget.master is inner:
                            try:
                                widget.pack_configure(padx=layout.cell_padx)
                            except tk.TclError:
                                # Widget may not be pack-managed (e.g., restart button)
                                continue

        update_restart_button_size(layout)

    def update_colorblind_button_state() -> None:
        """Update toggle button appearance/text."""
        if colorblind_button is None:
            return
        if is_colorblind():
            colorblind_button.configure(text="Colorblind On", relief=tk.SUNKEN)
        else:
            colorblind_button.configure(text="Colorblind Off", relief=tk.RAISED)

    def apply_colorblind_mode(*_args: object) -> None:
        """Reapply colors across board and keyboard when mode toggles."""
        for row_labels, row_markers in guess_history:
            for lbl, marker in zip(row_labels, row_markers):
                lbl.configure(bg=color_for_marker(marker))
        for ch, lbl in letter_labels.items():
            marker = letter_state.get(ch)
            if marker:
                color = color_for_marker(marker, for_keyboard=True)
                lbl.configure(bg=color)
                key_frame = letter_key_frames.get(ch)
                if key_frame is not None:
                    key_frame.configure(bg=color)
                count_label = letter_count_labels.get(ch)
                if count_label is not None:
                    count_label.configure(bg=color)
            else:
                lbl.configure(bg=COLORS.light_gray)
                if ch in letter_key_frames:
                    letter_key_frames[ch].configure(bg=COLORS.light_gray)
                if ch in letter_count_labels:
                    letter_count_labels[ch].configure(bg=COLORS.light_gray)
        update_colorblind_button_state()
        if restart_button is not None:
            restart_button.configure(activebackground=color_for_marker("G"))

    def toggle_colorblind() -> None:
        """Toggle colorblind mode."""
        apply_colorblind_mode()

    colorblind_button = tk.Checkbutton(
        footer,
        text="Colorblind Off",
        variable=colorblind_var,
        command=toggle_colorblind,
        bg=COLORS.footer_button_bg,
        fg=COLORS.primary_text,
        activebackground=COLORS.footer_button_active_bg,
        activeforeground=COLORS.primary_text,
        selectcolor=COLORS.alternate_correct,
        indicatoron=False,
        padx=layout.colorblind_internal_padx,
        pady=layout.colorblind_internal_pady,
        font=footer_font,
        relief=tk.RAISED,
    )
    colorblind_button.pack(
        side=tk.LEFT,
        padx=layout.colorblind_pack_padx,
        pady=layout.colorblind_pack_pady,
    )
    update_colorblind_button_state()

    # Guess area
    canvas = tk.Canvas(container, highlightthickness=0, bg=COLORS.background)
    guesses_frame = tk.Frame(canvas, bg=COLORS.background)

    guesses_frame.bind(
        "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    window_item = canvas.create_window((0, 0), window=guesses_frame, anchor="nw")

    canvas.pack(
        side=tk.LEFT,
        fill=tk.BOTH,
        expand=True,
        padx=layout.outer_padding,
        pady=(0, layout.outer_padding),
    )

    # Input row lives inside the guesses list; initially it is the first row
    input_row = tk.Frame(guesses_frame, bg=COLORS.background)
    input_row.pack(
        fill=tk.X,
        padx=layout.guess_row_padx,
        pady=layout.guess_row_pady,
    )
    input_cells = tk.Frame(input_row, bg=COLORS.background)
    input_cells.pack(anchor="center")
    for _ in range(word_length):
        lbl = _create_cell_label(input_cells, "", COLORS.cell_background, font_cell)
        lbl.pack(side=tk.LEFT, padx=layout.cell_padx)
        input_labels.append(lbl)

    apply_layout(current_layout())
    apply_easy_hint()

    def add_guess_row(guess_text: str, markers: list[str]) -> None:
        """Add a new guess row to the display.

        Args:
            guess_text: The guessed word.
            markers: List of color markers ('G', 'Y', 'B').
        """
        # Create a full-width row, then center the cells within it.
        layout_local = current_layout()
        row = tk.Frame(guesses_frame, bg=COLORS.background)
        row.pack(
            fill=tk.X,
            padx=layout_local.guess_row_padx,
            pady=layout_local.guess_row_pady,
        )
        cells = tk.Frame(row, bg=COLORS.background)
        cells.pack(anchor="center")
        color_map = {
            "G": color_for_marker("G"),
            "Y": color_for_marker("Y"),
            "B": COLORS.cell_background,
        }
        row_labels: list[tk.Label] = []
        for i, ch in enumerate(guess_text):
            bg = color_map.get(markers[i], COLORS.cell_background)
            cell = _create_cell_label(cells, _display_char(ch), bg, font_cell)
            cell.pack(side=tk.LEFT, padx=layout_local.cell_padx)
            row_labels.append(cell)

        # Keep canvas width in sync so inner frame resizes nicely
        canvas.update_idletasks()
        canvas_width = canvas.winfo_width()
        canvas.itemconfig(window_item, width=canvas_width)
        canvas.yview_moveto(1.0)

        guess_history.append((row_labels, list(markers)))

    game_over = False

    def reset_keyboard() -> None:
        """Reset all keyboard labels to default light gray color."""
        multiletter_shown.clear()
        letter_state.clear()
        for ch, lbl in letter_labels.items():
            lbl.configure(bg=COLORS.light_gray)
            if ch in letter_key_frames:
                letter_key_frames[ch].configure(bg=COLORS.light_gray)
            if ch in letter_count_labels:
                letter_count_labels[ch].configure(text="", bg=COLORS.light_gray)

    def reset_board_for_new_secret(new_secret: str) -> None:
        """Reset the game board for a new secret word.

        Args:
            new_secret: New secret word to use.
        """
        nonlocal secret, secret_norm, secret_counts, game_over, restart_row, restart_button
        secret = new_secret
        secret_norm = _normalize_word(secret)
        secret_counts = Counter(secret_norm)
        _log_secret_choice(logger, secret_norm, hide_secret=hide_secret)
        # Clear guess rows, keep input row
        for child in list(guesses_frame.winfo_children()):
            if child is not input_row:
                child.destroy()
        guess_history.clear()
        if restart_row is not None:
            restart_row.destroy()
            restart_row = None
        if restart_button is not None:
            restart_button.destroy()
            restart_button = None
        # Move input row to top
        input_row.pack_forget()
        layout_local = current_layout()
        input_row.pack(
            fill=tk.X,
            padx=layout_local.guess_row_padx,
            pady=layout_local.guess_row_pady,
        )
        # Clear input cells
        input_chars.clear()
        _clear_input_cells(input_labels)
        # Reset keyboard and state
        reset_keyboard()
        game_over = False
        status_var.set("")
        apply_easy_hint()

    def submit_guess_from_cells() -> None:  # pylint: disable=too-many-statements
        """Process and submit the current guess from input cells."""
        nonlocal game_over
        if game_over:
            return
        guess = "".join(input_chars)
        guess_norm = _normalize_word(guess)
        if len(guess) != word_length or len(guess_norm) != len(secret_norm):
            status_var.set(f"Please enter a word with exactly {word_length} letters.")
            return
        if not validator(guess):
            status_var.set("Not in dictionary.")
            return
        markers = score_guess(guess_norm, secret_norm)
        add_guess_row(guess, markers)
        update_keyboard(guess, markers)
        # Move input row visually to the next row when the game continues
        input_row.pack_forget()
        # clear input row
        input_chars.clear()
        _clear_input_cells(input_labels)
        status_var.set("")
        if guess_norm == secret_norm:
            game_over = True
            # Track used secret
            USED_SOLUTIONS.add(secret)
            # Show restart button if there are remaining unused solutions
            remaining = list(w for w in solutions_by_len if w not in USED_SOLUTIONS)
            nonlocal restart_button
            nonlocal restart_row
            if remaining:
                if restart_row is not None:
                    restart_row.destroy()
                    restart_row = None
                if restart_button is not None:
                    restart_button.destroy()
                    restart_button = None

                input_row.pack_forget()

                def do_restart() -> None:
                    """Handle restart button click."""
                    nonlocal restart_button
                    nonlocal restart_row
                    next_secret = pick_unused_solution(all_solutions, word_length)
                    if next_secret is None:
                        if restart_button is not None:
                            restart_button.destroy()
                            restart_button = None
                        if restart_row is not None:
                            restart_row.destroy()
                            restart_row = None
                        layout_local = current_layout()
                        input_row.pack(
                            fill=tk.X,
                            padx=layout_local.guess_row_padx,
                            pady=layout_local.guess_row_pady,
                        )
                        return
                    if restart_button is not None:
                        restart_button.destroy()
                        restart_button = None
                    if restart_row is not None:
                        restart_row.destroy()
                        restart_row = None
                    reset_board_for_new_secret(next_secret)

                layout_local = current_layout()
                restart_row = tk.Frame(guesses_frame, bg=COLORS.background)
                restart_row.pack(
                    fill=tk.X,
                    padx=layout_local.guess_row_padx,
                    pady=layout_local.guess_row_pady,
                )
                restart_cells = tk.Frame(restart_row, bg=COLORS.background)
                restart_cells.pack(anchor="center")

                restart_button = tk.Button(
                    restart_cells,
                    text="Restart",
                    command=do_restart,
                    bg=COLORS.cell_background,
                    fg=COLORS.primary_text,
                    activebackground=color_for_marker("G"),
                    activeforeground=COLORS.primary_text,
                    font=font_cell,
                    relief=tk.RAISED,
                    borderwidth=BUTTON_BORDER_WIDTH,
                    padx=layout_local.restart_button_internal_padx,
                    pady=layout_local.restart_button_internal_pady,
                )

                restart_cells.pack_propagate(False)
                restart_button.pack(fill=tk.X)
                update_restart_button_size(layout_local)
        else:
            layout_local = current_layout()
            input_row.pack(
                fill=tk.X,
                padx=layout_local.guess_row_padx,
                pady=layout_local.guess_row_pady,
            )

    def update_keyboard(  # pylint: disable=too-many-locals
        guess_text: str, markers: list[str]
    ) -> None:
        """Update keyboard letter colors based on guess feedback.

        Args:
            guess_text: The guessed word.
            markers: List of color markers ('G', 'Y', 'B').
        """
        rank = {"B": 0, "Y": 1, "G": 2}

        for i, raw_ch in enumerate(guess_text):
            key_char = _to_key_char(raw_ch, lang)
            if key_char not in letter_labels:
                continue
            label = letter_labels[key_char]
            new_marker = markers[i]
            new_rank = rank.get(new_marker, -1)

            existing_marker = letter_state.get(key_char)
            existing_rank = rank.get(existing_marker, -1)
            if new_rank > existing_rank:
                letter_state[key_char] = new_marker

            marker_to_apply = letter_state.get(key_char, new_marker)
            new_color = color_for_marker(marker_to_apply, for_keyboard=True)

            label.configure(bg=new_color)
            key_frame = letter_key_frames.get(key_char)
            if key_frame is not None:
                key_frame.configure(bg=new_color)
            count_label = letter_count_labels.get(key_char)
            if count_label is not None:
                count_label.configure(bg=new_color)

            if new_marker in ("G", "Y"):
                normalized_char = raw_ch.lower()
                total = secret_counts.get(normalized_char, 0)
                if total > 1 and count_label is not None:
                    count_label.configure(text=str(total))
                    multiletter_shown.add(key_char)
                elif (
                    total <= 1
                    and key_char in multiletter_shown
                    and count_label is not None
                ):
                    count_label.configure(text="", bg=new_color)
                    multiletter_shown.discard(key_char)
            else:
                if count_label is not None and key_char in multiletter_shown:
                    count_label.configure(text="", bg=new_color)
                    multiletter_shown.discard(key_char)

    def on_key(event) -> None:
        """Handle keyboard input events.

        Args:
            event: Tkinter key event.
        """
        if game_over:
            return
        ch = event.char
        # Handle Enter
        if event.keysym == "Return":
            submit_guess_from_cells()
            return
        # Handle Backspace
        if event.keysym == "BackSpace":
            if input_chars:
                idx = len(input_chars) - 1
                input_chars.pop()
                input_labels[idx].configure(text="")
            return
        if not ch:
            return
        lower = ch.lower()
        if len(lower) != 1 or not lower.isalpha():
            return
        if len(input_chars) >= word_length:
            return
        display = _display_char(lower)
        idx = len(input_chars)
        input_chars.append(lower)
        input_labels[idx].configure(text=display)

    root.bind("<Key>", on_key)

    def on_resize(event):
        """Handle canvas resize: width sync + responsive font scaling.

        Args:
            event: Tkinter configure event.
        """
        canvas.itemconfig(window_item, width=event.width)
        # Scale against a phone baseline 360x640
        scale_w = max(1.0, event.width / 360)
        # estimate height of content area from root height
        height = root.winfo_height() or 640
        scale_h = max(1.0, height / 640)
        scale = min(scale_w, scale_h)
        # Increase size by ~50% for non-smartphone modes
        if scale > 1.0:
            scale = scale * 1.5
        size_cell = max(12, int(12 * scale))
        font_cell.configure(size=size_cell)
        font_count.configure(size=max(6, int(size_cell * 0.6)))
        layout_state["current"] = compute_layout(font_cell)
        apply_layout(current_layout())

    canvas.bind("<Configure>", on_resize)

    root.minsize(360, 640)
    root.mainloop()


def load_baked_defaults() -> dict:
    """Load packaged or workspace ``defaults.json`` values.

    Missing files and keys fall back to the stock defaults. CLI flags still
    override these values when the player passes them.

    Returns:
        Defaults dictionary with ``lang``, ``length``, ``difficulty``,
        ``disable_solution_filters``, ``exe_name``, and ``hide_secret``.
    """

    defaults = dict(_STOCK_DEFAULTS)
    path = _resource_path(_DEFAULTS_FILENAME)
    if not os.path.isfile(path):
        return defaults
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logging.getLogger("anyletters").warning(
            "Could not read baked defaults from %s: %s", path, exc
        )
        return defaults
    if not isinstance(data, dict):
        return defaults
    defaults.update(data)
    return defaults


def _build_arg_parser(defaults: dict | None = None) -> argparse.ArgumentParser:
    """Return the command-line parser.

    ``--diffiuclty`` remains accepted as an alias of ``--difficulty``.
    Defaults come from ``defaults.json`` when the build baked one in.

    Args:
        defaults: Optional defaults dictionary. Loaded from disk when omitted.

    Returns:
        Configured argument parser.
    """

    baked = defaults if defaults is not None else load_baked_defaults()
    lang_default = str(baked.get("lang", _STOCK_DEFAULTS["lang"])).strip() or "en"
    try:
        length_default = int(baked.get("length", _STOCK_DEFAULTS["length"]))
    except (TypeError, ValueError):
        length_default = int(_STOCK_DEFAULTS["length"])
    difficulty_default = (
        str(baked.get("difficulty", _STOCK_DEFAULTS["difficulty"])).strip().lower()
    )
    if difficulty_default not in ("easy", "medium", "hard", "chaos"):
        difficulty_default = "medium"
    disable_filters_default = bool(
        baked.get(
            "disable_solution_filters",
            _STOCK_DEFAULTS["disable_solution_filters"],
        )
    )
    hide_secret_default = bool(baked.get("hide_secret", _STOCK_DEFAULTS["hide_secret"]))

    parser = argparse.ArgumentParser(description="AnyLetters GUI (no fail state)")
    parser.add_argument(
        "--lang",
        type=str,
        default=lang_default,
        help=f"Language code for dictionaries (default: {lang_default})",
    )
    parser.add_argument(
        "--length",
        type=int,
        default=length_default,
        help=(
            f"Word length to play with (1-{_MAX_WORD_LENGTH}; "
            f"default: {length_default})"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available dictionaries and exit",
    )
    parser.add_argument(
        "-d",
        "--difficulty",
        "--diffiuclty",
        dest="difficulty",
        type=str.lower,
        choices=["easy", "medium", "hard", "chaos"],
        default=difficulty_default,
        help=(
            "easy reveals one letter and uses lemmas; medium uses the same "
            "lemmas; hard keeps irregular inflected lemmas; chaos also allows "
            f"generated inflections (default: {difficulty_default})."
        ),
    )
    parser.add_argument(
        "--disable-solution-filters",
        action="store_true",
        default=disable_filters_default,
        help="Skip language-based filtering when generating dictionary fallback solutions.",
    )
    hide_group = parser.add_mutually_exclusive_group()
    hide_group.add_argument(
        "--hide-secret",
        dest="hide_secret",
        action="store_true",
        help=("Do not log the chosen secret word (default when hide_secret is true)."),
    )
    hide_group.add_argument(
        "--show-secret",
        dest="hide_secret",
        action="store_false",
        help="Log the chosen secret word when it is generated.",
    )
    parser.set_defaults(hide_secret=hide_secret_default)
    parser.add_argument(
        "--clear-cache",
        nargs="?",
        const="*",
        metavar="LANG",
        help=(
            "Delete cached validator words and filtered solutions. Provide a language "
            "code to only remove that language's cache."
        ),
    )
    return parser


def main() -> None:  # pylint: disable=too-many-locals,too-many-statements
    """Parse arguments for language and length, then start the GUI game."""
    # Configure logging (console)
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    baked = load_baked_defaults()
    parser = _build_arg_parser(baked)
    args = parser.parse_args()

    logger = logging.getLogger("anyletters")

    if args.clear_cache is not None:
        raw_lang = args.clear_cache
        lang_code = None
        if raw_lang != "*":
            candidate = (raw_lang or "").strip().lower()
            if candidate:
                lang_code = candidate
        clear_cache(lang_code)
        clear_filtered_solution_cache(lang_code)
        if lang_code:
            logger.info(
                "Cleared caches for language '%s' (validator + filtered solutions).",
                lang_code,
            )
        else:
            logger.info(
                "Cleared caches for all languages (validator + filtered solutions)."
            )
        return

    if args.list:
        exit_code = _print_available_languages()
        raise SystemExit(exit_code)

    available_codes = _available_dictionary_codes()
    if not available_codes:
        parser.error(
            "No dictionaries available. Initialize the dictionaries submodule with "
            "'git submodule update --init --recursive'."
        )

    lang_input = (args.lang or "").strip()
    lang_normalized = lang_input.lower() or "de"
    if lang_normalized not in available_codes:
        parser.error(
            f"Unknown language '{lang_input}'. Run with --list to see available options."
        )

    canonical_lang = available_codes[lang_normalized]
    dict_folder = os.path.join(_dictionaries_root(), canonical_lang)
    if not os.path.isdir(dict_folder):
        parser.error(
            f"Dictionary files for '{canonical_lang}' not found at {dict_folder}. "
            "Ensure the dictionaries submodule is initialized."
        )

    word_length = args.length
    if word_length < 1 or word_length > _MAX_WORD_LENGTH:
        parser.error(f"Word length must be between 1 and {_MAX_WORD_LENGTH}.")
    solutions_filename = f"{lang_normalized}{word_length}.txt"
    solutions_path_candidate = os.path.join("solutions", solutions_filename)
    solutions_path = _resource_path(solutions_path_candidate)

    # Look for solutions file in solutions/ folder: solutions/<lang><length>.txt
    lang_for_runtime = lang_normalized
    if os.path.isfile(solutions_path):
        logger.info(
            "Using solutions file '%s' for language '%s'.",
            os.path.relpath(solutions_path, start=os.path.dirname(__file__)),
            canonical_lang,
        )
    else:
        logger.info(
            "No solutions file '%s' for language '%s'; will rely on dictionary data.",
            solutions_path_candidate,
            canonical_lang,
        )

    try:
        play_gui(
            word_length,
            solutions_path,
            dict_folder,
            lang_for_runtime,
            args.difficulty,
            use_solution_filters=not args.disable_solution_filters,
            hide_secret=args.hide_secret,
        )
    except (OSError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
