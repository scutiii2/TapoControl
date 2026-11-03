"""Split button: a main action beside a chevron half that opens a menu of related actions below it."""
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, Qt, QVariantAnimation
from PySide6.QtGui import QAction, QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QSizePolicy, QToolButton, QWidget

from ui import tokens as t
from ui.theme import theme


class ChevronButton(QToolButton):
    """The menu half: draws its own chevron, which turns upside down while the menu is open."""

    def __init__(self) -> None:
        super().__init__()
        self.angle = 0.0

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(QPointF(self.width() / 2, self.height() / 2))
        painter.rotate(self.angle)
        pen = QPen(QColor(theme().colors.accent_text), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(-4, -2), QPointF(0, 2))
        painter.drawLine(QPointF(0, 2), QPointF(4, -2))


class SplitButton(QWidget):
    """`main` runs the default action; `arrow` opens the menu directly under the whole button."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(t.SP_XS)  # the thin gap that reads as one pill cut in two
        self.main = QPushButton(text)
        self.arrow = ChevronButton()
        self.main.setFixedHeight(t.SPLIT_HEIGHT)  # one explicit height, so the halves match whatever the style measures
        self.arrow.setFixedHeight(t.SPLIT_HEIGHT)
        self.main.setProperty("primary", True)
        self.main.setProperty("split", "left")
        self.arrow.setProperty("primary", True)
        self.arrow.setProperty("split", "right")
        self.arrow.setAccessibleName(f"More options for {text.rstrip('…')}")
        self.arrow.setToolTip("More options")
        self.menu = QMenu(self)
        self.menu.aboutToShow.connect(lambda: self._turn(180.0))
        self.menu.aboutToHide.connect(lambda: self._turn(0.0))
        self.arrow.clicked.connect(self._open)
        self._turning = QVariantAnimation(self)
        self._turning.setDuration(t.MOTION_MS + 60)
        self._turning.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._turning.valueChanged.connect(self._set_angle)
        row.addWidget(self.main)
        row.addWidget(self.arrow)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # one pill, never squeezed or stretched
        self.setFixedHeight(t.SPLIT_HEIGHT)
        self.main.installEventFilter(self)  # the menu half follows the main half's enabled state

    def add_action(self, text: str, callback: Callable[[], None]) -> QAction:
        return self.menu.addAction(text, callback)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.main and event.type() == QEvent.Type.EnabledChange:
            self.arrow.setEnabled(self.main.isEnabled())
        return False

    def _open(self) -> None:
        # right edges line up, so the menu stays inside the window when the button sits at the page's right
        x = self.width() - self.menu.sizeHint().width()
        self.menu.popup(self.mapToGlobal(QPoint(x, self.height() + t.SP_XS)))

    def _turn(self, target: float) -> None:
        self._turning.stop()
        self._turning.setStartValue(self.arrow.angle)
        self._turning.setEndValue(target)
        self._turning.start()

    def _set_angle(self, value: float) -> None:
        self.arrow.angle = value
        self.arrow.update()
