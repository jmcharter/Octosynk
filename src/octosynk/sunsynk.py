from dataclasses import dataclass, field
from datetime import time
from enum import IntEnum
from typing import Any, Literal
from urllib.parse import urljoin

import requests
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from octosynk.auth import Authenticator, SunsynkAPIError, RetryableSunsynkError
from octosynk.config import Config

logger = structlog.stdlib.get_logger(__name__)


class SysWorkMode(IntEnum):
    SellingFirst = 0
    ZeroExportLimitLoad = 1
    LimitedToHome = 2


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

    def to_dict(self, slot_num: int) -> dict[str, Any]:
        """Convert to API format (camelCase) for a specific slot number"""
        return {
            f"sellTime{slot_num}": self.start_time.strftime("%H:%M"),
            f"sellTime{slot_num}Pac": str(self.power_watts),
            f"cap{slot_num}": str(self.target_soc),
            f"time{slot_num}On": "1" if self.enabled else "0",  # Note: capital 'O' in On, values "0"/"1"
        }

    def __str__(self) -> str:
        status = "Enabled" if self.enabled else "Disabled"
        return f"{self.start_time.strftime('%H:%M')} → {self.power_watts:,}W to {self.target_soc}% SOC ({status})"


@dataclass
class SunsynkInverterRead:
    """Complete inverter charge configuration"""

    charge_slots: list[InverterChargeSlot]
    system_work_mode: SysWorkMode = field(default=SysWorkMode.LimitedToHome)

    @classmethod
    def from_dict(cls, data: dict) -> "SunsynkInverterRead":
        """Create from API response"""
        slots = [InverterChargeSlot.from_dict(i, data) for i in range(1, 7)]
        system_work_mode = SysWorkMode(int(data.get("sysWorkMode", SysWorkMode.LimitedToHome)))
        return cls(charge_slots=slots, system_work_mode=system_work_mode)

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


@dataclass
class SunsynkInverterWrite:
    """Complete inverter charge configuration for writing to API"""

    charge_slots: list[InverterChargeSlot]
    system_work_mode: SysWorkMode = field(default=SysWorkMode.LimitedToHome)

    def __post_init__(self):
        """Validate the configuration"""
        if len(self.charge_slots) != 6:
            raise ValueError(f"Must have exactly 6 charge slots, got {len(self.charge_slots)}")

        for i, slot in enumerate(self.charge_slots, 1):
            if not 0 <= slot.target_soc <= 100:
                raise ValueError(f"Slot {i}: target_soc must be 0-100, got {slot.target_soc}")
            if slot.power_watts < 0:
                raise ValueError(f"Slot {i}: power_watts must be positive, got {slot.power_watts}")

    @classmethod
    def from_read(cls, read_config: SunsynkInverterRead) -> "SunsynkInverterWrite":
        """Create a write config from a read config"""
        return cls(
            charge_slots=read_config.charge_slots.copy(),
            system_work_mode=read_config.system_work_mode,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to API format (camelCase) for writing"""
        result = {
            "sysWorkMode": str(self.system_work_mode.value),
        }

        if self.charge_slots is not None:
            for i, slot in enumerate(self.charge_slots, 1):
                result.update(slot.to_dict(i))

        return result

    def update_slot(self, slot_num: int, slot: InverterChargeSlot) -> "SunsynkInverterWrite":
        """
        Update a single slot and return self for chaining.
        slot_num is 1-indexed (1-6).
        """
        if not 1 <= slot_num <= 6:
            raise ValueError(f"slot_num must be 1-6, got {slot_num}")

        if self.charge_slots is None:
            # Create empty slots if not initialized
            self.charge_slots = [InverterChargeSlot(time(0, 0), 0, 0, False) for _ in range(6)]

        self.charge_slots[slot_num - 1] = slot
        return self

    def __str__(self) -> str:
        """Pretty print the charge configuration"""
        lines = ["Inverter Charge Configuration (Write)", "=" * 40]

        for i, slot in enumerate(self.charge_slots, 1):
            lines.append(f"Slot {i}: {slot}")

        lines.append("=" * 40)
        active_count = sum(1 for slot in self.charge_slots if slot.enabled)
        lines.append(f"Active slots: {active_count}/6")

        return "\n".join(lines)


def create_charge_config(
    slot_1: InverterChargeSlot,
    slot_2: InverterChargeSlot,
    slot_3: InverterChargeSlot,
    slot_4: InverterChargeSlot,
    slot_5: InverterChargeSlot,
    slot_6: InverterChargeSlot,
) -> SunsynkInverterWrite:
    """Helper to create a write configuration with all 6 slots"""
    return SunsynkInverterWrite(charge_slots=[slot_1, slot_2, slot_3, slot_4, slot_5, slot_6])


def schedule_to_inverter_write(schedule: "Schedule") -> SunsynkInverterWrite:
    """Convert a Schedule to a SunsynkInverterWrite configuration"""

    charge_slots = [
        InverterChargeSlot(
            start_time=getattr(schedule, f"slot_{i}").from_datetime_utc.time(),
            power_watts=getattr(schedule, f"slot_{i}").power_watts,
            target_soc=getattr(schedule, f"slot_{i}").target_soc,
            enabled=getattr(schedule, f"slot_{i}").charge,
        )
        for i in range(1, 7)
    ]

    return SunsynkInverterWrite(charge_slots=charge_slots)


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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RetryableSunsynkError, requests.ConnectionError)),
        reraise=True,
    )
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
                response = requests.request(method=method, url=url, headers=headers, timeout=self._timeout, **kwargs)
                if response.status_code == 401 and attempt == 0:
                    self._authenticator.clear_token()  # Clear token so a new one will be generated
                    token = self._authenticator.get_token()
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                response.raise_for_status()
                return response
            except requests.Timeout:
                logger.warning("Request timeout, will retry")
                raise RetryableSunsynkError("Request timeout")
            except requests.HTTPError as e:
                # Retry on 5xx server errors
                if e.response.status_code >= 500:
                    logger.warning("Server error, will retry", status_code=e.response.status_code)
                    raise RetryableSunsynkError(f"HTTP server error: {e.response.status_code}")
                else:
                    logger.error("Error accessing Sunsynk API", status_code=e.response.status_code)
                    raise SunsynkAPIError(f"Error accessing Sunsynk API. Status {e.response.status_code}")
        raise SunsynkAPIError("Failed after retry")

    def get_inverter_data(self) -> SunsynkInverterRead:
        response = self._request("GET", "common/setting/2406164025/read")
        response_json = response.json()
        data = response_json.get("data")
        if not data:
            logger.info("No inverter data found for device", device_id=self.device_id)
        return SunsynkInverterRead.from_dict(data)

    def update_inverter_schedule(self, data: SunsynkInverterWrite) -> requests.Response:
        post_data = data.to_dict()
        logger.debug("Sending update request to inverter", data=post_data)
        response = self._request("POST", "common/setting/2406164025/set", json=post_data)
        return response
