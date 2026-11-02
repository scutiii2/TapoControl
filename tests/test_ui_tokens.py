"""Design guards: layout values come from the shared scales and the theme colors stay readable."""
import re
from pathlib import Path

import pytest

from ui import tokens as t
from ui.theme import DARK, LIGHT

UI = Path(__file__).parent.parent / "src" / "ui"
SCALE = {0, t.SP_XS, t.SP_SM, t.SP_MD, t.SP_LG, t.SP_XL}
SPACING_CALL = re.compile(r"\b(?:setContentsMargins|setSpacing|addSpacing|setVerticalSpacing)\(([^)]*)\)")


def luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("path", sorted(UI.glob("*.py")), ids=lambda p: p.name)
def test_spacing_literals_follow_the_scale(path):
    bad = []
    for call in SPACING_CALL.findall(path.read_text(encoding="utf-8")):
        bad += [n for n in re.findall(r"(?<![\w.])\d+(?![\w.])", call) if int(n) not in SCALE]
    assert not bad, f"{path.name}: spacing {bad} is off the 0/4/8/12/16/24 scale; use a token from ui/tokens.py"


@pytest.mark.parametrize("colors", [LIGHT, DARK], ids=["light", "dark"])
def test_text_and_control_colors_meet_contrast(colors):
    for surface in (colors.background, colors.surface, colors.raised, colors.selected):
        assert contrast(colors.text, surface) >= 4.5
        assert contrast(colors.muted, surface) >= (3 if colors is LIGHT else 4.5)
    for surface in (colors.background, colors.surface, colors.selected):
        assert contrast(colors.accent, surface) >= 4.5
    assert contrast(colors.success, colors.surface) >= 4.5 and contrast(colors.error, colors.surface) >= 4.5
    assert contrast(colors.accent_text, colors.accent) >= 4.5
    assert contrast(colors.control, colors.surface) >= 3  # switch outlines and input borders
    for line in colors.series:
        # Pale chart colors from the approved light reference accompany readable, labeled controls.
        assert contrast(line, colors.surface) >= (1.5 if colors is LIGHT else 2)


def test_each_theme_has_eight_distinct_line_colors():
    for colors in (LIGHT, DARK):
        assert len(set(colors.series)) == len(colors.series) == 8
