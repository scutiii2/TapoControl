"""Hover and press feedback for clickable widgets: a pointer cursor and a short tint animation."""
import weakref

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QPainter
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QMenu,
    QPushButton,
    QTabBar,
    QToolButton,
    QWidget,
)

from ui import tokens as t
from ui.theme import theme

CLICKABLE = (QAbstractButton, QComboBox, QTabBar)
TINTED = (QPushButton, QToolButton)  # the stylesheet owns these buttons' fill, so the tint is a separate layer


def set_pointer(widget: QWidget) -> None:
    """Pointer cursor while the widget accepts clicks, the normal arrow while it is disabled."""
    widget.setCursor(Qt.CursorShape.PointingHandCursor if widget.isEnabled() else Qt.CursorShape.ArrowCursor)


class Fade(QObject):
    """A value that eases toward 0 or 1 and repaints its widget on every step."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self.value = 0.0
        self.goal = 0.0
        self._widget = widget
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(t.MOTION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._step)

    def to(self, goal: float) -> None:
        if goal == self.goal:
            return
        self.goal = goal
        self._animation.stop()
        self._animation.setStartValue(self.value)
        self._animation.setEndValue(goal)
        self._animation.start()

    def reset(self) -> None:
        self._animation.stop()
        self.value = self.goal = 0.0
        self._widget.update()

    def _step(self, value: float) -> None:
        self.value = value
        self._widget.update()


class HoverPoller(QObject):
    """While a popup is open Qt sends no hover events to the windows under it, so follow the cursor instead.

    Widgets register once and answer `poll_hover(under, global_pos)`; the timer only runs while a popup is open.
    """

    def __init__(self) -> None:
        super().__init__()
        self._targets: list[weakref.ReferenceType] = []
        self._overriding = False
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def register(self, widget: QWidget) -> None:
        self._targets.append(weakref.ref(widget))

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        position = QCursor.pos()
        under = QApplication.widgetAt(position)
        alive = []
        for reference in self._targets:
            widget = reference()
            if widget is not None and isValid(widget):  # rows and buttons are deleted while the app runs
                alive.append(reference)
                widget.poll_hover(under, position)
        self._targets = alive
        if QApplication.activePopupWidget() is None:
            self._timer.stop()
            self._follow_cursor(None)
        else:
            self._follow_cursor(under)

    def _follow_cursor(self, under: QWidget | None) -> None:
        """The popup owns the mouse, so Qt ignores each widget's own cursor; apply the one under the pointer."""
        if under is None:
            if self._overriding:
                QApplication.restoreOverrideCursor()
                self._overriding = False
            return
        widget = under
        while widget is not None and not widget.testAttribute(Qt.WidgetAttribute.WA_SetCursor):
            widget = widget.parentWidget()
        cursor = widget.cursor() if widget is not None else QCursor(Qt.CursorShape.ArrowCursor)
        if self._overriding:
            QApplication.changeOverrideCursor(cursor)
        else:
            QApplication.setOverrideCursor(cursor)
            self._overriding = True


_poller = HoverPoller()
poller = _poller.register  # widgets call poller(self) once


def start_polling() -> None:
    _poller.start()


def contains(widget: QWidget, under: QWidget | None) -> bool:
    """Whether `under`, the widget at the cursor, is `widget` or one of its children."""
    return under is not None and (under is widget or widget.isAncestorOf(under))


class PressOverlay(QWidget):
    """Transparent layer over a button: fades in on hover, deepens and insets while pressed."""

    def __init__(self, button: QWidget) -> None:
        super().__init__(button)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hover = Fade(self)
        self._press = Fade(self)
        button.installEventFilter(self)
        poller(self)
        self.setGeometry(button.rect())
        self.raise_()

    def poll_hover(self, under: QWidget | None, position: QPoint) -> None:
        self._hover.to(1.0 if contains(self.parentWidget(), under) else 0.0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Enter:
            self._hover.to(1.0)
        elif kind == QEvent.Type.Leave:
            self._hover.to(0.0)
            self._press.to(0.0)
        elif kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._press.to(1.0)
        elif kind == QEvent.Type.MouseButtonRelease:
            self._press.to(0.0)
        elif kind == QEvent.Type.Resize:
            self.setGeometry(watched.rect())
        elif kind == QEvent.Type.EnabledChange:
            set_pointer(watched)
            self._hover.reset()
            self._press.reset()
        elif kind in (QEvent.Type.ChildAdded, QEvent.Type.Show):
            self.raise_()
        return False

    def paintEvent(self, event) -> None:
        hover, press = self._hover.value, self._press.value
        if not self.parentWidget().isEnabled() or not (hover or press):
            return
        color = QColor(theme().colors.text)
        color.setAlphaF(0.11 * hover + 0.09 * press)
        inset = 1.5 * press
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), t.RADIUS_MD, t.RADIUS_MD)


def show_ring_for_keyboard(button: QAbstractButton, event) -> None:
    """Show the focus ring only after keyboard focus; a click, or a window opening, leaves a button unringed."""
    keyboard = event.type() == QEvent.Type.FocusIn and event.reason() in (
        Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason,
    )
    if bool(button.property("kbd")) != keyboard:
        button.setProperty("kbd", keyboard)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()


def round_menu(menu: QMenu) -> None:
    """Make the menu window see-through and shadowless so the stylesheet's rounded corners show."""
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def enhance(widget: QObject) -> None:
    """Called once per widget as it is first styled; adds the cursor and, for buttons, the animated tint."""
    if isinstance(widget, QMenu) and not widget.property("rounded"):
        widget.setProperty("rounded", True)
        round_menu(widget)
        return
    if not isinstance(widget, CLICKABLE) or widget.property("interactive"):
        return
    widget.setProperty("interactive", True)
    set_pointer(widget)
    if isinstance(widget, TINTED):
        PressOverlay(widget)
