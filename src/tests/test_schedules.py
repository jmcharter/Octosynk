from datetime import time
from octosynk.config import Config
from octosynk.schedules import new_base_schedule, off_peak_range_to_transitions, Transition
import pytest


@pytest.mark.parametrize(
    "off_peak_start,off_peak_end",
    [
        (time(23, 30), time(5, 30)),
        (time(1, 0), time(7, 0)),
    ],
)
def test_off_peak_range_to_transitions(
    off_peak_start: time,
    off_peak_end: time,
):
    transitions = off_peak_range_to_transitions(off_peak_start, off_peak_end)
    assert transitions is not None
    assert transitions[0].time_utc == time(0)  # Midnight
    assert len(transitions) == 6
