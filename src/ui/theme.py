"""Shared system-following colors, widget styling and application icon."""
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QApplication, QMenu, QWidget

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
    "#151816", "#1b1f1d", "#242927", "#363c39", "#74807a", "#edf1ee", "#a8b2ac",
    "#62c299", "#0e2218", "#263029", "#6fd3a2", "#ffb4b4",
    ("#4fb88a", "#e0953a", "#5b9bd5", "#d07aa6", "#3fb8b8", "#d98a5a", "#9d8ce0", "#9fb3a6"),
)
LIGHT = Colors(
    "#f6f8f5", "#fcfdfb", "#eff3ec", "#e3e9e3", "#718077", "#20322c", "#586860",
    "#287351", "#ffffff", "#eaf2e9", "#287351", "#b32632",
    ("#2f7a56", "#a15c00", "#2f6fb0", "#a04a7c", "#1f7a7a", "#a0522d", "#6a55b0", "#5c6b62"),
)


MODES = ("system", "light", "dark")


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
    for size in (16, 24, 32, 48, 64, 128, 256):
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
        self.mode = "system"
        app.installEventFilter(self)
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self._follow_system())
        app.setStyle("Fusion")
        font = QFont(t.FONT_FAMILY)
        font.setPixelSize(t.FONT_BODY)
        app.setFont(font)
        self.apply(Qt.ColorScheme.Light)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Every clickable widget, however it is made, gets a pointer cursor and hover/press feedback."""
        popup = event.type() == QEvent.Type.Show and isinstance(watched, QWidget)
        if popup and watched.windowType() == Qt.WindowType.Popup:
            interaction.start_polling()  # menus and dropdown lists block hover events for the windows beneath them
        if isinstance(watched, (interaction.CLICKABLE, QMenu)):
            if event.type() == QEvent.Type.Polish:
                interaction.enhance(watched)
            elif event.type() == QEvent.Type.EnabledChange and isinstance(watched, interaction.CLICKABLE):
                interaction.set_pointer(watched)
            elif event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut) and isinstance(watched, QAbstractButton):
                interaction.show_ring_for_keyboard(watched, event)
        return False

    @property
    def dark(self) -> bool:
        return self.colors is DARK

    def set_mode(self, mode: str) -> None:
        """`mode` is "system", "light" or "dark"; "system" follows Windows live."""
        self.mode = mode if mode in MODES else "system"
        if self.mode == "system":
            self._follow_system()
        else:
            self.apply(Qt.ColorScheme.Dark if self.mode == "dark" else Qt.ColorScheme.Light)

    def cycle(self) -> None:
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])

    def _follow_system(self) -> None:
        if self.mode == "system":
            self.apply(
                Qt.ColorScheme.Dark
                if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
                else Qt.ColorScheme.Light
            )

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
            QLabel[role="brand"] {{ font-size: 19px; font-weight: 700; }}
            QLabel[role="device-value"] {{ font-size: {t.FONT_BODY}px; }}
            QLabel[role="plug-name"] {{ font-size: {t.FONT_SMALL}px; font-weight: 500; }}
            QPushButton[link="true"] {{ background: transparent; border: none; color: {c.accent};
                padding: 2px 4px; min-height: 0; font-weight: 600; }}
            QPushButton[link="true"]:hover {{ background: transparent; text-decoration: underline; }}
            QFrame#Network {{ background: {c.raised}; border-radius: 10px; }}
            QFrame[card="true"] {{ background: {c.surface}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_LG}px; }}
            QFrame[highlight="true"] {{ background: {c.selected};
                border: 1px solid {c.border}; border-radius: 12px; }}
            QFrame#DeviceCard {{ background: transparent; border: none; border-top: 1px solid {c.border}; }}
            QFrame#DeviceCard[first="true"] {{ border-top: none; }}  /* the panel's own border is the top edge */
            QFrame#DeviceCard[offline="true"] QLabel {{ color: {c.muted}; }}
            QPushButton[segment="true"] {{ background: transparent; border: none; color: {c.muted};
                padding: 3px 9px; min-height: 0; font-size: {t.FONT_CAPTION}px; }}
            QPushButton[segment="true"]:hover {{ background: {c.raised}; }}
            QPushButton[segment="true"]:checked {{ background: {c.selected}; color: {c.text}; font-weight: 600; }}
            QLabel[role="pill"] {{ background: {c.raised}; border-radius: 9px; padding: 2px 8px;
                font-size: {t.FONT_CAPTION}px; color: {c.muted}; }}
            QLabel[role="pill"][state="on"] {{ background: {c.selected}; color: {c.success}; }}
            QPushButton, QToolButton {{ background: {c.surface}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_MD}px; padding: 8px 16px; min-height: 18px; }}
            QPushButton:hover, QToolButton:hover {{ background: {c.raised}; border-color: {c.accent}; }}
            QPushButton:pressed, QToolButton:pressed {{ background: {c.selected}; }}
            QPushButton[kbd="true"]:focus, QToolButton[kbd="true"]:focus {{ border: 2px solid {c.accent}; }}
            QPushButton[split], QToolButton[split] {{ min-height: 0; padding-top: 0; padding-bottom: 0; }}
            QPushButton[split="left"] {{ border-top-right-radius: 3px; border-bottom-right-radius: 3px;
                padding: 8px 12px; }}
            QToolButton[split="right"] {{ border-top-left-radius: 3px; border-bottom-left-radius: 3px;
                padding: 8px 4px; min-width: 20px; }}
            QToolButton[primary="true"] {{ background: {c.accent}; color: {c.accent_text}; border-color: {c.accent}; }}
            QPushButton[primary="true"] {{ background: {c.accent}; color: {c.accent_text}; font-weight: 600; }}
            QPushButton:disabled, QToolButton:disabled, QToolButton[primary="true"]:disabled {{
                color: {c.muted}; background: {c.raised}; border-color: {c.border}; }}
            QPushButton[quiet="true"], QToolButton[quiet="true"] {{ background: transparent; border: none;
                padding: 0; font-size: 10px; color: {c.muted}; }}
            QPushButton[compact="true"] {{ font-size: 10px; padding: 6px 12px; min-height: 16px; }}
            QToolButton::menu-indicator {{ image: none; }}
            QLineEdit, QDoubleSpinBox, QSpinBox {{ background: {c.surface}; color: {c.text};
                border: 1px solid {c.control};
                border-radius: {t.RADIUS_MD}px; padding: 8px 12px; min-height: 18px;
                selection-background-color: {c.accent}; }}
            QDoubleSpinBox, QSpinBox {{ padding: 8px 34px 8px 0; }}  /* left gap comes from the text margin */
            QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 26px;
                border: none; background: transparent; border-radius: {t.RADIUS_SM}px; }}
            QAbstractSpinBox::up-button {{ subcontrol-position: top right; margin: 3px 3px 0 0; }}
            QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; margin: 0 3px 3px 0; }}
            QAbstractSpinBox::up-arrow, QAbstractSpinBox::down-arrow {{ image: none; width: 0; height: 0; }}
            QComboBox {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.control};
                border-radius: {t.RADIUS_MD}px; padding: 8px 12px; min-height: 18px; min-width: 104px; }}
            QComboBox:focus, QComboBox:on {{ border-color: {c.accent}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBoxPrivateContainer {{ background: transparent; border: none; }}
            QComboBox QAbstractItemView {{ background: {c.surface}; color: {c.text}; border: 1px solid {c.border};
                border-radius: {t.RADIUS_MD}px; padding: 4px; selection-background-color: {c.selected};
                selection-color: {c.text}; outline: none; }}
            QComboBox QAbstractItemView::item {{ min-height: 32px; padding: 0 10px; border-radius: {t.RADIUS_SM}px; }}
            QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{
                background: {c.selected}; color: {c.text}; }}
            QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {c.accent}; }}
            QFrame#Rail {{ background: {c.surface}; border-right: 1px solid {c.border}; }}
            QToolButton[nav="true"] {{ background: transparent; border: none; color: {c.muted};
                border-radius: {t.RADIUS_MD}px; padding: 0; font-size: 14px; text-align: left;
                min-height: 44px; max-height: 44px; }}
            QToolButton[nav="true"]:hover {{ background: {c.raised}; }}
            QToolButton[nav="true"]:checked {{ background: {c.selected}; color: {c.accent}; }}
            QToolButton[nav="true"][kbd="true"]:focus {{ border: 2px solid {c.accent}; }}
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
            QMenu {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: {t.RADIUS_MD}px;
                padding: 5px; }}
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

from ui import interaction  # noqa: E402  - it imports theme() from here, so it comes last
