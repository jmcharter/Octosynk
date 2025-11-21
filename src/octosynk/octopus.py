from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

import requests
import structlog

from octosynk.config import Config, TimeWindow

logger = structlog.stdlib.get_logger(__name__)


class GraphQLError(Exception):
    """Raised for errors returned by GraphQL Queries"""

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

    trimmed = []
    for dispatch in dispatches:
        start_time = dispatch.start_datetime_utc.time()
        end_time = dispatch.end_datetime_utc.time()

        # Check if dispatch is entirely within any off-peak window
        entirely_within = False
        for window in off_peak_windows:
            if start_time >= window.start and end_time <= window.end:
                entirely_within = True
                break

        if entirely_within:
            continue  # Skip this dispatch - it's redundant

        # Check if dispatch needs trimming at the start
        new_start = dispatch.start_datetime_utc
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
            logger.exception("Request timed out")
            raise GraphQLError("Request timed out")
        except requests.HTTPError as e:
            logger.exception()
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
