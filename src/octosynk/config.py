from dataclasses import dataclass
from datetime import time


@dataclass
class Config:
    octopus_api_key: str
    device_id: str
    graphql_base_url: str
    off_peak_start_time: time
    off_peak_end_time: time
    max_power_watts: int = 8000
    soc_max: int = 100
    soc_min: int = 7
