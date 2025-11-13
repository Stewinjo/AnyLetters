"""AnyLetters – a variable-length word game with dictionary validation.

This module implements AnyLetters, a Wordle-style game that supports a variable
word length, configurable solutions and validates guesses using `.dic` and `.aff`.

Author: stewinjo
"""

__version__ = "1.0.0"

import argparse
import logging
import os
import random
import re
import sys
import tkinter as tk
from collections import Counter
from collections.abc import Iterator
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
    apply_language_filters,
    clear_filtered_solution_cache,
    load_filter_config,
    load_filtered_solution_cache,
    save_filtered_solution_cache,
)

USED_SOLUTIONS: set[str] = set()

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
        raise FileNotFoundError(
            f"Dictionary directory '{directory}' does not exist."
        )

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
) -> tuple["AffRules", list[tuple[str, str]]]:
    """Load affix rules and dictionary entries from matching pairs."""

    combined_rules = AffRules()
    all_entries: list[tuple[str, str]] = []

    for aff_path, dic_path in dict_pairs:
        rules = parse_aff_rules(aff_path)
        for flag, rule_list in rules.sfx.items():
            combined_rules.sfx.setdefault(flag, []).extend(rule_list)
        for flag, rule_list in rules.pfx.items():
            combined_rules.pfx.setdefault(flag, []).extend(rule_list)

        entries = parse_dic_entries(dic_path)
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
            f"No solutions of length {word_length} found in solutions.txt"
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
        w for w in candidates
        if len(w) == word_length and w not in USED_SOLUTIONS
    )
    if not remaining:
        return None
    return random.choice(remaining)

def parse_dic_entries(dic_path: str) -> list[tuple[str, str]]:
    """Parse .dic entries into (base_word_norm_lower, flags_str).

    Args:
        dic_path: Path to the .dic file.

    Returns:
        List of (normalized_word, flags) tuples.

    Raises:
        UnicodeDecodeError: If file is not valid UTF-8.
        OSError: If file cannot be read.
    """
    entries: list[tuple[str, str]] = []
    with open(dic_path, "r", encoding="utf-8") as f:
        first = True
        for line in f:
            if not (stripped := line.strip()):
                continue
            if first:
                first = False
                if stripped.isdigit():
                    continue
            # entry like: Wort/FLAGS or just Wort
            base, flags = stripped.split("/", 1) if "/" in stripped else (stripped, "")
            base_norm = _normalize_word(base)
            entries.append((base_norm, flags))
    return entries

class AffRules:
    """Container for affix rules parsed from .aff files.

    Stores suffix (SFX) and prefix (PFX) rules keyed by flag characters.
    """

    def __init__(self) -> None:
        """Initialize empty suffix and prefix rule dictionaries."""
        self.sfx: dict[str, list[tuple[str, str, str]]] = {}
        self.pfx: dict[str, list[tuple[str, str, str]]] = {}

    def add_rule(
        self, is_suffix: bool, flag: str, strip: str, add: str, cond: str
    ) -> None:
        """Add an affix rule.

        Args:
            is_suffix: True for suffix (SFX), False for prefix (PFX).
            flag: Flag character identifying this rule group.
            strip: Characters to remove from base word.
            add: Characters to add after stripping.
            cond: Condition pattern for matching.
        """
        store = self.sfx if is_suffix else self.pfx
        lst = store.setdefault(flag, [])
        lst.append((strip, add, cond))

def parse_aff_rules(aff_path: str) -> AffRules:
    """Parse minimal SFX/PFX rules from .aff to enable basic inflections.

    Supports: header lines and per-rule lines: SFX|PFX FLAG [Y|N] COUNT and
    SFX|PFX FLAG strip add condition. Condition is treated as a simple regex
    fragment; '.' means any, [...] kept.

    Args:
        aff_path: Path to the .aff file.

    Returns:
        AffRules object.

    Raises:
        UnicodeDecodeError: If file is not valid UTF-8.
        OSError: If file cannot be read.
    """
    rules = AffRules()

    if not os.path.isfile(aff_path):
        return rules

    with open(aff_path, "r", encoding="utf-8") as f:
        for line in f:
            if not (stripped := line.strip()) or stripped.startswith("#"):
                continue
            if len(parts := stripped.split()) < 4:
                continue
            type_tag = parts[0]
            if type_tag not in ("SFX", "PFX"):
                continue
            # header lines look like: SFX A Y 2  (we ignore)
            # rule lines look like:   SFX A 0 en .
            if len(parts) >= 5 and parts[2] != "Y" and parts[2] != "N":
                flag = parts[1]
                strip = parts[2] if parts[2] != "0" else ""
                add = parts[3] if parts[3] != "0" else ""
                cond = parts[4] if len(parts) >= 5 else "."
                # keep cond as-is (used as simple regex later)
                rules.add_rule(type_tag == "SFX", flag, strip, add, cond)
    return rules

