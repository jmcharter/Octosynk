from dataclasses import dataclass
from datetime import time
import os
from octosynk.schedules import Schedule, Transition, new_base_schedule
import structlog

from octosynk.config import Config
from octosynk import octopus


logger = structlog.stdlib.get_logger(__name__)


def get_config() -> Config | None:
    octopus_api_key = os.environ.get("OCTOPUS_API_KEY")
    if not octopus_api_key:
        logger.error("OCTOPUS_API_KEY environment variable is required")
        return
    device_id = os.environ.get("DEVICE_ID")
    if not device_id:
        logger.error("DEVICE_ID environment variable is required")
        return
    off_peak_start_time_str = os.environ.get("OFF_PEAK_START_TIME", "23:30")
    if not off_peak_start_time_str:
        logger.error("OFF_PEAK_START_TIME environment variable is required")
        return
    try:
        off_peak_start_time = time.fromisoformat(off_peak_start_time_str)
    except ValueError:
        logger.error("OFF_PEAK_START_TIME must be of format: hh:mm, e.g 14:00")
        return
    off_peak_end_time_str = os.environ.get("OFF_PEAK_END_TIME", "23:30")
    if not off_peak_end_time_str:
        logger.error("OFF_PEAK_END_TIME environment variable is required")
        return
    try:
        off_peak_end_time = time.fromisoformat(off_peak_end_time_str)
    except ValueError:
        logger.error("OFF_PEAK_END_TIME must be of format: hh:mm, e.g 14:00")
        return

    return Config(
        octopus_api_key=octopus_api_key,
        device_id=device_id,
        graphql_base_url=os.environ.get("GRAPHQL_BASE_URL", "https://api.octopus.energy/v1/graphql/"),
        off_peak_start_time=off_peak_start_time,
        off_peak_end_time=off_peak_end_time,
    )


def dispatches_to_transitions(dispatches: list[octopus.Dispatch]) -> list[Transition]:
    transitions: list[Transition] = []
    for dispatch in dispatches:
        if dispatch.start_datetime_utc > dispatch.end_datetime_utc:
            raise ValueError("Dispatch start time should never be later than dispatch end time")
        t1 = Transition(time_utc=dispatch.start_datetime_utc.time(), off_peak=True)
        t2 = Transition(time_utc=dispatch.end_datetime_utc.time(), off_peak=False)

    return transitions


def get_schedule_from_octopus_dispatches(dispatches: list[octopus.Dispatch], config: Config) -> Schedule:
    schedule = new_base_schedule(config)
    return schedule


def run():
    config = get_config()
    if not config:
        return
    client = octopus.GraphQLClient(config=config)
    client.authenticate()
    dispatches = client.query_dispatches(config.device_id)
    dispatches = octopus.merge_dispatches(dispatches)
    dispatches = octopus.trim_dispatches(dispatches, config.off_peak_windows)
    # schedules = get_schedules_from_octopus_dispatches(dispatches, config)
    print(dispatches)


if __name__ == "__main__":
    run()
