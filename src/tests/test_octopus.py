from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from octosynk.octopus import AuthenticationError, Dispatch


class TestAuthenticate:
    @patch("octosynk.octopus.requests.post")
    def test_extracts_token_from_response(self, mock_post, client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "obtainKrakenToken": {
                    "token": "abc123",
                    "payload": "test-payload",
                    "refreshToken": "refresh-abc123",
                    "refreshExpiresIn": 3600,
                }
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client.authenticate()

        assert client.auth_token == "abc123"


class TestQueryDispatches:
    @patch("octosynk.octopus.requests.post")
    def test_handles_empty_dispatches(self, mock_post, client):
        client.auth_token = "token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": {"flexPlannedDispatches": []}}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = client.query_dispatches("device-123")

        assert result == []

    @patch("octosynk.octopus.requests.post")
    def test_parses_dispatch_datetimes(self, mock_post, client):
        client.auth_token = "token"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "flexPlannedDispatches": [
                    {
                        "start": "2020-01-01T00:00:00.000Z",
                        "end": "2020-01-01T01:00:00.000Z",
                        "type": "SMART",
                        "energyAddedKwh": "1.0",
                    },
                    {
                        "start": "2020-01-01T02:00:00.000Z",
                        "end": "2020-01-01T03:00:00.000Z",
                        "type": "SMART",
                        "energyAddedKwh": "2.5",
                    },
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        result = client.query_dispatches("device-123")

        assert len(result) == 2
        assert isinstance(result[0], Dispatch)
        assert result[0].start_datetime_utc == datetime.fromisoformat("2020-01-01T00:00:00.000Z")
        assert result[1].end_datetime_utc == datetime.fromisoformat("2020-01-01T03:00:00.000Z")

    def test_requires_authentication(self, client):
        with pytest.raises(AuthenticationError):
            client.query_dispatches("device-123")
