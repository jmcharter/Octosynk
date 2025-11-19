from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from octosynk.octopus import AuthenticationError, Dispatch, merge_dispatches


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


@pytest.mark.parametrize(
    "input_dispatches,expected_output",
    [
        # Test case 1: Two overlapping dispatches
        (
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 12, 0)),
                Dispatch(datetime(2024, 1, 1, 11, 0), datetime(2024, 1, 1, 13, 0)),
            ],
            [Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 13, 0))],
        ),
        # Test case 2: Two non-overlapping dispatches
        (
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0)),
                Dispatch(datetime(2024, 1, 1, 12, 0), datetime(2024, 1, 1, 13, 0)),
            ],
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0)),
                Dispatch(datetime(2024, 1, 1, 12, 0), datetime(2024, 1, 1, 13, 0)),
            ],
        ),
        # Test case 3: Three dispatches, all overlapping
        (
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 12, 0)),
                Dispatch(datetime(2024, 1, 1, 11, 0), datetime(2024, 1, 1, 13, 0)),
                Dispatch(datetime(2024, 1, 1, 12, 30), datetime(2024, 1, 1, 14, 0)),
            ],
            [Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 14, 0))],
        ),
        # Test case 4: One dispatch contained entirely within another
        (
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 14, 0)),
                Dispatch(datetime(2024, 1, 1, 11, 0), datetime(2024, 1, 1, 12, 0)),
            ],
            [Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 14, 0))],
        ),
        # Test case 5: Multiple groups of overlapping dispatches
        (
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0)),
                Dispatch(datetime(2024, 1, 1, 10, 30), datetime(2024, 1, 1, 11, 30)),
                Dispatch(datetime(2024, 1, 1, 14, 0), datetime(2024, 1, 1, 15, 0)),
                Dispatch(datetime(2024, 1, 1, 14, 30), datetime(2024, 1, 1, 16, 0)),
            ],
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 30)),
                Dispatch(datetime(2024, 1, 1, 14, 0), datetime(2024, 1, 1, 16, 0)),
            ],
        ),
        # Test case 6: Dispatches that touch exactly (end time == start time)
        (
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0)),
                Dispatch(datetime(2024, 1, 1, 11, 0), datetime(2024, 1, 1, 12, 0)),
            ],
            [Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 12, 0))],
        ),
        # Test case 7: Single dispatch
        (
            [Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0))],
            [Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0))],
        ),
        # Test case 8: Empty list
        (
            [],
            [],
        ),
        # Test case 9: Unsorted input dispatches
        (
            [
                Dispatch(datetime(2024, 1, 1, 14, 0), datetime(2024, 1, 1, 15, 0)),
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 11, 0)),
                Dispatch(datetime(2024, 1, 1, 10, 30), datetime(2024, 1, 1, 12, 0)),
            ],
            [
                Dispatch(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 12, 0)),
                Dispatch(datetime(2024, 1, 1, 14, 0), datetime(2024, 1, 1, 15, 0)),
            ],
        ),
    ],
    ids=[
        "two_overlapping",
        "two_non_overlapping",
        "three_all_overlapping",
        "one_contained_in_another",
        "multiple_groups",
        "exact_touching_times",
        "single_dispatch",
        "empty_list",
        "unsorted_input",
    ],
)
def test_merge_dispatches(input_dispatches, expected_output):
    result = merge_dispatches(input_dispatches)
    assert result == expected_output
