from datetime import time

import pytest

from octosynk.config import Config, TimeWindow
from octosynk.schedules import (
    new_base_schedule,
    off_peak_range_to_transitions,
    today_at_utc,
)


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
    config: Config,
):
    config.off_peak_start_time = off_peak_start
    config.off_peak_end_time = off_peak_end
    transitions = off_peak_range_to_transitions(config.off_peak_windows)
    assert transitions is not None
    assert transitions[0].time_utc == time(0)
    assert len(transitions) == 6


@pytest.mark.parametrize(
    "off_peak_start,off_peak_end,expected_times_and_charges",
    [
        # Case 1: Off-peak spans midnight (23:30 to 5:30)
        (
            time(23, 30),
            time(5, 30),
            [
                (time(0, 0), True),  # 00:00 - off-peak (continues from previous day)
                (time(0, 30), True),  # 00:30 - off-peak (padding)
                (time(1, 0), True),  # 01:00 - off-peak (padding)
                (time(1, 30), True),  # 01:30 - off-peak (padding)
                (time(5, 30), False),  # 05:30 - on-peak starts
                (time(23, 30), True),  # 23:30 - off-peak starts
            ],
        ),
        # Case 2: Off-peak within same day (1:00 to 7:00)
        (
            time(1, 0),
            time(7, 0),
            [
                (time(0, 0), False),  # 00:00 - on-peak
                (time(0, 30), False),  # 00:30 - on-peak (padding)
                (time(1, 0), True),  # 01:00 - off-peak starts
                (time(1, 30), True),  # 01:30 - off-peak (padding)
                (time(2, 0), True),  # 02:00 - off-peak (padding)
                (time(7, 0), False),  # 07:00 - on-peak starts
            ],
        ),
        # Case 3: Off-peak at midnight exactly (0:00 to 6:00)
        (
            time(0, 0),
            time(6, 0),
            [
                (time(0, 0), True),  # 00:00 - off-peak starts
                (time(0, 30), True),  # 00:30 - off-peak (padding)
                (time(1, 0), True),  # 01:00 - off-peak (padding)
                (time(1, 30), True),  # 05:00 - off-peak (padding)
                (time(2, 0), True),  # 05:30 - off-peak (padding)
                (time(6, 0), False),  # 06:00 - on-peak starts
            ],
        ),
        # Case 4: Short off-peak period (3:00 to 5:00)
        (
            time(3, 0),
            time(5, 0),
            [
                (time(0, 0), False),  # 00:00 - on-peak
                (time(0, 30), False),  # 00:30 - on-peak (padding)
                (time(1, 0), False),  # 01:00 - on-peak (padding)
                (time(1, 30), False),  # 01:00 - on-peak (padding)
                (time(3, 0), True),  # 03:00 - off-peak starts
                (time(5, 0), False),  # 05:00 - on-peak starts
            ],
        ),
        # Case 5: Edge-case, all day (00:00 - 00:00)
        (
            time(0, 0),
            time(0, 0),
            [
                (time(0, 0), True),  # 00:00 - on-peak
                (time(0, 30), True),  # 00:30 - on-peak (padding)
                (time(1, 0), True),  # 01:00 - on-peak (padding)
                (time(1, 30), True),  # 01:00 - on-peak (padding)
                (time(2, 0), True),  # 03:00 - off-peak starts
                (time(23, 30), True),  # 05:00 - on-peak starts
            ],
        ),
    ],
)
def test_new_base_schedule(
    off_peak_start: time,
    off_peak_end: time,
    expected_times_and_charges: list[tuple[time, bool]],
    config: Config,
):
    """Test that new_base_schedule correctly generates 6 time slots with proper off-peak/on-peak transitions"""
    config.off_peak_start_time = off_peak_start
    config.off_peak_end_time = off_peak_end

    schedule = new_base_schedule(config)

    slots = [
        schedule.slot_1,
        schedule.slot_2,
        schedule.slot_3,
        schedule.slot_4,
        schedule.slot_5,
        schedule.slot_6,
    ]

    # Verify we have exactly 6 slots
    assert len(slots) == 6
    assert all(slot is not None for slot in slots)

    # Check each slot against expected values
    for i, (slot, (expected_time, expected_charge)) in enumerate(zip(slots, expected_times_and_charges), 1):
        # Check time
        assert slot.from_datetime_utc == today_at_utc(
            expected_time
        ), f"Slot {i}: Time mismatch - expected {expected_time}, got {slot.from_datetime_utc.time()}"

        # Check charge state
        assert (
            slot.charge == expected_charge
        ), f"Slot {i}: Charge state mismatch at {expected_time} - expected {expected_charge}, got {slot.charge}"

        # Check power_watts is set correctly
        assert (
            slot.power_watts == config.max_power_watts
        ), f"Slot {i}: Power watts mismatch - expected {config.max_power_watts}, got {slot.power_watts}"

        # Check target_soc matches charge state
        expected_soc = config.soc_max if expected_charge else config.soc_min
        assert (
            slot.target_soc == expected_soc
        ), f"Slot {i}: SOC mismatch at {expected_time} - expected {expected_soc}, got {slot.target_soc}"

    # Verify slots are in chronological order
    for i in range(len(slots) - 1):
        assert (
            slots[i].from_datetime_utc <= slots[i + 1].from_datetime_utc
        ), f"Slots not in chronological order: slot {i+1} at {slots[i].from_datetime_utc.time()} > slot {i+2} at {slots[i+1].from_datetime_utc.time()}"


def test_new_base_schedule_charge_discharge_logic(config: Config):
    """Test that charge/discharge states and SOC targets are set correctly"""
    config.off_peak_start_time = time(2, 0)
    config.off_peak_end_time = time(6, 0)

    schedule = new_base_schedule(config)
    slots = [schedule.slot_1, schedule.slot_2, schedule.slot_3, schedule.slot_4, schedule.slot_5, schedule.slot_6]

    for slot in slots:
        if slot.charge:
            # During off-peak (charging), target should be max SOC
            assert slot.target_soc == config.soc_max, f"Charging slot should target soc_max, got {slot.target_soc}"
        else:
            # During on-peak (not charging), target should be min SOC
            assert slot.target_soc == config.soc_min, f"Non-charging slot should target soc_min, got {slot.target_soc}"
