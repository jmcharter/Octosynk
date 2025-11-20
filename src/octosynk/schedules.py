from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import NamedTuple
import structlog


from octosynk.config import Config, TimeWindow

logger = structlog.stdlib.get_logger(__name__)


@dataclass
class ScheduleLine:
    from_datetime_utc: datetime
    power_watts: int
    target_soc: int
    charge: bool


@dataclass
class Schedule:
    slot_1: ScheduleLine
    slot_2: ScheduleLine
    slot_3: ScheduleLine
    slot_4: ScheduleLine
    slot_5: ScheduleLine
    slot_6: ScheduleLine

    def __str__(self) -> str:
        lines = ["Schedule:"]
        for i in range(1, 7):
            slot = getattr(self, f"slot_{i}")
            lines.append(
                f"  Slot {i}: {slot.from_datetime_utc.strftime('%H:%M')} | "
                f"{'Charge' if slot.charge else 'Discharge'} | "
                f"{slot.power_watts}W | "
                f"Target: {slot.target_soc}%"
            )
        return "\n".join(lines)


def today_at_utc(time_of_day: time) -> datetime:
    """Return a datetime representing today at the given time"""
    return datetime.combine(datetime.now(tz=timezone.utc), time_of_day)


class Transition(NamedTuple):
    time_utc: time
    off_peak: bool


def off_peak_range_to_transitions(windows: list[TimeWindow]) -> list[Transition]:
    """Convert TimeWindows to Transitions for schedule generation."""
    MIDNIGHT = time(0)
    transitions: list[Transition] = []

    for window in windows:
        # For all-day off-peak, window covers most of day (00:00 to 23:30)
        if window.start == MIDNIGHT and window.end == time(23, 30):
            # All-day off-peak special case - both transitions are True
            transitions.append(Transition(window.start, True))
            transitions.append(Transition(window.end, True))
        else:
            # Normal case: window start = charging begins
            transitions.append(Transition(window.start, True))
            # Only add end transition if it's not midnight (to avoid conflicts)
            if window.end != MIDNIGHT:
                transitions.append(Transition(window.end, False))

    # Always start from midnight if not already present
    if not any(t.time_utc == MIDNIGHT for t in transitions):
        transitions.append(Transition(MIDNIGHT, False))

    return transitions


def pad_transitions(transitions: list[Transition]) -> list[Transition]:
    """Pad transitions to return exactly six

    Example:
    Input transitions [Transition(time(0,0),True), Transition(time(5,30), False), Transition(time(23,30), True)]
    Output transitions [
        Transition(time(0, 0), True),    # Original: off-peak starts at midnight
        Transition(time(0, 30), True),   # Padding: still off-peak
        Transition(time(1, 0), True),    # Padding: still off-peak
        Transition(time(1, 30), True),   # Padding: still off-peak
        Transition(time(5, 30), False),  # Original: off-peak ends
        Transition(time(23, 30), True)   # Original: off-peak starts again
    ]

    """
    if len(transitions) >= 6:
        logger.error("More than 6 transitions", transitions_qty=len(transitions))
        raise ValueError("More than 6 transitions")
    all_times = [time(h, m) for h in range(24) for m in [0, 30]]
    used_times = [t.time_utc for t in transitions]
    available_times = [t for t in all_times if t not in used_times]

    padded_transitions = [t for t in transitions]
    for padding_time in available_times:
        if len(padded_transitions) > 5:
            break
        state = False  # default to on-peak
        for t in transitions:
            if t.time_utc <= padding_time:
                state = t.off_peak
        padded_transitions.append(Transition(padding_time, off_peak=state))
    return sorted(padded_transitions, key=lambda x: x.time_utc)


def new_schedule(config: Config, dispatch_transitions: list[Transition] | None = None) -> Schedule:
    # Schedules must start from no earlier than midnight, therefore if we have
    # an off-peak range that spans two days, e.g 23:30 to 05:30 then we must
    # start the schedule from midnight and start the final schedule from the
    # start of the first day up to midnight.
    # e.g
    # Slot 1 = 00:00 - 05:30
    # ...
    # Slot 6 = 23:30 - 00:00

    transitions = off_peak_range_to_transitions(config.off_peak_windows)
    if dispatch_transitions:
        transitions = transitions + dispatch_transitions
    transitions = sorted(transitions, key=lambda t: t.time_utc)
    transitions = pad_transitions(transitions)
    schedule_lines = [
        ScheduleLine(
            today_at_utc(transition.time_utc),
            config.max_power_watts,
            target_soc=config.soc_max if transition.off_peak else config.soc_min,
            charge=transition.off_peak,
        )
        for transition in transitions
    ]
    if len(schedule_lines) != 6:
        logger.error("Incorrect number of schedule lines generated", schedule_lines_qty=len(schedule_lines))
        raise ValueError("Incorrect number of schedule lines generated")
    return Schedule(*schedule_lines)
