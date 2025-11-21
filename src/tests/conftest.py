from datetime import time

import pytest

from octosynk.config import Config
from octosynk.octopus import GraphQLClient


@pytest.fixture
def config():
    return Config(
        octopus_api_key="wibble-wobble",
        device_id="0000-00-00-0000000",
        octopus_api_url="https://api.wibble.com",
        off_peak_start_time=time(23, 30),
        off_peak_end_time=time(5, 30),
        max_power_watts=8000,
    )


@pytest.fixture
def client(config):
    return GraphQLClient(config)
