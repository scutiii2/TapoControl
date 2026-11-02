"""A left rail of icon buttons beside a stack of pages: a QTabWidget stand-in with the same calls."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from ui.theme import theme

ICON_SIZES = (24, 32, 48)


def _paint_icon(painter: QPainter, kind: str, color: QColor) -> None:
    """Draw `kind` on a 24 x 24 grid."""
    painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "overview":
        for x, y in ((3, 3), (14, 3), (3, 14), (14, 14)):
            painter.drawRoundedRect(QRectF(x, y, 7, 7), 2, 2)
    elif kind == "devices":
        painter.drawLine(QPointF(9, 2.5), QPointF(9, 7))
        painter.drawLine(QPointF(15, 2.5), QPointF(15, 7))
        painter.drawRoundedRect(QRectF(6, 7, 12, 7.5), 3, 3)
        painter.drawLine(QPointF(12, 14.5), QPointF(12, 21.5))
    elif kind == "energy":
        bolt = ((13, 2), (5, 13.5), (11, 13.5), (10, 22), (19, 10.5), (13, 10.5))
        painter.drawPolygon(QPolygonF([QPointF(*point) for point in bolt]))
    elif kind == "account":
        painter.drawEllipse(QPointF(12, 8), 4, 4)
        painter.drawArc(QRectF(4, 14, 16, 14), 0, 180 * 16)
    else:  # settings: three sliders
        painter.setBrush(color)
        for y, knob in ((6, 8), (12, 16), (18, 10)):
            painter.drawLine(QPointF(3, y), QPointF(21, y))
            painter.drawEllipse(QPointF(knob, y), 2.4, 2.4)


def nav_icon(kind: str, muted: str, accent: str) -> QIcon:
    """Muted when idle, accent while the page is open."""
    icon = QIcon()
    for color, state in ((muted, QIcon.State.Off), (accent, QIcon.State.On)):
        for size in ICON_SIZES:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.scale(size / 24, size / 24)
            _paint_icon(painter, kind, QColor(color))
            painter.end()
            icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


class SideTabs(QWidget):
    """Pages chosen from an icon rail on the left. `content` is the column above the pages, for a shared header."""

    currentChanged = Signal(int)

    def __init__(self):
        super().__init__()
        self._rail = QFrame()
        self._rail.setObjectName("Rail")
        self._rail.setFixedWidth(68)
        self._rail_layout = QVBoxLayout(self._rail)
        self._rail_layout.setContentsMargins(10, 14, 10, 14)
        self._rail_layout.setSpacing(6)
        self._stack = QStackedWidget()
        self._buttons: list[QToolButton] = []
        self._kinds: list[str] = []
        self._bottom = False
        self._group = QButtonGroup(self)
        self._group.idClicked.connect(self.setCurrentIndex)
        self.content = QVBoxLayout()
        self.content.setSpacing(16)
        self.content.addWidget(self._stack, 1)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._rail)
        row.addLayout(self.content, 1)
        theme().changed.connect(self._apply_theme)

    def addTab(self, page: QWidget, kind: str, label: str, bottom: bool = False) -> int:
        """`kind` picks the icon; `bottom` puts this and the following buttons at the foot of the rail."""
        index = self._stack.addWidget(page)
        button = QToolButton()
        button.setProperty("nav", True)
        button.setCheckable(True)
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setFixedSize(48, 48)
        button.setIconSize(QSize(26, 26))
        self._group.addButton(button, index)
        if bottom and not self._bottom:
            self._rail_layout.addStretch(1)
            self._bottom = True
        self._rail_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._buttons.append(button)
        self._kinds.append(kind)
        button.setChecked(index == 0)
        self._apply_theme()
        return index

    def _apply_theme(self) -> None:
        colors = theme().colors
        for button, kind in zip(self._buttons, self._kinds, strict=True):
            button.setIcon(nav_icon(kind, colors.muted, colors.accent))

    def setCurrentIndex(self, index: int) -> None:
        if index == self._stack.currentIndex():
            return
        self._stack.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self.currentChanged.emit(index)

    def setCurrentWidget(self, page: QWidget) -> None:
        self.setCurrentIndex(self._stack.indexOf(page))

    def currentIndex(self) -> int:
        return self._stack.currentIndex()

    def currentWidget(self) -> QWidget:
        return self._stack.currentWidget()

    def widget(self, index: int) -> QWidget:
        return self._stack.widget(index)
