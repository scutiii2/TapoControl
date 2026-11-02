from datetime import datetime

from core.profile import MIN_READINGS, SLOT_SECONDS, fill_gaps, slot_key

MON = datetime(2026, 11, 2, 9, 0).timestamp()  # a Monday
SAT = datetime(2026, 11, 7, 9, 0).timestamp()


def flat_profile(ts, mean, n=MIN_READINGS):
    return {slot_key(ts + i * SLOT_SECONDS): (mean, n) for i in range(-1, 60)}


def test_slot_key_splits_weekday_and_weekend():
    assert slot_key(MON) == (0, 108)  # 09:00 / 5 min
    assert slot_key(SAT) == (1, 108)


def test_gap_follows_usual_day_and_meets_both_edges():
    profile = flat_profile(MON, 60.0)
    points = [(MON, 70.0), (MON + 3600, 50.0)]  # 10 W above usual before the gap, 10 W below after
    estimates = fill_gaps(points, [], profile, 12.5)
    assert estimates and all(MON < t < MON + 3600 for t, _ in estimates)
    first, last = estimates[0][1], estimates[-1][1]
    assert 65 < first < 70 and 50 < last < 55  # shift fades from +10 to -10 across the gap


def test_no_estimates_without_profile_or_when_plug_covers_gap_or_gap_is_short():
    points = [(MON, 70.0), (MON + 3600, 50.0)]
    assert fill_gaps(points, [], {}, 12.5) == []
    assert fill_gaps(points, [], flat_profile(MON, 60.0, n=MIN_READINGS - 1), 12.5) == []
    assert fill_gaps(points, [(MON + 1800, 55.0)], flat_profile(MON, 60.0), 12.5) == []
    assert fill_gaps([(MON, 70.0), (MON + 20, 50.0)], [], flat_profile(MON, 60.0), 12.5) == []


def test_estimates_never_go_negative():
    estimates = fill_gaps([(MON, 0.0), (MON + 3600, 0.0)], [], flat_profile(MON, 100.0), 12.5)
    assert estimates and min(w for _, w in estimates) >= 0
