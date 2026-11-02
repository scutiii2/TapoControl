"""Responsive native device grid; resizing keeps every card and signal connection alive."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QGridLayout, QListView, QListWidget, QWidget

from ui import tokens as t
from ui.plug_card import PlugCard


class DeviceList(QListWidget):
    """Selectable responsive cards with native keyboard navigation."""

    def __init__(self) -> None:
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setSpacing(t.SP_SM)
        self.setResizeMode(QListView.ResizeMode.Adjust)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_cards()

    def fit_cards(self) -> None:
        width = self.viewport().width()
        limit = 2 if width < 840 else 4
        columns = max(1, min(limit, width // (t.DEVICE_MIN_WIDTH + 2 * self.spacing())))
        card_width = max(1, width // columns - 2 * self.spacing() - 2)
        for index in range(self.count()):
            self.item(index).setSizeHint(QSize(card_width, t.DEVICE_HEIGHT))


class DeviceGrid(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.cards: dict[str, PlugCard] = {}
        self.columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(t.CARD_GAP)

    def sync(self, keys: list[str]) -> list[tuple[str, PlugCard]]:
        """Return only newly created cards so callers connect each signal once."""
        for key in self.cards.keys() - set(keys):
            card = self.cards.pop(key)
            self._grid.removeWidget(card)
            card.deleteLater()
        added = []
        for key in keys:
            if key not in self.cards:
                card = PlugCard(key)
                self.cards[key] = card
                added.append((key, card))
        self._reflow(force=True)
        return added

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, force: bool = False) -> None:
        limit = 2 if self.width() < 840 else 4
        columns = max(1, min(limit, (self.width() + t.CARD_GAP) // (t.DEVICE_MIN_WIDTH + t.CARD_GAP)))
        if columns == self.columns and not force:
            return
        previous = self.columns
        self.columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for col in range(max(previous, columns)):
            self._grid.setColumnStretch(col, 1 if col < columns else 0)
        for index, card in enumerate(self.cards.values()):
            self._grid.addWidget(card, index // columns, index % columns)
        rows = (len(self.cards) + columns - 1) // columns
        self.setMinimumHeight(rows * t.DEVICE_HEIGHT + max(0, rows - 1) * t.CARD_GAP)
