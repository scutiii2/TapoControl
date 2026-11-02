"""A left rail of icon buttons beside a stack of pages: a QTabWidget stand-in with the same calls."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from ui import tokens as t
from ui.theme import power_icon, theme

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
    elif kind == "sidebar":
        painter.drawRoundedRect(QRectF(3, 4, 18, 16), 3, 3)
        painter.drawLine(QPointF(9, 4), QPointF(9, 20))
    elif kind == "monitor":
        painter.drawRoundedRect(QRectF(3, 4, 18, 13), 2, 2)
        painter.drawLine(QPointF(8, 21), QPointF(16, 21))
        painter.drawLine(QPointF(12, 17), QPointF(12, 21))
    elif kind == "lamp":
        painter.drawPolygon(QPolygonF([QPointF(8, 3), QPointF(4, 15), QPointF(20, 15), QPointF(16, 3)]))
        painter.drawLine(QPointF(12, 15), QPointF(12, 21))
        painter.drawLine(QPointF(7, 21), QPointF(17, 21))
    elif kind == "coffee":
        painter.drawRoundedRect(QRectF(4, 7, 13, 12), 4, 4)
        painter.drawArc(QRectF(14, 8, 8, 7), -90 * 16, 180 * 16)
        painter.drawLine(QPointF(3, 22), QPointF(19, 22))
    elif kind == "fan":
        painter.drawEllipse(QPointF(12, 12), 2, 2)
        for angle in (0, 120, 240):
            painter.save()
            painter.translate(12, 12)
            painter.rotate(angle)
            painter.drawEllipse(QRectF(-2, -10, 5, 8))
            painter.restore()
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
    collapsedChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self._rail = QFrame()
        self._rail.setObjectName("Rail")
        self._collapsed = False
        self._rail.setFixedWidth(t.SIDEBAR_EXPANDED)
        self._rail_layout = QVBoxLayout(self._rail)
        self._rail_layout.setContentsMargins(t.METRIC_PAD, t.PAGE_Y, t.METRIC_PAD, t.PAGE_BOTTOM)
        self._rail_layout.setSpacing(t.SP_XS)
        brand = QHBoxLayout()
        brand.setSpacing(t.SP_MD)
        self._brand_icon = QLabel()
        self._brand_icon.setFixedSize(35, 35)
        self._brand = QLabel("TapoControl")
        self._brand.setProperty("role", "brand")
        brand.addWidget(self._brand_icon)
        brand.addWidget(self._brand, 1)
        self._rail_layout.addLayout(brand)
        self._rail_layout.addSpacing(t.PAGE_X)
        self._workspace = QLabel("WORKSPACE")
        self._workspace.setProperty("role", "eyebrow")
        self._workspace.setContentsMargins(t.SP_MD, 0, 0, t.SP_SM)
        self._rail_layout.addWidget(self._workspace)
        self._network = QFrame()
        self._network.setObjectName("Network")
        network_layout = QVBoxLayout(self._network)
        network_layout.setContentsMargins(t.SP_MD, t.SP_LG, t.SP_MD, t.SP_LG)
        network_layout.setSpacing(t.SP_SM)
        network_label = QLabel("●  Local network")
        network_label.setProperty("role", "small")
        self._network_status = QLabel("No plugs connected")
        self._network_status.setProperty("role", "caption")
        network_layout.addWidget(network_label)
        network_layout.addWidget(self._network_status)
        self.collapse_button = QToolButton()
        self.collapse_button.setProperty("quiet", True)
        self.collapse_button.setFixedSize(32, 32)
        self.collapse_button.setIconSize(QSize(19, 19))
        self.collapse_button.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        self._stack = QStackedWidget()
        self._buttons: list[QToolButton] = []
        self._kinds: list[str] = []
        self._labels: list[str] = []
        self._bottom = False
        self._group = QButtonGroup(self)
        self._group.idClicked.connect(self.setCurrentIndex)
        self.content = QVBoxLayout()
        self.content.setSpacing(t.SP_LG)
        self.content.addWidget(self._stack, 1)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._rail)
        row.addLayout(self.content, 1)
        theme().changed.connect(self._apply_theme)
        self._apply_theme()
        self.set_collapsed(False)

    def addTab(self, page: QWidget, kind: str, label: str, bottom: bool = False) -> int:
        """`kind` picks the icon; `bottom` puts this and the following buttons at the foot of the rail."""
        index = self._stack.addWidget(page)
        button = QToolButton()
        button.setProperty("nav", True)
        button.setCheckable(True)
        button.setToolTip(f"{label} (Ctrl+{index + 1})")
        button.setAccessibleName(label)
        QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self, activated=lambda: self.setCurrentIndex(index))
        button.setText(label)
        button.setFixedHeight(44)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # a keyboard ring, never a leftover from a mouse click
        button.setIconSize(QSize(18, 18))
        self._group.addButton(button, index)
        if bottom and not self._bottom:
            self._rail_layout.addStretch(1)
            self._rail_layout.addWidget(self._network)
            self._rail_layout.addSpacing(t.SP_SM)
            self._bottom = True
        self._rail_layout.addWidget(button)
        self._buttons.append(button)
        self._kinds.append(kind)
        self._labels.append(label)
        button.setChecked(index == 0)
        self._apply_theme()
        self.set_collapsed(self._collapsed)
        return index

    def _apply_theme(self) -> None:
        colors = theme().colors
        self._brand_icon.setPixmap(power_icon(colors.accent).pixmap(35, 35))
        self.collapse_button.setIcon(nav_icon("sidebar", colors.muted, colors.accent))
        for button, kind in zip(self._buttons, self._kinds, strict=True):
            button.setIcon(nav_icon(kind, colors.muted, colors.accent))

    def set_collapsed(self, collapsed: bool) -> None:
        """Resize only navigation; page objects and in-flight operations remain intact."""
        changed = self._collapsed != collapsed
        self._collapsed = collapsed
        self._rail.setFixedWidth(t.SIDEBAR_COLLAPSED if collapsed else t.SIDEBAR_EXPANDED)
        self._brand.setVisible(not collapsed)
        self._workspace.setVisible(not collapsed)
        self._network.setVisible(not collapsed and self._bottom)
        margin = t.SP_MD if collapsed else t.METRIC_PAD
        self._rail_layout.setContentsMargins(margin, t.PAGE_Y, margin, t.PAGE_BOTTOM)
        for button in self._buttons:
            button.setFixedWidth(48 if collapsed else t.SIDEBAR_EXPANDED - 2 * t.METRIC_PAD)
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if collapsed else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setStyleSheet("padding-left: 0;" if collapsed else "padding-left: 12px;")
        label = "Expand sidebar" if collapsed else "Collapse sidebar"
        self.collapse_button.setToolTip(label)
        self.collapse_button.setAccessibleName(label)
        self.collapse_button.setAccessibleDescription("Sidebar collapsed" if collapsed else "Sidebar expanded")
        if changed:
            self.collapsedChanged.emit(collapsed)

    def show_connection_count(self, online: int) -> None:
        self._network_status.setText(f"{online} plug{'s' if online != 1 else ''} connected")

    def setCurrentIndex(self, index: int) -> None:
        if index == self._stack.currentIndex():
            return
        self._stack.setCurrentIndex(index)
        self._buttons[index].setChecked(True)
        self.currentChanged.emit(index)

    def setCurrentWidget(self, page: QWidget) -> None:
        self.setCurrentIndex(self._stack.indexOf(page))

    def kind(self, index: int) -> str:
        return self._kinds[index]

    def currentIndex(self) -> int:
        return self._stack.currentIndex()

    def currentWidget(self) -> QWidget:
        return self._stack.currentWidget()

    def widget(self, index: int) -> QWidget:
        return self._stack.widget(index)
