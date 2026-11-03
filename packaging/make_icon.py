"""Write packaging/TapoControl.ico from the app's own power logo, so the exe and installer match the window icon.

Usage: .venv/Scripts/python.exe packaging/make_icon.py
"""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from ui.theme import LIGHT, power_icon  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def build_ico() -> bytes:
    """An ICO holding one PNG per size (Windows Vista and later read PNG entries, up to 256 px)."""
    icon = power_icon(LIGHT.accent)
    images = []
    for size in SIZES:
        data = QBuffer()
        data.open(QIODevice.OpenModeFlag.WriteOnly)
        icon.pixmap(size, size).save(data, "PNG")
        images.append((size, bytes(data.data())))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, payload = b"", b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 means 256 in an ICO directory
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


if __name__ == "__main__":
    app = QGuiApplication([])
    target = Path(__file__).with_name("TapoControl.ico")
    target.write_bytes(build_ico())
    print(f"Wrote {target}")
