from datetime import time
import logging
import os
import sys
import requests
from octosynk.schedules import Transition, new_schedule
from octosynk.sunsynk import Client as SunsynkClient
import structlog

from octosynk.config import Config
from octosynk import octopus


logger = structlog.stdlib.get_logger(__name__)


def ping_healthcheck(uuid: str | None, endpoint: str = ""):
    """Ping healthchecks.io with optional endpoint (/start, /fail, or empty for success)"""
    if not uuid:
        return

    url = f"https://hc-ping.com/{uuid}{endpoint}"
    try:
        requests.get(url, timeout=10)
        logger.debug("Healthcheck ping sent", endpoint=endpoint)
    except Exception as e:
        # Don't fail the application if healthcheck ping fails
        logger.warning("Failed to ping healthcheck", error=str(e), endpoint=endpoint)


def get_config() -> Config | None:
    def get_required_env(key: str, default: str | None = None) -> str:
        value = os.environ.get(key)
        if not value:
            if default:
                return default
            logger.error(f"{key} environment variable is required")
            raise ValueError(f"{key} is required")
        return value

    def get_time_env(key: str, default: str) -> time:
        value = os.environ.get(key, default)
        try:
            return time.fromisoformat(value)
        except ValueError:
            logger.error(f"{key} must be of format: hh:mm, e.g 14:00")
            raise

    try:
        return Config(
            octopus_api_key=get_required_env("OCTOPUS_API_KEY"),
            sunsynk_api_url=get_required_env("SUNSYNK_API_URL", "https://api.sunsynk.net/api/v1/"),
            sunsynk_auth_url=get_required_env("SUNSYNK_AUTH_URL", "https://api.sunsynk.net/oauth/"),
            sunsynk_username=get_required_env("SUNSYNK_USERNAME"),
            sunsynk_password=get_required_env("SUNSYNK_PASSWORD"),
            sunsynk_device_id=get_required_env("SUNSYNK_DEVICE_ID"),
            octopus_device_id=get_required_env("OCTOPUS_DEVICE_ID"),
            octopus_api_url=get_required_env("OCTOPUS_API_URL", "https://api.octopus.energy/v1/graphql/"),
            off_peak_start_time=get_time_env("OFF_PEAK_START_TIME", "23:30"),
            off_peak_end_time=get_time_env("OFF_PEAK_END_TIME", "05:30"),
            healthcheck_uuid=get_required_env("HEALTHCHECK_UUID", None),
            log_level=get_required_env("LOG_LEVEL", "INFO"),
        )
    except ValueError:
        return None


def dispatches_to_transitions(dispatches: list[octopus.Dispatch]) -> list[Transition]:
    transitions: list[Transition] = []
    for dispatch in dispatches:
        if dispatch.start_datetime_utc > dispatch.end_datetime_utc:
            raise ValueError("Dispatch start time should never be later than dispatch end time")
        transitions.extend(
            [
                Transition(time_utc=dispatch.start_datetime_utc.time(), off_peak=True),
                Transition(time_utc=dispatch.end_datetime_utc.time(), off_peak=False),
            ]
        )

    return transitions


def run():
    config = get_config()
    if not config:
        return

    # Configure logging level
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, config.log_level.upper(), logging.INFO)
        )
    )

    ping_healthcheck(config.healthcheck_uuid, "/start")

    try:
        logger.info("Starting Octosynk run")

        # Fetch and process Octopus dispatches
        client = octopus.GraphQLClient(config=config)
        client.authenticate()
        dispatches = client.query_dispatches(config.octopus_device_id)
        dispatches = octopus.merge_dispatches(dispatches)
        dispatches = octopus.trim_dispatches(dispatches, config.off_peak_windows)

        # Generate schedule from dispatches
        dispatch_transitions = dispatches_to_transitions(dispatches)
        schedule = new_schedule(config, dispatch_transitions)
        active_slots = sum(1 for i in range(1, 7) if getattr(schedule, f"slot_{i}").charge)
        logger.info("Generated schedule", active_slots=active_slots)

        # Update Sunsynk inverter
        from octosynk.sunsynk import schedule_to_inverter_write

        sun_client = SunsynkClient(config)
        inverter_write = schedule_to_inverter_write(schedule)
        res = sun_client.update_inverter_schedule(inverter_write)

        if res.status_code == 200:
            logger.info("Successfully updated inverter schedule")
        else:
            logger.warning("Unexpected response from inverter", status=res.status_code)

        ping_healthcheck(config.healthcheck_uuid)

    except Exception as e:
        logger.exception("Octosynk run failed")
        ping_healthcheck(config.healthcheck_uuid, "/fail")
        sys.exit(1)


if __name__ == "__main__":
    run()
