"""Page-local layout rules for the control pages; Overview keeps its own styling."""

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui import tokens as t
from ui.interaction import Fade, contains, poller
from ui.theme import theme

FORM_WIDTH = 620
SETTINGS_WIDTH = 880


class ChoiceBox(QComboBox):
    """Native combo behavior with a clear chevron and a rounded, themed popup list on both Windows palettes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.view().viewport().setCursor(Qt.CursorShape.PointingHandCursor)  # popup rows are clickable
        self.setItemDelegate(QStyledItemDelegate(self))  # lets the stylesheet shape each row

    def showPopup(self) -> None:
        # Qt resets the popup window's flags between openings, so make it see-through every time:
        # without this the rounded list sits inside a square frame.
        popup = self.view().window()
        popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.NoDropShadowWindowHint)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.setFrameShape(QFrame.Shape.NoFrame)
        popup.installEventFilter(self)
        super().showPopup()
        # Open the list under the box rather than over it; the container keeps a margin above the list.
        margin = self.view().geometry().top()
        popup.move(self.mapToGlobal(QPoint(0, self.height() + t.SP_XS - margin)))
        popup.resize(self.width(), popup.height())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # The container paints a square menu frame around the list; the list draws its own rounded border.
        if watched is self.view().window() and event.type() == QEvent.Type.Paint:
            return True
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme().colors.muted), 1.5))
        x, y = self.width() - 18, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)


class _Stepper:
    """Up and down buttons that fade a tint in on hover and show a pointer cursor over them.

    Mixed in before the spin box class: the stylesheet leaves the buttons blank, so they are painted here.
    """

    def _setup_stepper(self) -> None:
        # A text margin gives the left gap in every layout; stylesheet padding on a spin box is not honored there.
        self.lineEdit().setTextMargins(t.SP_MD, 0, 0, 0)
        self.setMouseTracking(True)
        self._fades = {"up": Fade(self), "down": Fade(self)}
        poller(self)

    def _button_rects(self) -> dict[str, QRect]:
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        style = self.style()
        return {
            "up": style.subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, self),
            "down": style.subControlRect(
                QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, self
            ),
        }

    def _hover_button(self, position: QPoint | None) -> None:
        over = next((name for name, rect in self._button_rects().items() if position and rect.contains(position)), None)
        if over and self.isEnabled():
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        for name, fade in self._fades.items():
            fade.to(1.0 if name == over and self.isEnabled() else 0.0)

    def mouseMoveEvent(self, event) -> None:
        self._hover_button(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_button(None)
        super().leaveEvent(event)

    def poll_hover(self, under: QWidget | None, position: QPoint) -> None:
        self._hover_button(self.mapFromGlobal(position) if contains(self, under) else None)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tint = QColor(theme().colors.text)
        painter.setPen(QPen(QColor(theme().colors.muted), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for name, rect in self._button_rects().items():
            fade = self._fades[name].value
            if fade:
                tint.setAlphaF(0.14 * fade)
                painter.setBrush(tint)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(QRectF(rect).adjusted(2, 2, -2, -2), t.RADIUS_SM, t.RADIUS_SM)
                painter.setPen(QPen(QColor(theme().colors.muted), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x, y, rise = rect.center().x(), rect.center().y(), -1 if name == "up" else 1
            painter.drawLine(QPointF(x - 3.5, y - 1.5 * rise), QPointF(x, y + 1.5 * rise))
            painter.drawLine(QPointF(x, y + 1.5 * rise), QPointF(x + 3.5, y - 1.5 * rise))


class IntBox(_Stepper, QSpinBox):
    """Whole-number input with visible, animated steppers."""

    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self._setup_stepper()


class DecimalBox(_Stepper, QDoubleSpinBox):
    """Decimal input with visible, animated steppers."""

    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self._setup_stepper()


def text_label(text: str, role: str = "", *, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("tone", "muted")
    return label


def panel(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(t.SP_XL, t.SP_LG, t.SP_XL, t.SP_LG)
    layout.setSpacing(t.SP_MD)
    if title:
        layout.addWidget(text_label(title, "heading"))
    return frame, layout


def style_control_page(widget: QWidget) -> None:
    """Apply current palette only within this page's subtree."""
    c = theme().colors
    widget.setStyleSheet(f"""
        QLabel {{ font-size: 14px; }}
        QLabel[role="heading"] {{ font-size: 17px; font-weight: 600; }}
        QLabel[role="caption"] {{ font-size: 12px; color: {c.muted}; }}
        QLabel[role="control-name"] {{ font-size: 16px; font-weight: 600; }}
        QLabel[role="control-value"] {{ font-size: 18px; font-weight: 600; }}
        QLabel[role="metric"] {{ font-size: 26px; font-weight: 600; }}
        QLabel[tone="muted"] {{ color: {c.muted}; }}
        QLabel[tone="error"] {{ color: {c.error}; }}
        QLabel[tone="success"] {{ color: {c.success}; }}
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ min-height: 24px; }}
        QComboBox::down-arrow {{ image: none; }}
        QCheckBox {{ font-size: 14px; spacing: 8px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; }}
    """)


class ControlPage(QScrollArea):
    """Scrollable content with optional form measure and no horizontal overflow."""

    def __init__(self, parent=None, *, max_width: int = 0):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, t.SP_SM, 0)
        self.body = QWidget()
        self.body.setMinimumWidth(0)
        if max_width:
            self.body.setMaximumWidth(max_width)
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, t.SP_SM, 0, t.SP_LG)
        self.content.setSpacing(t.SP_XL)
        outer.addWidget(self.body, 1)
        if max_width:
            outer.addStretch()
        self.setWidget(root)
        theme().changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        style_control_page(self)
