from datetime import time
import os
import structlog

from octosynk.config import Config
from octosynk import octopus


logger = structlog.stdlib.get_logger(__name__)


def run():
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

    config = Config(
        octopus_api_key=octopus_api_key,
        device_id=device_id,
        graphql_base_url=os.environ.get("GRAPHQL_BASE_URL", "https://api.octopus.energy/v1/graphql/"),
        off_peak_start_time=off_peak_start_time,
        off_peak_end_time=off_peak_end_time,
    )
    client = octopus.GraphQLClient(config=config)
    client.authenticate()
    dispatches = client.query_dispatches(config.device_id)
    print(dispatches)


if __name__ == "__main__":
    run()
