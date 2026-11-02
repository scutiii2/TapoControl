"""Shared system-following colors, widget styling and application icon."""
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from ui import tokens as t


@dataclass(frozen=True)
class Colors:
    background: str
    surface: str
    raised: str
    border: str
    control: str  # 3:1 against surfaces, for switch outlines and input borders
    text: str
    muted: str
    accent: str
    accent_text: str
    selected: str
    success: str
    error: str
    series: tuple[str, ...] = ()  # one color per plug line, in order; validated on this theme's chart surface


DARK = Colors(
    "#171a21", "#20242d", "#292e39", "#465164", "#7c8aa0", "#f1f4fa", "#b3bed0",
    "#82b5ff", "#132137", "#25364e", "#7cdebb", "#ffb4b4",
    ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
)
LIGHT = Colors(
    "#f6f8f5", "#ffffff", "#eff3ec", "#e3e9e3", "#718077", "#20322c", "#718077",
    "#287351", "#ffffff", "#eaf2e9", "#287351", "#b32632",
    ("#428362", "#a4b875", "#d2b985", "#aab4a9", "#9c6686", "#367b7a", "#7964a0", "#ad6858"),
)


def palette_for(dark: bool) -> Colors:
    return DARK if dark else LIGHT


def series_color(slot: int) -> str:
    """The plug line color for a slot on the current theme."""
    series = theme().colors.series
    return series[slot % len(series)]


def energy_error(error: BaseException) -> str:
    """Keep transport details out of the main message; callers expose a tooltip."""
    if isinstance(error, TimeoutError):
        return "The plug timed out. Check its connection and reopen Energy to retry."
    if isinstance(error, ConnectionError):
        return "The plug is unreachable. Check its connection and reopen Energy to retry."
    detail = str(error).strip().splitlines()[0][:160] if str(error).strip() else type(error).__name__
    return f"Energy data is unavailable ({detail}). Reopen Energy to try again."


def action_error(error: BaseException) -> str:
    """A plain sentence for a failed action, with what to do next; callers keep the raw text for a tooltip."""
    if isinstance(error, TimeoutError):
        return "A plug did not answer in time. Check that it is on and connected, then try again."
    if isinstance(error, ConnectionError):
        return "A plug could not be reached. Check its connection, then try again."
    detail = str(error).strip().splitlines()[0][:160] if str(error).strip() else type(error).__name__
    return f"Something went wrong ({detail}). Try again."


