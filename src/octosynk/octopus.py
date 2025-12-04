from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

import requests
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from octosynk.config import Config, TimeWindow

logger = structlog.stdlib.get_logger(__name__)


class GraphQLError(Exception):
    """Raised for errors returned by GraphQL Queries"""

    pass


class RetryableGraphQLError(GraphQLError):
    """Raised for transient errors that should be retried"""

    pass


class AuthenticationError(GraphQLError):
    """Raised when authentication fails"""

    pass


@dataclass
class Dispatch:
    start_datetime_utc: datetime
    end_datetime_utc: datetime


def merge_dispatches(dispatches: list[Dispatch]) -> list[Dispatch]:
    """Merge dispatches with overlapping times into a single Dispatch

    Returns a sorted list of Dispatches
    """
    if not dispatches:
        return []
    sorted_dispatches = sorted(dispatches, key=lambda d: d.start_datetime_utc)
    merged_dispatches: list[Dispatch] = []
    current = sorted_dispatches[0]
    for next_dispatch in sorted_dispatches[1:]:
        if current.end_datetime_utc >= next_dispatch.start_datetime_utc:
            current = Dispatch(
                current.start_datetime_utc,
                end_datetime_utc=max(current.end_datetime_utc, next_dispatch.end_datetime_utc),
            )
        else:
            merged_dispatches.append(current)
            current = next_dispatch
    # Add the final dispatch
    merged_dispatches.append(current)

    return merged_dispatches


def trim_dispatches(dispatches: list[Dispatch], off_peak_windows: list[TimeWindow]) -> list[Dispatch]:
    """Trim dispatches to remove portions that overlap with off-peak windows.

    Keeps only the parts of dispatches that fall outside the off-peak windows,
    since the base schedule already handles charging during off-peak.
    """
    if not dispatches:
        return []

    from datetime import time as time_class

    trimmed = []
    for dispatch in dispatches:
        start_time = dispatch.start_datetime_utc.time()
        end_time = dispatch.end_datetime_utc.time()

        # Determine if dispatch crosses midnight
        dispatch_crosses_midnight = start_time > end_time

        # Check if dispatch is entirely within any off-peak window
        entirely_within = False

        if dispatch_crosses_midnight:
            # For a midnight-crossing dispatch to be entirely within off-peak windows,
            # both the before-midnight and after-midnight portions must be covered by windows
            before_midnight_covered = False
            after_midnight_covered = False

            for window in off_peak_windows:
                # Check if this window covers from start_time to midnight
                # Window like TimeWindow(23:30, 00:00) with end=00:00 means "to midnight"
                # So we check: window.start <= start_time AND window.end == 00:00
                if window.start <= start_time and window.end == time_class(0, 0):
                    before_midnight_covered = True

                # Check if this window covers from midnight to end_time
                # This requires: window.start == 00:00 AND window.end >= end_time
                if window.start == time_class(0, 0) and window.end >= end_time:
                    after_midnight_covered = True

            entirely_within = before_midnight_covered and after_midnight_covered
        else:
            # Dispatch doesn't cross midnight - use simple time comparison
            for window in off_peak_windows:
                if start_time >= window.start and end_time <= window.end:
                    entirely_within = True
                    break

        if entirely_within:
            continue  # Skip this dispatch - it's redundant

        # Check if dispatch needs trimming at the start
        new_start = dispatch.start_datetime_utc
        if not dispatch_crosses_midnight:
            # Only apply trimming logic for non-midnight-crossing dispatches
            # (midnight-crossing dispatch trimming would require more complex logic)
            for window in off_peak_windows:
                # If dispatch starts during off-peak but ends after it
                if start_time >= window.start and start_time < window.end and end_time > window.end:
                    # Trim start to window end
                    new_start = dispatch.start_datetime_utc.replace(
                        hour=window.end.hour, minute=window.end.minute, second=0, microsecond=0
                    )
                    break

        if new_start < dispatch.end_datetime_utc:
            trimmed.append(Dispatch(new_start, dispatch.end_datetime_utc))

    return trimmed


