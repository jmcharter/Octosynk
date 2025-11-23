from dataclasses import dataclass
from datetime import time


@dataclass
class TimeWindow:
    start: time
    end: time


@dataclass
class Config:
    octopus_api_key: str
    octopus_device_id: str
    octopus_api_url: str
    sunsynk_auth_url: str
    sunsynk_api_url: str
    sunsynk_username: str
    sunsynk_password: str
    sunsynk_device_id: str
    off_peak_start_time: time
    off_peak_end_time: time
    max_power_watts: int = 8000
    soc_max: int = 100
    soc_min: int = 7
    healthcheck_uuid: str | None = None
    log_level: str = "INFO"
    mqtt_broker: str | None = None
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = "octosynk"

    @property
    def off_peak_windows(self) -> list[TimeWindow]:
        """Convert off-peak range to windows that don't cross midnight.

        Example: 23:30 - 05:30 becomes:
        - [TimeWindow(00:00, 05:30), TimeWindow(23:30, 00:00)]

        Special case: If start == end, returns window covering the entire day (all-day off-peak)
        """
        MIDNIGHT = time(0, 0)

        if self.off_peak_start_time == self.off_peak_end_time:
            # All-day off-peak - return window covering full day
            return [TimeWindow(MIDNIGHT, time(23, 30))]
        elif self.off_peak_start_time > self.off_peak_end_time:
            return [TimeWindow(MIDNIGHT, self.off_peak_end_time), TimeWindow(self.off_peak_start_time, MIDNIGHT)]
        else:
            return [TimeWindow(self.off_peak_start_time, self.off_peak_end_time)]
