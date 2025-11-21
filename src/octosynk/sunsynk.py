from dataclasses import dataclass
from datetime import time
from typing import Any, Literal
from urllib.parse import urljoin

import requests
import structlog

from octosynk.auth import Authenticator, SunsynkAPIError
from octosynk.config import Config

logger = structlog.stdlib.get_logger(__name__)

# "sellTime1": "00:00",
# "time1on": "true",
# "cap1": "100",
# "sellTime1Pac": "8000",


@dataclass
class InverterChargeSlot:
    """Represents a single charge time slot configuration"""

    start_time: time  # When this slot starts (e.g., "00:00" -> time(0, 0))
    power_watts: int  # Maximum power for this slot (e.g., 8000)
    target_soc: int  # Target state of charge percentage (e.g., 100)
    enabled: bool  # Whether this slot is active (from time1On, time2On, etc.)

    @classmethod
    def from_dict(cls, slot_num: int, data: dict) -> "InverterChargeSlot":
        """Create a charge slot from the API response data"""
        # Parse time string "HH:MM"
        time_str = data[f"sellTime{slot_num}"]
        hour, minute = map(int, time_str.split(":"))

        return cls(
            start_time=time(hour, minute),
            power_watts=int(data[f"sellTime{slot_num}Pac"]),
            target_soc=int(data[f"cap{slot_num}"]),
            enabled=data[f"time{slot_num}On"] == "1",
        )

    def __str__(self) -> str:
        status = "Enabled" if self.enabled else "Disabled"
        return f"{self.start_time.strftime('%H:%M')} → {self.power_watts:,}W to {self.target_soc}% SOC ({status})"


@dataclass
class SunsynkInverterRead:
    """Complete inverter charge configuration"""

    charge_slots: list[InverterChargeSlot]

    @classmethod
    def from_dict(cls, data: dict) -> "SunsynkInverterRead":
        """Create from API response"""
        slots = [InverterChargeSlot.from_dict(i, data) for i in range(1, 7)]
        return cls(charge_slots=slots)

    @property
    def active_slots(self) -> list[InverterChargeSlot]:
        """Get only the enabled charge slots"""
        return [slot for slot in self.charge_slots if slot.enabled]

    def __str__(self) -> str:
        """Pretty print the charge configuration"""
        lines = ["Inverter Read", "=" * 40]

        for i, slot in enumerate(self.charge_slots, 1):
            lines.append(f"Slot {i}: {slot}")

        lines.append("=" * 40)
        lines.append(f"Enabled slots: {len(self.active_slots)}/6")

        return "\n".join(lines)


class Client:
    base_url: str
    token: str | None

    def __init__(self, config: Config, timeout: float = 30):
        self.base_url = config.sunsynk_api_url
        self.auth_url = config.sunsynk_auth_url
        self.device_id = config.sunsynk_device_id
        self._timeout = timeout
        self._authenticator = Authenticator(
            config.sunsynk_username,
            config.sunsynk_password,
            timeout=timeout,
        )

    def authenticate(self):
        """Authenticate with the Sunsynk API."""
        self._authenticator.authenticate()

    def _request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        *,
        base_url: str | None = None,
        **kwargs,
    ) -> requests.Response:

        url = urljoin((base_url or self.base_url).rstrip("/") + "/", endpoint.lstrip())
        token = self._authenticator.get_token()
        headers = kwargs.pop("headers", {}).copy()
        headers["Authorization"] = f"Bearer {token}"
        for attempt in range(2):
            try:
                response = requests.request(method=method, url=url, headers=headers, timeout=self._timeout)
                if response.status_code == 401 and attempt == 0:
                    self._authenticator.clear_token()  # Clear token so a new one will be generated
                    continue
                response.raise_for_status()
                return response
            except requests.HTTPError as e:
                logger.exception("Error accessing Sunsynk API", status_code=e.response.status_code)
                raise SunsynkAPIError(f"Error accessing Sunsynk API. Status {e.response.status_code}")
        raise SunsynkAPIError("Failed after retry")

    def get_inverter_data(self) -> SunsynkInverterRead:
        response = self._request("GET", "common/setting/2406164025/read")
        response_json = response.json()
        data = response_json.get("data")
        if not data:
            logger.info("No inverter data found for device", device_id=self.device_id)
        return SunsynkInverterRead.from_dict(data)