def _generate_affixed_candidates(
    base: str,
    flags: str,
    rules: AffRules,
    word_length: int,
    letters_re: re.Pattern[str],
    blocked_suffix_additions: set[str] | None = None,
) -> Iterator[str]:
    """Generate affixed candidates from a base word and flags.

    Args:
        base: Base word to generate candidates from.
        flags: Flags string indicating applicable affix rules.
        rules: AffRules object containing affix rules.
        word_length: Target word length.
        letters_re: Compiled regex pattern for valid letters.

    Yields:
        Generated candidate words matching target length and pattern.
    """
    # suffixes
    for flag in flags:
        for strip, add, cond in rules.sfx.get(flag, []):
            if blocked_suffix_additions and add and add.lower() in blocked_suffix_additions:
                continue
            stem = base
            if strip and base.endswith(strip):
                stem = base[: -len(strip)]
            elif strip:
                continue
            candidate = stem + add
            # condition: basic match on stem end
            try:
                if cond and not re.search(cond + r"$", stem):
                    continue
            except re.error:
                pass
            if len(candidate) == word_length and letters_re.match(candidate):
                yield candidate
        # prefixes
        for strip, add, cond in rules.pfx.get(flag, []):
            stem = base
            if strip and base.startswith(strip):
                stem = base[len(strip) :]
            elif strip:
                continue
            candidate = add + stem
            try:
                if cond and not re.match(r"^" + cond, stem):
                    continue
            except re.error:
                pass
            if len(candidate) == word_length and letters_re.match(candidate):
                yield candidate

def expand_with_affixes(
    entries: list[tuple[str, str]],
    rules: AffRules,
    word_length: int,
    *,
    blocked_suffix_additions: set[str] | None = None,
) -> set[str]:
    """Generate words by applying simple PFX/SFX rules to base forms.

    We apply single prefix OR single suffix (no combinations) to control size.
    Only words of the target length are kept.

    Args:
        entries: List of (base_word, flags) tuples.
        rules: AffRules object containing affix rules.
        word_length: Target word length.
        blocked_suffix_additions: Optional set of lowercase suffix strings to skip.

    Returns:
        Set of generated words matching target length.
    """
    letters_re = re.compile(r"^[a-zäöüß]+$")
    result: set[str] = set()

    for base, flags in entries:
        if len(base) == word_length and letters_re.match(base):
            result.add(base)
        result.update(
            _generate_affixed_candidates(
                base,
                flags,
                rules,
                word_length,
                letters_re,
                blocked_suffix_additions,
            )
        )

    return result


def _prune_blocked_suffix_bases(
    words: set[str],
    blocked_suffixes: set[str],
    catalog: set[str],
) -> None:
    """Remove words that appear to be base-plus-blocked-suffix variants."""

    if not blocked_suffixes or not words:
        return

    normalized_catalog = {entry.lower() for entry in catalog}
    removals: set[str] = set()
    for word in words:
        lower_word = word.lower()
        for suffix in blocked_suffixes:
            if not suffix:
                continue
            if not lower_word.endswith(suffix):
                continue
            stem = lower_word[: -len(suffix)]
            if stem and stem in normalized_catalog:
                removals.add(word)
                break
    words.difference_update(removals)


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
    lang: str,
) -> DictionaryWordData:
    """Collect dictionary candidates by combining all available aff/dic pairs."""

    dict_pairs = _find_matching_dict_pairs(dict_folder)

    combined_rules, all_entries = _load_dictionary_components(dict_pairs, logger)
    if not all_entries:
        raise ValueError(
            f"Dictionary files in '{dict_folder}' do not contain any entries."
        )

    base_words = {base for base, _ in all_entries if len(base) == word_length}
    blocked_suffixes: set[str] = set()
    normalized_lang = (lang or "").strip().lower()
    if normalized_lang:
        archetype = normalized_lang.split("-", 1)[0]
        if archetype:
            blocked_suffixes.update(
                suffix.lower()
                for suffix in load_filter_config(archetype).suffixes
                if suffix
            )
    blocked_suffixes.update(
        suffix.lower() for suffix in load_filter_config("global").suffixes if suffix
    )
    affixed_words = expand_with_affixes(
        all_entries,
        combined_rules,
        word_length,
        blocked_suffix_additions=blocked_suffixes or None,
    )
    source_catalog = {base for base, _ in all_entries}
    _prune_blocked_suffix_bases(base_words, blocked_suffixes, source_catalog)
    _prune_blocked_suffix_bases(affixed_words, blocked_suffixes, source_catalog)
    catalog = {base for base, _ in all_entries}

    return DictionaryWordData(base_words=base_words, affixed_words=affixed_words, catalog=catalog)

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
        os.path.join(cache_dir, f"{lang}_{word_length}_utf-8.txt")
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


