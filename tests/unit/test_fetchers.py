"""Unit tests for data fetchers.

Tests OddsFetcher and StatsFetcher with mocked HTTP responses.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests
from src.config import Settings
from src.data.fetchers import OddsFetcher, StatsFetcher, OddsAPIError, StatsAPIError


@pytest.fixture
def config():
    """Fixture for Settings."""
    return Settings(
        odds_api_key="test_key",
        isports_api_key="test_key",
        telegram_bot_token="test_token",
        telegram_chat_id="123456",
    )


class TestOddsFetcher:
    """Tests for OddsFetcher."""

    def test_fetch_live_odds_success(self, config):
        """Test successful odds fetching."""
        mock_response_data = [
            {
                "id": "match_1",
                "home_team": "Team A",
                "away_team": "Team B",
                "bookmakers": [],
            }
        ]

        with patch("requests.Session.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            fetcher = OddsFetcher(config)
            matches = fetcher.fetch_live_odds()

            assert len(matches) == 1
            assert matches[0].home_team == "Team A"
            fetcher.close()

    def test_fetch_live_odds_http_error(self, config):
        """Test handling of HTTP errors."""
        with patch("requests.Session.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.text = "Unauthorized"
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
            mock_get.return_value = mock_response

            fetcher = OddsFetcher(config)
            with pytest.raises(OddsAPIError):
                fetcher.fetch_live_odds()
            fetcher.close()

    def test_fetch_live_odds_timeout(self, config):
        """Test handling of timeout errors."""
        with patch("requests.Session.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()

            fetcher = OddsFetcher(config)
            with pytest.raises(OddsAPIError):
                fetcher.fetch_live_odds()
            fetcher.close()

    def test_context_manager(self, config):
        """Test that context manager properly closes session."""
        with patch("requests.Session.get"):
            with patch.object(OddsFetcher, "close") as mock_close:
                with OddsFetcher(config) as fetcher:
                    pass
                mock_close.assert_called_once()


class TestStatsFetcher:
    """Tests for StatsFetcher."""

    def test_fetch_team_stats_success(self, config):
        """Test successful stats fetching."""
        mock_response_data = {
            "data": [
                {
                    "result": "W",
                    "home_score": 2,
                    "away_score": 1,
                    "is_home": True,
                }
            ]
        }

        with patch("requests.Session.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            fetcher = StatsFetcher(config)
            stats = fetcher.fetch_team_stats("Team A")

            assert stats.team_name == "Team A"
            assert len(stats.recent_games) == 1
            fetcher.close()

    def test_fetch_team_stats_no_data(self, config):
        """Test handling when no stats are found."""
        mock_response_data = {"data": []}

        with patch("requests.Session.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            fetcher = StatsFetcher(config)
            stats = fetcher.fetch_team_stats("Team A")

            assert stats.team_name == "Team A"
            assert len(stats.recent_games) == 0
            fetcher.close()

    def test_fetch_team_stats_http_error(self, config):
        """Test handling of HTTP errors."""
        with patch("requests.Session.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError()
            mock_get.return_value = mock_response

            fetcher = StatsFetcher(config)
            with pytest.raises(StatsAPIError):
                fetcher.fetch_team_stats("Team A")
            fetcher.close()
