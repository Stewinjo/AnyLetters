"""Language-specific filters and solution-cache helpers for AnyLetters."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from collections.abc import Iterable

try:
    from better_profanity import profanity as _profanity
except ImportError:  # pragma: no cover - optional dependency
    _profanity = None
else:
    _profanity.load_censor_words()

__all__ = [
    "apply_language_filters",
    "clear_filtered_solution_cache",
    "filter_candidates",
    "load_filtered_solution_cache",
    "save_filtered_solution_cache",
    "solution_cache_path",
]


@dataclass(slots=True)
class FilterConfig:
    """Configuration describing blacklist and affix filters for a language."""

    prefixes: tuple[str, ...] = field(default_factory=tuple)
    suffixes: tuple[str, ...] = field(default_factory=tuple)
    blacklist: tuple[str, ...] = field(default_factory=tuple)
    blacklist_files: tuple[str, ...] = field(default_factory=tuple)


def _config_root() -> str:
    """Return the directory containing language filter JSON files."""

    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "filters")


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

    @property
    def config(self) -> FilterConfig:
        """Return the loaded filter configuration."""

        return self._config

    def apply(self, words: Iterable[str], _catalog: set[str]) -> list[str]:
        """Apply configured blacklist, affix exclusions, and profanity checks."""

        processed: list[str] = []
        seen: set[str] = set()
        for word in words:
            lower = word.lower()
            if not lower.isalpha():
                continue
            if _contains_profanity(word):
                continue
            if lower in self.config.blacklist:
                continue
            if self._matches_prefix(lower) or self._matches_suffix(lower):
                continue
            if lower in seen:
                continue
            processed.append(word)
            seen.add(lower)
        return sorted(processed)

    def _matches_prefix(self, word_lower: str) -> bool:
        """Return True if the word begins with a disallowed prefix."""

        return any(word_lower.startswith(prefix) for prefix in self.config.prefixes)

    def _matches_suffix(self, word_lower: str) -> bool:
        """Return True if the word ends with a disallowed suffix."""

        return any(word_lower.endswith(suffix) for suffix in self.config.suffixes)


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


def solution_cache_path(lang: str, word_length: int) -> str:
    """Return the cache path for a filtered solution list."""

    directory = _ensure_solution_cache_dir()
    filename = f"{lang}_{word_length}.txt"
    return os.path.normpath(os.path.join(directory, filename))


def load_filtered_solution_cache(lang: str, word_length: int) -> list[str]:
    """Load previously generated filtered solutions for a language/length pair."""

    path = solution_cache_path(lang, word_length)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        return [line for line in (line.strip() for line in handle) if line]


def save_filtered_solution_cache(
    lang: str, word_length: int, words: Iterable[str]
) -> None:
    """Persist filtered solutions to disk for future runs."""

    path = solution_cache_path(lang, word_length)
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
