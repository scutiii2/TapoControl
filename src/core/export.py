"""CSV text for the history shown in the Energy tab."""
import csv
import io
from datetime import date


def history_csv(rows: list[tuple[date | int, int]], kind: str, price: float) -> str:
    """`rows` are (date, Wh), or (hour, Wh) for kind "hour"; `kind` is "hour", "day" or "month"."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([{"hour": "hour", "day": "date", "month": "month"}[kind], "kWh", "cost"])
    for key, wh in rows:
        label = f"{key:02d}:00" if kind == "hour" else key.strftime("%Y-%m" if kind == "month" else "%Y-%m-%d")
        writer.writerow([label, f"{wh / 1000:.3f}", f"{wh / 1000 * price:.2f}"])
    return out.getvalue()