def _load_or_build_filtered_solutions(
    lang: str,
    word_length: int,
    dict_folder: str,
    logger: logging.Logger,
    *,
    enable_filters: bool = True,
) -> list[str]:
    """Load or generate a (optionally) filtered solution cache for the language."""

    cached: list[str] = []
    if enable_filters:
        cached = load_filtered_solution_cache(lang, word_length)
        if cached:
            logger.info(
                "Loaded filtered solution cache for %s/%s (%d words)",
                lang,
                word_length,
                len(cached),
            )
            return cached

    data = _collect_dictionary_word_data(dict_folder, word_length, logger, lang)

    generated_words = sorted(data.combined)
    if not generated_words:
        raise ValueError(
            f"Dictionary candidate list empty for language '{lang}' and length {word_length}."
        )

    if not enable_filters:
        logger.info(
            "Generated %d dictionary candidates for %s/%s without language filters.",
            len(generated_words),
            lang,
            word_length,
        )
        return generated_words

    filtered = apply_language_filters(
        lang,
        generated_words,
        data.catalog,
        enable_filters=enable_filters,
    )
    if not filtered:
        logger.warning(
            "Filtered solution list empty for %s/%s; falling back to unfiltered dictionary words.",
            lang,
            word_length,
        )
        filtered = generated_words

    save_filtered_solution_cache(lang, word_length, filtered)
    logger.info(
        "Built filtered solution cache for %s/%s (%d words)",
        lang,
        word_length,
        len(filtered),
    )
    return filtered


def _looks_plural_en(word: str, catalog: set[str]) -> bool:
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
    """Heuristic to detect English past tense (-ed) forms via dictionary lookup."""

    w = word.lower()
    if len(w) <= 3:
        return False
    if w.endswith("ied") and len(w) > 3:
        stem = w[:-3] + "y"
        if stem in catalog:
            return True
    if w.endswith("ed") and len(w) > 3:
        stem = w[:-2]
        if stem in catalog:
            return True
    if w.endswith("t") and len(w) > 3:
        stem = w[:-1]
        if stem in catalog and stem + "e" in catalog:
            return True
    return False


def _looks_plural_de(word: str, catalog: set[str]) -> bool:
    """Heuristic to detect German plural nouns using dictionary presence."""

    w = word.lower()
    if len(w) <= 3:
        return False
    if w.endswith("innen") and len(w) > 5:
        stem = w[:-5] + "in"
        if stem in catalog:
            return True
    if w.endswith("er") and len(w) > 3:
        stem = w[:-2]
        if stem in catalog:
            return True
    if w.endswith("en") and len(w) > 3 and not w.endswith(("chen", "lein")):
        stem = w[:-2]
        if stem in catalog:
            return True
    if w.endswith("e") and len(w) > 3:
        stem = w[:-1]
        if stem in catalog:
            return True
    if w.endswith("s") and len(w) > 3:
        stem = w[:-1]
        if stem in catalog:
            return True
    return False


def _looks_past_tense_de(word: str, catalog: set[str]) -> bool:
    """Heuristic to detect German past tense (Präteritum/Partizip II) forms."""

    w = word.lower()
    if len(w) <= 3:
        return False
    if w.startswith("ge") and len(w) > 4:
        if w.endswith("t"):
            stem = w[2:-1]
            if (stem + "en") in catalog:
                return True
        if w.endswith("en"):
            stem = w[2:]
            if stem in catalog:
                return True
    endings = ("te", "test", "tet", "ten")
    for ending in endings:
        if w.endswith(ending) and len(w) > len(ending) + 1:
            stem = w[: -len(ending)]
            if stem + "en" in catalog:
                return True
    return False


