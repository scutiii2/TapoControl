"""Typical watts of a plug by time of day, used to estimate the parts of a chart nobody recorded."""
from collections.abc import Mapping, Sequence
from datetime import datetime

SLOT_SECONDS = 300
MIN_FILL_SECONDS = 30  # shorter gaps are just a missed poll; leave the straight line
MIN_READINGS = 12  # about a minute of 5-second readings before a slot counts as known

Key = tuple[int, int]  # (is_weekend, slot of the day)
Profile = Mapping[Key, tuple[float, int]]  # key -> (mean watts, readings)


def slot_key(ts: float) -> Key:
    t = datetime.fromtimestamp(ts)
    return int(t.weekday() >= 5), (t.hour * 3600 + t.minute * 60 + t.second) // SLOT_SECONDS


def _typical(profile: Profile, ts: float) -> float | None:
    mean, n = profile.get(slot_key(ts), (0.0, 0))
    return mean if n >= MIN_READINGS else None


def total_series(
    series: Sequence[Sequence[tuple[float, float]]], interval: float, hold: int = 2,
) -> list[tuple[float, float]]:
    """Overall (ts, watts): per `interval` bucket, the sum of each plug's mean reading.

    A plug whose reading landed in the next bucket is carried for up to `hold` buckets, so polls that
    straddle a bucket edge do not make the total dip.
    """
    means: list[dict[int, float]] = []
    for points in series:
        buckets: dict[int, list[float]] = {}
        for t, w in points:
            buckets.setdefault(round(t / interval), []).append(w)
        means.append({k: sum(v) / len(v) for k, v in buckets.items()})
    last: list[tuple[int, float] | None] = [None] * len(means)
    totals: list[tuple[float, float]] = []
    for key in sorted({k for m in means for k in m}):
        total = 0.0
        for n, m in enumerate(means):
            if key in m:
                last[n] = (key, m[key])
            if last[n] and key - last[n][0] <= hold:
                total += last[n][1]
        totals.append((key * interval, total))
    return totals


def fill_gaps(
    points: Sequence[tuple[float, float]],
    plug: Sequence[tuple[float, float]],
    profile: Profile,
    gap_seconds: float,
) -> list[tuple[float, float]]:
    """Estimated (ts, watts) points inside each gap of `points` that the plug's own data does not cover.

    The plug's data wins. Otherwise the plug's usual watts for that time of day are shifted so the line
    still meets the last reading before the gap and the first one after it.
    """
    estimates: list[tuple[float, float]] = []
    for (t0, w0), (t1, w1) in zip(points, points[1:], strict=False):
        if t1 - t0 <= max(gap_seconds, MIN_FILL_SECONDS) or any(t0 < t < t1 for t, _ in plug):
            continue
        shift0 = w0 - (_typical(profile, t0) or w0)
        shift1 = w1 - (_typical(profile, t1) or w1)
        step = min(SLOT_SECONDS, (t1 - t0) / 2)  # at least a midpoint, even in a short gap
        t = t0 + step
        while t < t1 - step / 2:
            base = _typical(profile, t)
            if base is not None:
                shift = shift0 + (shift1 - shift0) * (t - t0) / (t1 - t0)
                estimates.append((t, max(0.0, base + shift)))
            t += step
    return estimates
