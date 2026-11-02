from PySide6.QtGui import QColor

from ui.theme import energy_error, palette_for


def contrast(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        c = QColor(value)
        channels = [c.redF(), c.greenF(), c.blueF()]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    values = sorted((luminance(first), luminance(second)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def test_palettes_keep_small_text_readable():
    assert palette_for(True) != palette_for(False)
    for dark in (False, True):
        colors = palette_for(dark)
        for background in (colors.background, colors.surface, colors.selected):
            assert contrast(colors.text, background) >= 4.5
            assert contrast(colors.muted, background) >= 4.5
        assert contrast(colors.accent_text, colors.accent) >= 4.5


def test_energy_errors_explain_failure_without_exposing_raw_details():
    assert "timed out" in energy_error(TimeoutError("raw transport details"))
    assert "unreachable" in energy_error(ConnectionError("raw transport details"))
    assert "raw transport details" not in energy_error(ValueError("raw transport details"))
