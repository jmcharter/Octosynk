from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Callable

import requests
import structlog

from octosynk.config import Config

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
        self.base_url = config.graphql_base_url
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
                start_datetime_utc=datetime.fromisoformat(dispatch.get("start")),
                end_datetime_utc=datetime.fromisoformat(dispatch.get("end")),
            )
            for dispatch in dispatches_data
        ]
