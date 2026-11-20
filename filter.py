"""Language-specific filters and solution-cache helpers for AnyLetters."""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from collections.abc import Iterable

try:
    from better_profanity import profanity as _profanity
except (ImportError, OSError):  # pragma: no cover - optional dependency
    _profanity = None
else:
    try:
        _profanity.load_censor_words()
    except (OSError, ValueError):  # pragma: no cover - broken install
        _profanity = None

__all__ = [
    "CACHE_VERSION",
    "apply_language_filters",
    "clear_filtered_solution_cache",
    "filter_candidates",
    "load_filtered_solution_cache",
    "save_filtered_solution_cache",
    "solution_cache_path",
]

# Bump when dictionary parsing or solution filtering changes so old files
# are left unread instead of being treated as current.
CACHE_VERSION = "3"


@dataclass(slots=True)
class FilterConfig:
    """Configuration describing blacklist entries for a language.

    Prefix and suffix lists are still loaded so existing JSON files stay valid.
    They are not applied as raw ``startswith`` / ``endswith`` checks, because
    that also removed ordinary words such as ``chaos``, ``forest``, and
    ``sacred``. Inflection handling lives in the difficulty selector.
    """

    prefixes: tuple[str, ...] = field(default_factory=tuple)
    suffixes: tuple[str, ...] = field(default_factory=tuple)
    blacklist: tuple[str, ...] = field(default_factory=tuple)
    blacklist_files: tuple[str, ...] = field(default_factory=tuple)


def _config_root() -> str:
    """Return the directory containing language filter JSON files.

    Frozen builds look in the PyInstaller resource directory. Running from
    source uses the ``filters`` directory next to this module.
    """

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        bundled = os.path.join(bundle_root, "filters")
        if os.path.isdir(bundled):
            return bundled
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "filters")


def fold_blacklist_key(word: str) -> str:
    """Return a blacklist key that treats German transliterations as equal.

    ``ä``/``ö``/``ü``/``ß`` fold to ``ae``/``oe``/``ue``/``ss``, so a list
    entry such as ``aegypten`` matches the dictionary word ``Ägypten``.

    Args:
        word: Word or blacklist entry to fold.

    Returns:
        Case-folded, transliteration-folded key.
    """

    folded = unicodedata.normalize("NFC", word).casefold()
    return (
        folded.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _config_path(archetype: str) -> str:
    """Return the path to the JSON config for a given archetype."""

    return os.path.join(_config_root(), f"{archetype}.json")


@lru_cache(maxsize=None)
def load_filter_config(archetype: str) -> FilterConfig:
    """Load and cache filter configuration for a language archetype."""

    path = _config_path(archetype)
    if not os.path.isfile(path):
        return FilterConfig()
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    prefixes = tuple(p.lower() for p in data.get("prefixes", []) if p)
    suffixes = tuple(s.lower() for s in data.get("suffixes", []) if s)
    blacklist_entries = [w.lower() for w in data.get("blacklist", []) if w]
    extra_files = tuple(f for f in data.get("blacklist_files", []) if f)
    for filename in extra_files:
        file_path = os.path.join(_config_root(), filename)
        if not os.path.isfile(file_path):
            continue
        with open(file_path, "r", encoding="utf-8") as list_handle:
            for line in list_handle:
                candidate = line.strip().lower()
                if candidate:
                    blacklist_entries.append(candidate)
    blacklist = tuple(dict.fromkeys(blacklist_entries))
    return FilterConfig(
        prefixes=prefixes,
        suffixes=suffixes,
        blacklist=blacklist,
        blacklist_files=extra_files,
    )


def _contains_profanity(text: str) -> bool:
    """Return True when better_profanity flags the supplied text."""

    if _profanity is None:
        return False
    return bool(_profanity.contains_profanity(text))


class LanguageFilter:
    """Base implementation shared by all language filters."""

    def __init__(self, archetype: str) -> None:
        """Initialize filter with JSON-backed configuration."""

        self.archetype = archetype
        self._config = load_filter_config(archetype)
        self._blacklist_keys = {
            fold_blacklist_key(word) for word in self._config.blacklist
        }

    @property
    def config(self) -> FilterConfig:
        """Return the loaded filter configuration."""

        return self._config

    def apply(self, words: Iterable[str], _catalog: set[str]) -> list[str]:
        """Apply the blacklist and profanity checks.

        Args:
            words: Candidate solution words.
            _catalog: Unused. Kept so callers can pass the dictionary catalog.

        Returns:
            Sorted words that are alphabetic, not profane, and not blacklisted.
        """

        processed: list[str] = []
        seen: set[str] = set()
        for word in words:
            lower = word.lower()
            if not lower.isalpha():
                continue
            if _contains_profanity(word):
                continue
            if fold_blacklist_key(lower) in self._blacklist_keys:
                continue
            if lower in seen:
                continue
            processed.append(word)
            seen.add(lower)
        return sorted(processed)


def filter_candidates(
    words: Iterable[str],
    lang: str,
    catalog: set[str],
    *,
    enable_filters: bool = True,
) -> list[str]:
    """Filter candidates according to the language archetype configuration."""

    if not enable_filters:
        return sorted(dict.fromkeys(words))

    filtered: list[str] = sorted(dict.fromkeys(words))

    global_filter = _get_filter_for_archetype("global")
    if filtered and global_filter is not None:
        filtered = global_filter.apply(filtered, catalog)

    archetype = _language_archetype(lang)
    if archetype is None:
        return filtered

    filter_obj = _get_filter_for_archetype(archetype)
    return filter_obj.apply(filtered, catalog)


class EnglishFilter(LanguageFilter):
    """Language filter for English using JSON-based configuration."""

    def __init__(self) -> None:
        super().__init__("en")


class GermanFilter(LanguageFilter):
    """Language filter for German using JSON-based configuration."""

    def __init__(self) -> None:
        super().__init__("de")


class GenericLanguageFilter(LanguageFilter):
    """Fallback filter that only relies on JSON configuration."""


_FILTER_CLASSES: dict[str, type[LanguageFilter]] = {
    "en": EnglishFilter,
    "de": GermanFilter,
}


@lru_cache(maxsize=None)
def _get_filter_for_archetype(archetype: str) -> LanguageFilter:
    """Return a cached language filter instance for the archetype."""

    filter_cls = _FILTER_CLASSES.get(archetype)
    if filter_cls is not None:
        return filter_cls()
    return GenericLanguageFilter(archetype)


def _language_archetype(lang: str) -> str | None:
    """Return the archetype key for a language code."""

    normalized = (lang or "").strip().lower()
    if not normalized:
        return None
    if normalized in _FILTER_CLASSES:
        return normalized
    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]
    return normalized or None


