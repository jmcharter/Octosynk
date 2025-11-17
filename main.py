from dataclasses import dataclass
from datetime import datetime
from typing import Any
import requests
import os
import structlog

ACCOUNT_NUMBER = "A-EEB11DF5"
DEVICE_ID = os.environ.get("DEVICE_ID")

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


@dataclass
class Config:
    auth_token: str
    device_id: str
    graphql_base_url: str


class GraphQLClient:
    def __init__(self, config: Config):
        self.base_url = config.graphql_base_url
        self.auth_token = config.auth_token

    def get_query(self, query_str: str, variables: dict[str, Any]) -> requests.Response | None:
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.auth_token,
        }
        try:
            res = requests.post(
                self.base_url,
                json={"query": query_str, "variables": variables},
                headers=headers,
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
        res = self.get_query(query, variables)
        print(res.text)
        if not res:
            logger.error("No data found")
            return []
        data_json = res.json().get("data", {})
        print(data_json)
        dispatches_data = data_json.get("flexPlannedDispatches", [])
        return [
            Dispatch(
                start_datetime_utc=datetime.fromisoformat(dispatch.get("start")),
                end_datetime_utc=datetime.fromisoformat(dispatch.get("end")),
            )
            for dispatch in dispatches_data
        ]


def main():
    config = Config(
        auth_token=os.environ.get("AUTH_TOKEN", ""),
        device_id=os.environ.get("DEVICE_ID", ""),
        graphql_base_url=os.environ.get("GRAPHQL_BASE_URL", "https://api.octopus.energy/v1/graphql/"),
    )
    client = GraphQLClient(config=config)
    dispatches = client.query_dispatches(config.device_id)
    print(dispatches)


if __name__ == "__main__":
    main()
