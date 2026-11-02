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
    "#f3f5f9", "#ffffff", "#edf1f6", "#c7d0de", "#7a889e", "#192332", "#53637b",
    "#185cce", "#ffffff", "#eaf2ff", "#15765b", "#b32632",
    ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
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
        painter.setPen(QPen(QColor("#132137"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
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
        self.colors = palette_for(app.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        app.setStyle("Fusion")
        app.setFont(QFont("Segoe UI", 10))
        app.styleHints().colorSchemeChanged.connect(self.apply)
        self.apply(app.styleHints().colorScheme())

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
            QWidget {{ color: {c.text}; }}
            QLabel {{ background: transparent; }}
            QLabel[tone="muted"] {{ color: {c.muted}; }}
            QLabel[tone="success"] {{ color: {c.success}; }}
            QLabel[tone="error"] {{ color: {c.error}; }}
            QLabel[role="title"] {{ font-size: {t.FONT_TITLE}px; font-weight: 600; }}
            QLabel[role="heading"] {{ font-size: {t.FONT_HEADING}px; font-weight: 600; }}
            QLabel[role="metric"] {{ font-size: {t.FONT_METRIC}px; font-weight: 600; }}
            QFrame[card="true"] {{ background: {c.surface}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_LG}px; }}
            QFrame#DeviceCard[selected="true"] {{ background: {c.selected}; border-color: {c.accent}; }}
            QFrame#DeviceCard[offline="true"] QLabel {{ color: {c.muted}; }}
            QFrame#DeviceCard[offline="true"] {{ border-style: dashed; }}
            QPushButton, QToolButton {{ background: {c.surface}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_MD}px; padding: 8px 16px; min-height: 18px; }}
            QPushButton:hover, QToolButton:hover {{ background: {c.raised}; border-color: {c.accent}; }}
            QPushButton:pressed, QToolButton:pressed {{ background: {c.selected}; }}
            QPushButton:focus, QToolButton:focus {{ border: 2px solid {c.accent}; }}
            QPushButton[primary="true"] {{ background: {c.accent}; color: {c.accent_text}; font-weight: 600; }}
            QPushButton:disabled, QToolButton:disabled {{ color: {c.muted}; background: {c.raised}; }}
            QToolButton::menu-indicator {{ image: none; }}
            QLineEdit, QDoubleSpinBox {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.control};
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
            QToolButton[nav="true"] {{ background: transparent; border: none;
                border-radius: {t.RADIUS_MD}px; padding: 0; }}
            QToolButton[nav="true"]:hover {{ background: {c.raised}; }}
            QToolButton[nav="true"]:checked {{ background: {c.selected}; border-left: 3px solid {c.accent}; }}
            QToolButton[nav="true"]:focus {{ border: 2px solid {c.accent}; }}
            QListWidget {{ background: transparent; border: none; outline: none; }}
            QListWidget::item {{ background: transparent; border: none; padding: 0; }}
            QScrollArea {{ background: transparent; border: none; }}
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