def authentication_required(method: Callable):
    @wraps(method)
    def _impl(self, *args, **kwargs):
        if not self.auth_token:
            logger.error("Authentication required. No auth token found")
            raise AuthenticationError("Authentication required. No auth token found")
        return method(self, *args, **kwargs)

    return _impl


class GraphQLClient:
    base_url: str
    api_key: str
    auth_token: str | None

    def __init__(self, config: Config):
        if not config.octopus_api_key:
            raise ValueError("Octopus API key is required")
        self.base_url = config.octopus_api_url
        self.api_key = config.octopus_api_key
        self.auth_token = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((RetryableGraphQLError, requests.ConnectionError)),
        reraise=True,
    )
    def get_query(self, query_str: str, variables: dict[str, Any], auth_token: str | None = None) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
        }
        if auth_token:
            headers["Authorization"] = auth_token
        try:
            res = requests.post(
                self.base_url,
                json={"query": query_str, "variables": variables},
                headers=headers,
                timeout=30,
            )

            res.raise_for_status()
            response_data = res.json()
            if "errors" in response_data:
                errors_data = response_data["errors"]
                errors = [
                    {
                        "message": err.get("message", "Unknown error"),
                        "code": err.get("extensions", {}).get("errorCode", None),
                    }
                    for err in errors_data
                ]
                for error in errors:
                    if error.get("code") == "KT-CT-1124":
                        logger.error("Authentication failed", error_message=error.get("message"))
                        raise AuthenticationError(f"Authentication failed: {error.get("message")}")
                logger.error("GraphQL Errors", errors=errors)
                raise GraphQLError(f"GraphQL Errors: {"; ".join([err.get("message","") for err in errors])}")

            return response_data
        except requests.Timeout:
            logger.warning("Request timed out, will retry")
            raise RetryableGraphQLError("Request timed out")
        except requests.HTTPError as e:
            # Retry on 5xx server errors, but not on 4xx client errors
            if e.response.status_code >= 500:
                logger.warning("Server error, will retry", status_code=e.response.status_code)
                raise RetryableGraphQLError(f"HTTP server error: {e.response.status_code}")
            else:
                logger.error("HTTP client error", status_code=e.response.status_code)
                raise GraphQLError(f"HTTP error: {e.response.status_code}")

    def authenticate(self):
        query = """
        mutation ObtainKrakenToken($input: ObtainJSONWebTokenInput!) {
              obtainKrakenToken(input: $input) {
                token
                payload
                refreshToken
                refreshExpiresIn
              }
            }
        """
        variables = {"input": {"APIKey": self.api_key}}
        data = self.get_query(query, variables)
        auth_token = data.get("data", {}).get("obtainKrakenToken", {}).get("token", None)
        if not auth_token:
            logger.error("Failed to acquire auth token")
            raise AuthenticationError("Failed to acquire auth token")
        self.auth_token = auth_token

    @authentication_required
    def query_devices(self, account_number: str) -> list[dict[str, Any]]:
        """Query devices for an account and return id, name, and deviceType"""
        query = """
        query Devices($accountNumber: String!) {
          devices(accountNumber: $accountNumber) {
            id
            name
            deviceType
          }
        }
        """
        variables = {"accountNumber": account_number}
        data = self.get_query(query, variables, self.auth_token)
        devices_data = data.get("data", {}).get("devices", [])
        return devices_data

    @authentication_required
    def query_dispatches(self, device_id: str) -> list[Dispatch]:
        query = """
        query FlexPlannedDispatches($deviceId: String!) {
          flexPlannedDispatches(deviceId: $deviceId) {
            start
            end
            type
            energyAddedKwh
          }
        }
        """
        variables = {
            "deviceId": device_id,
        }
        data = self.get_query(query, variables, self.auth_token)
        dispatches_data = data.get("data", {}).get("flexPlannedDispatches", [])
        return [
            Dispatch(
                start_datetime_utc=datetime.fromisoformat(dispatch.get("start")).astimezone(timezone.utc),
                end_datetime_utc=datetime.fromisoformat(dispatch.get("end")).astimezone(timezone.utc),
            )
            for dispatch in dispatches_data
        ]