def _should_exclude_inflected(word: str, lang: str, catalog: set[str]) -> bool:
    """Return True if word appears to be an inflected form to skip on medium mode."""

    if not catalog:
        return False
    if lang.startswith("en"):
        return _looks_plural_en(word, catalog) or _looks_past_tense_en(word, catalog)
    if lang.startswith("de"):
        return _looks_plural_de(word, catalog) or _looks_past_tense_de(word, catalog)
    return False



def build_validator(
    dict_folder: str, solutions: list[str], lang: str, word_length: int
):
    """Create a callable that validates whether a guess is a real word.

    Generates/loads a per-(lang,length) cache to avoid recomputation.
    Combines all matching .aff/.dic pairs in the directory.

    Args:
        dict_folder: Directory containing .dic and .aff files.
        solutions: List of valid solution words.
        lang: Language code (e.g., 'de').
        word_length: Target word length.

    Returns:
        Callable function that takes a word string and returns bool.
    """
    logger = logging.getLogger("anyletters")

    logger.info("Using dictionary folder: %s", dict_folder)

    # Initialize allowed words from solutions
    allowed_len = {_normalize_word(w) for w in solutions if len(w) == word_length}
    backend_name = "solutions-only"

    # Try to load cache
    cached_words = load_cache(lang, word_length)
    if cached_words:
        allowed_len = cached_words
        backend_name = "cache-only"
        logger.info(
            "Loaded cache for %s/%s: %d words",
            lang, word_length, len(cached_words)
        )
    else:
        # No cache found - need to process dictionaries
        data = _collect_dictionary_word_data(dict_folder, word_length, logger, lang)

        allowed_len = data.combined
        # Persist cache
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

    # Include solutions (normalized) regardless of cache or dictionary entries
    allowed_len |= {
        _normalize_word(w) for w in solutions if len(w) == word_length
    }

    def is_valid(word: str) -> bool:
        """Check if word is valid according to dictionary and solutions.

        Args:
            word: Word to validate.

        Returns:
            True if word is valid, False otherwise.
        """
        wn = _normalize_word(word)
        if wn in allowed_len:
            return True
        if (lang or "").lower() == "de":
            alt = _transliterate_german(wn)
            if alt in allowed_len:
                logger.info(
                    "Accepted via transliteration: '%s' -> '%s'", word, alt
                )
                return True
        logger.info("Dictionary rejected: %s", word)
        return False

    setattr(is_valid, "backend", backend_name)
    # Always set allowed_words so caller can use dictionary words when solutions are missing
    setattr(is_valid, "allowed_words", allowed_len)
    return is_valid

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
    """
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
    """Map input character to keyboard label key respecting language.

    Args:
        ch: Input character.
        lang: Language code.

    Returns:
        Mapped character for keyboard lookup.
    """
    if _is_german_lang(lang):
        if ch in ("ä", "ö", "ü"):
            return ch.upper()
        if ch in ("Ä", "Ö", "Ü"):
            return ch
        if ch == "ß":
            return "ß"
    # Default Latin A-Z
    if "a" <= ch <= "z":
        return ch.upper()
    return ch.upper()

def play_gui(
    word_length: int,
    solutions_path: str,
    dict_folder: str,
    lang: str,
    difficulty: str,
    use_solution_filters: bool = True,
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
    """
    logger = logging.getLogger("anyletters")
    solutions_file_found = os.path.isfile(solutions_path)
    all_solutions = read_solutions_file(solutions_path)

    # Build validator first to get dictionary words if needed
    validator = build_validator(dict_folder, all_solutions, lang, word_length)
    backend = getattr(validator, "backend", "Unknown")
    difficulty = difficulty.lower()
    logger.info("Difficulty selected: %s", difficulty)
    logger.info(
        "Solution filters %s",
        "enabled" if use_solution_filters else "disabled",
    )

    # Get allowed words from validator (includes cache/dictionary words)
    allowed_words = getattr(validator, "allowed_words", set())

    # If no solutions file or no solutions of required length, use dictionary words
    solutions_by_len = _filter_solutions_by_length(all_solutions, word_length)
    if not solutions_file_found and difficulty != "chaos":
        filtered_solutions = _load_or_build_filtered_solutions(
            lang,
            word_length,
            dict_folder,
            logger,
            enable_filters=use_solution_filters,
        )
        if filtered_solutions:
            all_solutions = list(filtered_solutions)
            solutions_by_len = filtered_solutions

    if not solutions_by_len:
        dictionary_candidates: list[str] = []
        allowed_list: list[str] = []
        if allowed_words:
            # Convert set to list for compatibility
            allowed_list = sorted(list(allowed_words))
            dictionary_candidates = _filter_solutions_by_length(allowed_list, word_length)
        if dictionary_candidates:
            if solutions_file_found:
                logger.warning(
                    "Solutions file '%s' contains no words of length %d will use %d dictionary words instead.",
                    solutions_path,
                    word_length,
                    len(dictionary_candidates),
                )
            else:
                logger.warning(
                    "No solutions file found. Tried: %s will use %d dictionary words instead.",
                    solutions_path,
                    len(dictionary_candidates),
                )
            all_solutions = allowed_list if allowed_list else dictionary_candidates
            solutions_by_len = dictionary_candidates
        else:
            raise ValueError(
                f"No solutions of length {word_length} found and "
                f"no dictionary words available for language '{lang}' with length {word_length}."
            )

    # Pick an unused secret if possible, otherwise any
    chosen = pick_unused_solution(all_solutions, word_length)
    secret = chosen if chosen is not None else pick_random_solution(all_solutions, word_length)
    secret_norm = _normalize_word(secret)
    secret_counts = Counter(secret_norm)

    logger.info(
        "Secret '%s' selected (length %d). Validator backend: %s",
        secret_norm,
        word_length,
        backend,
    )

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
            return (
                COLORS.alternate_correct if is_colorblind() else COLORS.correct
            )
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
    # Add language-specific extra letters to the keyboard
    extra_letters: list[str] = []
    if _is_german_lang(lang):
        extra_letters = ["Ä", "Ö", "Ü", "ß"]
    rows = [letters[:13], letters[13:]]
    if extra_letters:
        rows.append(extra_letters)
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

    def apply_layout(layout: Layout) -> None:
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
            cell = _create_cell_label(cells, ch.upper(), bg, font_cell)
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
                letter_count_labels[ch].configure(
                    text="", bg=COLORS.light_gray
                )

    def reset_board_for_new_secret(new_secret: str) -> None:
        """Reset the game board for a new secret word.

        Args:
            new_secret: New secret word to use.
        """
        nonlocal secret, secret_norm, secret_counts, game_over, restart_row, restart_button
        secret = new_secret
        secret_norm = _normalize_word(secret)
        secret_counts = Counter(secret_norm)
        logger.info(
            "New secret '%s' selected.",
            secret_norm
        )
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

    def submit_guess_from_cells() -> None:
        """Process and submit the current guess from input cells."""
        nonlocal game_over
        if game_over:
            return
        guess = "".join(input_chars)
        guess_norm = _normalize_word(guess)
        if len(guess) != word_length:
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

    def update_keyboard(guess_text: str, markers: list[str]) -> None:
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
                elif total <= 1 and key_char in multiletter_shown and count_label is not None:
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
        # Accept letters (including German umlauts and ß)
        allowed = "abcdefghijklmnopqrstuvwxyzäöüß"
        lower = ch.lower()
        if lower not in allowed:
            return
        if len(input_chars) >= word_length:
            return
        display = lower.upper()
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

def main() -> None:
    """Parse arguments for language and length, then start the GUI game."""
    # Configure logging (console)
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(
        description="AnyLetters GUI (no fail state)"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="en",
        help="Language code for dictionaries (e.g., de)",
    )
    parser.add_argument(
        "--length", type=int, default=6, help="Word length to play with"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available dictionaries and exit",
    )
    parser.add_argument(
        "-d",
        "--diffiuclty",
        dest="difficulty",
        type=str.lower,
        choices=["easy", "medium", "hard", "chaos"],
        default="medium",
        help="Select difficulty: easy, medium, hard, or chaos (default: medium).",
    )
    parser.add_argument(
        "--disable-solution-filters",
        action="store_true",
        help="Skip language-based filtering when generating dictionary fallback solutions.",
    )
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
        )
    except (OSError, ValueError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
