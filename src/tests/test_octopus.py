from datetime import datetime, time, timezone
from unittest.mock import MagicMock, patch

import pytest

from octosynk.config import TimeWindow
from octosynk.octopus import AuthenticationError, Dispatch, merge_dispatches, trim_dispatches


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


@pytest.mark.parametrize(
    "dispatches,off_peak_windows,expected_output,test_description",
    [
        # Test case 1: Midnight-crossing dispatch NOT entirely within off-peak (the bug scenario)
        # Dispatch: 20:00-01:00, Off-peak: 23:30-05:30 (split into [00:00-05:30], [23:30-00:00])
        # The dispatch from 20:00-23:30 is during peak time and should create a transition
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 1, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(5, 30)), TimeWindow(time(23, 30), time(0, 0))],
            [
                Dispatch(
                    datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 1, 0, tzinfo=timezone.utc),
                )
            ],
            "midnight_crossing_dispatch_not_filtered",
        ),
        # Test case 2: Midnight-crossing dispatch entirely within off-peak windows
        # Dispatch: 23:30-01:00, Off-peak: 23:00-06:00 (split into [00:00-06:00], [23:00-00:00])
        # The entire dispatch is covered by off-peak windows and should be filtered
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 23, 30, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 1, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(6, 0)), TimeWindow(time(23, 0), time(0, 0))],
            [],
            "midnight_crossing_dispatch_entirely_within",
        ),
        # Test case 3: Non-midnight-crossing dispatch entirely within off-peak
        # Dispatch: 01:00-04:00, Off-peak: 00:00-05:30
        # Should be filtered as it's entirely within off-peak
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(5, 30))],
            [],
            "non_midnight_crossing_entirely_within",
        ),
        # Test case 4: Non-midnight-crossing dispatch NOT within off-peak
        # Dispatch: 10:00-12:00, Off-peak: 00:00-05:30
        # Should not be filtered as it's outside off-peak
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(5, 30))],
            [
                Dispatch(
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                )
            ],
            "non_midnight_crossing_outside_offpeak",
        ),
        # Test case 5: Dispatch partially overlapping with off-peak (trimming scenario)
        # Dispatch: 04:00-06:00, Off-peak: 00:00-05:00
        # Should be trimmed to start at 05:00
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 4, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(5, 0))],
            [
                Dispatch(
                    datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 6, 0, tzinfo=timezone.utc),
                )
            ],
            "dispatch_trimmed_at_start",
        ),
        # Test case 6: Multiple windows, dispatch not in any
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(5, 30)), TimeWindow(time(23, 30), time(0, 0))],
            [
                Dispatch(
                    datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                )
            ],
            "multiple_windows_dispatch_outside",
        ),
        # Test case 7: Empty dispatches list
        (
            [],
            [TimeWindow(time(0, 0), time(5, 30))],
            [],
            "empty_dispatches",
        ),
        # Test case 8: Midnight-crossing dispatch with only before-midnight covered
        # Dispatch: 23:00-02:00, Off-peak only before midnight: 22:00-00:00
        # Should NOT be filtered as after-midnight portion is not covered
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 2, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(22, 0), time(0, 0))],
            [
                Dispatch(
                    datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 2, 0, tzinfo=timezone.utc),
                )
            ],
            "midnight_crossing_only_before_covered",
        ),
        # Test case 9: Midnight-crossing dispatch with only after-midnight covered
        # Dispatch: 23:00-02:00, Off-peak only after midnight: 00:00-03:00
        # Should NOT be filtered as before-midnight portion is not covered
        (
            [
                Dispatch(
                    datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 2, 0, tzinfo=timezone.utc),
                )
            ],
            [TimeWindow(time(0, 0), time(3, 0))],
            [
                Dispatch(
                    datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, 2, 0, tzinfo=timezone.utc),
                )
            ],
            "midnight_crossing_only_after_covered",
        ),
    ],
)
def test_trim_dispatches(dispatches, off_peak_windows, expected_output, test_description):
    """Test that trim_dispatches correctly handles midnight-crossing dispatches and off-peak windows"""
    result = trim_dispatches(dispatches, off_peak_windows)
    assert result == expected_output, f"Failed for test case: {test_description}"
