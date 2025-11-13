"""Centralized styling constants and helpers for AnyLetters' UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable

import tkinter as tk
from tkinter import font as tkfont

_REGISTERED_FONTS: set[Path] = set()


@dataclass(frozen=True)
class Colors:
    """Color palette used across the AnyLetters UI."""

    background: str = "#121212"
    cell_background: str = "#3a3a3c"
    correct: str = "#117733"
    present: str = "#E66100"
    alternate_correct: str = "#5D3A9B"
    light_gray: str = "#9aa0a6"
    dark_gray: str = "#3a3a3c"
    primary_text: str = "#ffffff"
    status_text: str = "#ffa500"
    footer_text: str = "#666666"
    footer_button_bg: str = "#2b2b2b"
    footer_button_active_bg: str = "#3a3a3c"


@dataclass(frozen=True)
class Layout:
    """Layout and spacing guidelines for AnyLetters widgets."""

    outer_padding: int = 8
    status_padding_bottom: int = 6
    keyboard_padding_bottom: int = 8
    guess_row_padx: int = 4
    guess_row_pady: int = 2
    cell_padx: int = 2
    key_padx: int = 2
    key_pady: int = 1
    count_label_offset_x: int = 2
    count_label_offset_y: int = 0
    footer_version_padx: int = 8
    footer_version_pady: int = 8
    colorblind_internal_padx: int = 8
    colorblind_internal_pady: int = 2
    colorblind_pack_padx: int = 8
    colorblind_pack_pady: int = 8
    restart_button_internal_padx: int = 6
    restart_button_internal_pady: int = 2


COLORS = Colors()

CELL_LABEL_WIDTH = 2
CELL_LABEL_HEIGHT = 1
BUTTON_BORDER_WIDTH = 1

ASSETS_DIR = Path("assets") / "Open_sans"
FONT_REGULAR = ASSETS_DIR / "static" / "OpenSans-Regular.ttf"
FONT_BOLD = ASSETS_DIR / "static" / "OpenSans-Bold.ttf"
FONT_SEMIBOLD = ASSETS_DIR / "static" / "OpenSans-SemiBold.ttf"

BODY_FONT_SIZE = 12
CELL_FONT_SIZE = 12
COUNT_FONT_SIZE = 8
FOOTER_FONT_SIZE = 8


@dataclass(frozen=True)
class Fonts:
    """Container for Tk font instances used throughout the UI."""

    body: tkfont.Font
    cell: tkfont.Font
    count: tkfont.Font
    footer: tkfont.Font


def _register_font_file(path: Path) -> None:
    """Register a font file with the operating system so Tk can use it."""

    if path in _REGISTERED_FONTS or not path.is_file():
        return

    if sys.platform == "win32":
        try:
            from ctypes import windll

            FR_PRIVATE = 0x10
            added = windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0)
            if added:
                _REGISTERED_FONTS.add(path)
                # Notify system font list changed (best effort).
                windll.user32.SendMessageTimeoutW(
                    0xFFFF, 0x001D, 0, 0, 0, 100, 0
                )
                return
        except OSError:
            pass

    # For non-Windows or failed registration, fall back to letting Tk resolve it.
    _REGISTERED_FONTS.add(path)


def _font_from_file(
    root: tk.Misc, path: Path, fallback_family: str, size: int
) -> tkfont.Font:
    """Return a Tk font ensuring the font file is registered if possible."""

    if path and path.is_file():
        _register_font_file(path)
    try:
        return tkfont.Font(root=root, family=fallback_family, size=size)
    except tk.TclError:
        return tkfont.Font(root=root, size=size)


def load_fonts(root: tk.Misc, resolver: Callable[[str], str]) -> Fonts:
    """Create and return all fonts used by the UI.

    Args:
        root: Root Tk widget used for font registration.
        resolver: Callable that turns a relative project path into an absolute path.

    Returns:
        Fonts dataclass containing Tk font instances.
    """

    fallback_family = "Open Sans"
    regular_path = Path(resolver(str(FONT_REGULAR)))
    bold_path = Path(resolver(str(FONT_BOLD)))
    semibold_path = Path(resolver(str(FONT_SEMIBOLD)))

    body_font = _font_from_file(root, regular_path, fallback_family, BODY_FONT_SIZE)
    cell_font = _font_from_file(root, bold_path, fallback_family, CELL_FONT_SIZE)
    cell_font.configure(weight="bold")
    count_font = _font_from_file(root, semibold_path, fallback_family, COUNT_FONT_SIZE)
    count_font.configure(weight="bold")
    footer_font = _font_from_file(root, regular_path, fallback_family, FOOTER_FONT_SIZE)

    return Fonts(
        body=body_font,
        cell=cell_font,
        count=count_font,
        footer=footer_font,
    )


def compute_layout(cell_font: tkfont.Font) -> Layout:
    """Return a Layout scaled proportionally to the current cell font size."""

    base_size = CELL_FONT_SIZE or 12
    current_size = abs(int(cell_font.cget("size") or base_size))
    scale = max(0.5, current_size / base_size)

    def scaled(value: int, minimum: int = 0) -> int:
        return max(minimum, int(round(value * scale)))

    return Layout(
        outer_padding=scaled(8, 2),
        status_padding_bottom=scaled(6, 2),
        keyboard_padding_bottom=scaled(8, 2),
        guess_row_padx=scaled(4, 1),
        guess_row_pady=scaled(2, 1),
        cell_padx=scaled(2, 1),
        key_padx=scaled(2, 1),
        key_pady=scaled(1, 0),
        count_label_offset_x=scaled(2, 0),
        count_label_offset_y=scaled(0, 0),
        footer_version_padx=scaled(8, 2),
        footer_version_pady=scaled(8, 2),
        colorblind_internal_padx=scaled(8, 2),
        colorblind_internal_pady=scaled(2, 1),
        colorblind_pack_padx=scaled(8, 2),
        colorblind_pack_pady=scaled(8, 2),
        restart_button_internal_padx=scaled(6, 2),
        restart_button_internal_pady=scaled(2, 1),
    )