def apply_language_filters(
    lang: str,
    words: Iterable[str],
    catalog: set[str],
    *,
    enable_filters: bool = True,
) -> list[str]:
    """Apply the appropriate language-specific filter to candidate words."""

    return filter_candidates(words, lang, catalog, enable_filters=enable_filters)


def _ensure_solution_cache_dir() -> str:
    """Return the directory for language/length solution caches."""

    cache_dir = os.path.normpath(os.path.join("cache", "solutions_filtered"))
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError:
        # Directory creation failed (e.g., readonly), caller will handle writes.
        pass
    return cache_dir


def solution_cache_path(
    lang: str,
    word_length: int,
    difficulty: str = "medium",
    *,
    use_filters: bool = True,
) -> str:
    """Return the cache path for one language, length, and difficulty.

    Args:
        lang: Language code.
        word_length: Target word length.
        difficulty: Difficulty whose solution pool is cached.
        use_filters: Whether blacklist and profanity filters were applied.

    Returns:
        Path of the solution-cache file.
    """

    directory = _ensure_solution_cache_dir()
    mode = "filtered" if use_filters else "raw"
    safe_difficulty = (difficulty or "medium").strip().lower()
    filename = f"{lang}_{word_length}_{safe_difficulty}_{mode}_v{CACHE_VERSION}.txt"
    return os.path.normpath(os.path.join(directory, filename))


def load_filtered_solution_cache(
    lang: str,
    word_length: int,
    difficulty: str = "medium",
    *,
    use_filters: bool = True,
) -> list[str]:
    """Load a cached solution list for a language, length, and difficulty."""

    path = solution_cache_path(lang, word_length, difficulty, use_filters=use_filters)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [line for line in (line.strip() for line in handle) if line]


def save_filtered_solution_cache(
    lang: str,
    word_length: int,
    words: Iterable[str],
    difficulty: str = "medium",
    *,
    use_filters: bool = True,
) -> None:
    """Persist a solution list for a later run of the same difficulty."""

    path = solution_cache_path(lang, word_length, difficulty, use_filters=use_filters)
    unique_sorted = sorted(dict.fromkeys(words))
    with open(path, "w", encoding="utf-8") as handle:
        for word in unique_sorted:
            handle.write(word + "\n")


def clear_filtered_solution_cache(lang: str | None = None) -> None:
    """Delete cached filtered solution files, optionally scoped to a language.

    Args:
        lang: Optional language code; when provided, only cache files with a
            matching language prefix are removed. When omitted, all cached
            solution files are deleted.
    """

    cache_dir = _ensure_solution_cache_dir()
    if not os.path.isdir(cache_dir):
        return

    target_prefix = None
    if lang:
        target_prefix = f"{lang.strip().lower()}_"
        if not target_prefix.strip("_"):
            target_prefix = None

    for entry in os.listdir(cache_dir):
        if not entry.lower().endswith(".txt"):
            continue
        if target_prefix is not None and not entry.lower().startswith(target_prefix):
            continue
        entry_path = os.path.join(cache_dir, entry)
        try:
            os.remove(entry_path)
        except OSError:
            continue

    if target_prefix is None:
        try:
            os.rmdir(cache_dir)
        except OSError:
            pass