def power_icon(color: str) -> QIcon:
    """Paint at several sizes so window and tray icons remain sharp."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 32, size / 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(QRectF(1, 1, 30, 30), 8, 8)
        foreground = "#ffffff" if QColor(color).lightness() < 128 else "#132137"
        painter.setPen(QPen(QColor(foreground), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(8, 8, 16, 17), 135 * 16, 270 * 16)
        painter.drawLine(16, 7, 16, 16)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class Theme(QObject):
    changed = Signal()

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.setObjectName("tapoTheme")
        self._app = app
        self.colors = LIGHT
        app.setStyle("Fusion")
        font = QFont(t.FONT_FAMILY)
        font.setPixelSize(t.FONT_BODY)
        app.setFont(font)
        self.apply(Qt.ColorScheme.Light)

    def apply(self, scheme: Qt.ColorScheme) -> None:
        self.colors = c = palette_for(scheme == Qt.ColorScheme.Dark)
        palette = QPalette()
        for role, color in (
            (QPalette.ColorRole.Window, c.background), (QPalette.ColorRole.WindowText, c.text),
            (QPalette.ColorRole.Base, c.surface), (QPalette.ColorRole.AlternateBase, c.raised),
            (QPalette.ColorRole.Text, c.text), (QPalette.ColorRole.Button, c.surface),
            (QPalette.ColorRole.ButtonText, c.text), (QPalette.ColorRole.Highlight, c.accent),
            (QPalette.ColorRole.HighlightedText, c.accent_text), (QPalette.ColorRole.ToolTipBase, c.raised),
            (QPalette.ColorRole.ToolTipText, c.text), (QPalette.ColorRole.PlaceholderText, c.muted),
            (QPalette.ColorRole.Link, c.accent),
        ):
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c.muted))
        self._app.setPalette(palette)
        self._app.setStyleSheet(f"""
            QMainWindow, QDialog {{ background: {c.background}; }}
            QWidget {{ color: {c.text}; font-family: '{t.FONT_FAMILY}'; font-size: {t.FONT_BODY}px; }}
            QLabel {{ background: transparent; }}
            QLabel[tone="muted"] {{ color: {c.muted}; }}
            QLabel[tone="success"] {{ color: {c.success}; }}
            QLabel[tone="error"] {{ color: {c.error}; }}
            QLabel[role="title"] {{ font-size: {t.FONT_TITLE}px; font-weight: 600; }}
            QLabel[role="heading"] {{ font-size: {t.FONT_HEADING}px; font-weight: 600; }}
            QLabel[role="metric"] {{ font-size: {t.FONT_METRIC}px; font-weight: 600; }}
            QLabel[role="caption"] {{ font-size: {t.FONT_CAPTION}px; color: {c.muted}; }}
            QLabel[role="small"] {{ font-size: {t.FONT_SMALL}px; }}
            QLabel[role="eyebrow"] {{ font-size: 10px; font-weight: 700; letter-spacing: 1.5px; color: {c.muted}; }}
            QLabel[role="brand"] {{ font-size: 19px; font-weight: 700; }}
            QLabel[role="device-value"] {{ font-size: {t.FONT_VALUE}px; font-weight: 600; }}
            QFrame#Network {{ background: {'#f5f8f3' if c is LIGHT else c.raised}; border-radius: 10px; }}
            QFrame[card="true"] {{ background: {c.surface}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_LG}px; }}
            QFrame[highlight="true"] {{ background: {'#e9f1e6' if c is LIGHT else c.selected};
                border: 1px solid {'#dce7d6' if c is LIGHT else c.border}; border-radius: 12px; }}
            QFrame#DeviceCard[selected="true"] {{ border-color: {c.border}; }}
            QFrame#DeviceCard {{ border-radius: 11px; }}
            QFrame#DeviceCard[offline="true"] QLabel {{ color: {c.muted}; }}
            QFrame#DeviceCard[offline="true"] {{ border-style: dashed; }}
            QPushButton, QToolButton {{ background: {c.surface}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_MD}px; padding: 8px 16px; min-height: 18px; }}
            QPushButton:hover, QToolButton:hover {{ background: {c.raised}; border-color: {c.accent}; }}
            QPushButton:pressed, QToolButton:pressed {{ background: {c.selected}; }}
            QPushButton:focus, QToolButton:focus {{ border: 2px solid {c.accent}; }}
            QPushButton[primary="true"] {{ background: {c.accent}; color: {c.accent_text}; font-weight: 600; }}
            QPushButton:disabled, QToolButton:disabled {{ color: {c.muted}; background: {c.raised}; }}
            QPushButton[quiet="true"], QToolButton[quiet="true"] {{ background: transparent; border: none;
                padding: 0; font-size: 10px; color: {c.muted}; }}
            QPushButton[compact="true"] {{ font-size: 10px; padding: 6px 12px; min-height: 16px; }}
            QToolButton::menu-indicator {{ image: none; }}
            QLineEdit, QDoubleSpinBox, QSpinBox {{ background: {c.surface}; color: {c.text};
                border: 1px solid {c.control};
                border-radius: {t.RADIUS_MD}px; padding: 8px; min-height: 18px;
                selection-background-color: {c.accent}; }}
            QComboBox {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.control};
                border-radius: {t.RADIUS_MD}px; padding: 8px 12px; min-height: 18px; min-width: 120px; }}
            QComboBox:focus, QComboBox:on {{ border-color: {c.accent}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{ background: {c.surface}; border: 1px solid {c.border};
                selection-background-color: {c.selected}; selection-color: {c.text}; outline: none; }}
            QLineEdit:focus, QDoubleSpinBox:focus {{ border-color: {c.accent}; }}
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 20px; }}
            QFrame#Rail {{ background: {c.surface}; border-right: 1px solid {c.border}; }}
            QToolButton[nav="true"] {{ background: transparent; border: none; color: {c.muted};
                border-radius: {t.RADIUS_MD}px; padding: 0; font-size: 14px; text-align: left;
                min-height: 44px; max-height: 44px; }}
            QToolButton[nav="true"]:hover {{ background: {c.raised}; }}
            QToolButton[nav="true"]:checked {{ background: {c.selected}; color: {c.accent}; }}
            QToolButton[nav="true"]:focus {{ border: 2px solid {c.accent}; }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ background: transparent; border: none; padding: 0; }}
            QScrollArea {{ background: transparent; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QCheckBox {{ font-size: 12px; spacing: 6px; }}
            QCheckBox::indicator {{ width: 12px; height: 12px; border: 1px solid {c.control}; border-radius: 3px; }}
            QCheckBox::indicator:checked {{ background: {c.accent}; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {c.border}; border-radius: {t.RADIUS_SM}px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QMenu {{ background: {c.surface}; border: 1px solid {c.border}; padding: 5px; }}
            QMenu::item {{ padding: 8px 24px; border-radius: {t.RADIUS_SM}px; }}
            QMenu::item:selected {{ background: {c.selected}; }}
            QToolTip {{ background: {c.raised}; color: {c.text}; border: 1px solid {c.border}; padding: 6px; }}
            QStatusBar {{ background: {c.background}; color: {c.muted}; }}
            QStatusBar::item {{ border: none; }}
            QSplitter::handle {{ background: {c.background}; height: 8px; }}
        """)
        self._app.setWindowIcon(power_icon(c.accent))
        self.changed.emit()


def theme() -> Theme:
    app = QApplication.instance()
    current = app.findChild(Theme, "tapoTheme", Qt.FindChildOption.FindDirectChildrenOnly)
    return current if current is not None else Theme(app)
