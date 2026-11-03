"""Plug rows in one column; resizing keeps every row and signal connection alive."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListView, QListWidget, QVBoxLayout, QWidget

from ui import tokens as t
from ui.plug_card import PlugCard, mark_first


class DeviceList(QListWidget):
    """Selectable plug rows with native keyboard navigation."""

    def __init__(self) -> None:
        super().__init__()
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setMovement(QListView.Movement.Static)
        self.setSpacing(t.SP_SM)
        self.setResizeMode(QListView.ResizeMode.Adjust)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fit_cards()

    def fit_cards(self) -> None:
        width = max(1, self.viewport().width() - 2 * self.spacing() - 2)
        for index in range(self.count()):
            item = self.item(index)
            card = self.itemWidget(item)
            item.setSizeHint(QSize(width, card.height() if card else t.DEVICE_HEIGHT))


class DeviceGrid(QWidget):
    """A column of plug rows."""

    def __init__(self) -> None:
        super().__init__()
        self.cards: dict[str, PlugCard] = {}
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(0)

    def sync(self, keys: list[str]) -> list[tuple[str, PlugCard]]:
        """Return only newly created rows so callers connect each signal once."""
        for key in self.cards.keys() - set(keys):
            card = self.cards.pop(key)
            self._column.removeWidget(card)
            card.deleteLater()
        added = []
        for key in keys:
            if key not in self.cards:
                card = PlugCard(key, actions=False)  # the Devices page carries rename, energy and timer
                self.cards[key] = card
                self._column.addWidget(card)
                added.append((key, card))
        mark_first(self.cards[key] for key in keys)
        return added
