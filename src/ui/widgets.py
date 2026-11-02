"""Small widgets shared by several pages."""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


def metric_card(row: QHBoxLayout, title: str, sub: str = "—") -> tuple[QLabel, QLabel]:
    """A titled card with a big value and a muted line under it; returns (value label, sub label)."""
    card = QFrame()
    card.setProperty("card", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 16, 20, 16)
    heading = QLabel(title)
    heading.setProperty("tone", "muted")
    value = QLabel("—")
    value.setProperty("role", "metric")
    detail = QLabel(sub)
    detail.setProperty("tone", "muted")
    for label in (heading, value, detail):
        layout.addWidget(label)
    row.addWidget(card, 1)
    return value, detail
