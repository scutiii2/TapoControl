"""Small widgets shared by several pages."""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ui import tokens as t


def cost_line(wh: float, price: float, hint: str) -> str:
    """Cost of `wh` at `price` per kWh, or `hint` when no tariff is set (0.00 would read as free)."""
    return f"Estimated cost {wh / 1000 * price:.2f}" if price else hint


def metric_card(row: QHBoxLayout, title: str, sub: str = "—") -> tuple[QLabel, QLabel]:
    """A titled card with a big value and a muted line under it; returns (value label, sub label)."""
    card = QFrame()
    card.setProperty("card", True)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(t.CARD_PAD, t.CARD_PAD, t.CARD_PAD, t.CARD_PAD)
    layout.setSpacing(t.SP_XS)
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
