"""Data fetching layer for APIs.

Handles communication with external APIs (odds, stats) with retry logic and error handling.
"""

import logging
from typing import List, Dict, Any, Optional
import requests
from requests.exceptions import RequestException, Timeout, ConnectionError

from src.config import Settings
from src.models.schemas import Match, TeamStats, GameStats, ResultEnum
from src.utils import retry_with_backoff


logger = logging.getLogger(__name__)


class OddsAPIError(Exception):
    """Custom exception for odds API errors."""

    pass


class StatsAPIError(Exception):
    """Custom exception for stats API errors."""

    pass


class OddsFetcher:
    """Fetches live odds from the-odds-api.com."""

    def __init__(self, config: Settings):
        """Initialize fetcher with configuration.

        Args:
            config: Application settings
        """
        self.config = config
        self.session = requests.Session()

    @retry_with_backoff(
        max_retries=3,
        base_delay=0.5,
        exceptions=(RequestException, Timeout, ConnectionError),
    )
    def fetch_live_odds(self) -> List[Match]:
        """Fetch live soccer odds from API.

        Returns:
            List of Match objects with odds data

        Raises:
            OddsAPIError: If API request fails after retries
        """
        try:
            params = {
                "apiKey": self.config.odds_api_key,
                "regions": self.config.odds_regions,
                "markets": self.config.odds_markets,
                "oddsFormat": self.config.odds_format,
            }

            logger.debug(f"Fetching odds from {self.config.odds_api_url}")
            response = self.session.get(
                self.config.odds_api_url,
                params=params,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"Successfully fetched {len(data)} matches from odds API")

            # Parse and validate matches
            matches = []
            for match_data in data:
                try:
                    match = Match(
                        id=match_data.get("id", f"{match_data.get('home_team')}-{match_data.get('away_team')}"),
                        home_team=match_data.get("home_team", "Unknown"),
                        away_team=match_data.get("away_team", "Unknown"),
                        bookmakers=match_data.get("bookmakers", []),
                    )
                    matches.append(match)
                except Exception as e:
                    logger.warning(f"Failed to parse match data: {e}")
                    continue

            return matches

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching odds: {e.response.status_code} - {e.response.text}")
            raise OddsAPIError(f"Failed to fetch odds: {e}") from e
        except Timeout:
            logger.error(f"Timeout fetching odds (>{self.config.request_timeout}s)")
            raise OddsAPIError("Odds API request timed out") from None
        except Exception as e:
            logger.error(f"Unexpected error fetching odds: {e}")
            raise OddsAPIError(f"Unexpected error: {e}") from e

    def close(self) -> None:
        """Close the session."""
        self.session.close()
        logger.debug("OddsFetcher session closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class StatsFetcher:
    """Fetches team statistics from isportsapi.com."""

    def __init__(self, config: Settings):
        """Initialize fetcher with configuration.

        Args:
            config: Application settings
        """
        self.config = config
        self.session = requests.Session()

    @retry_with_backoff(
        max_retries=3,
        base_delay=0.5,
        exceptions=(RequestException, Timeout, ConnectionError),
    )
    def fetch_team_stats(self, team_name: str) -> TeamStats:
        """Fetch recent team statistics.

        Args:
            team_name: Name of the team

        Returns:
            TeamStats object with recent game records

        Raises:
            StatsAPIError: If API request fails after retries
        """
        try:
            params = {
                "api_key": self.config.isports_api_key,
                "team_name": team_name,
                "limit": self.config.stats_limit,
            }

            logger.debug(f"Fetching stats for team: {team_name}")
            response = self.session.get(
                self.config.isports_stats_url,
                params=params,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()

            data = response.json().get("data", [])

            if not data:
                logger.warning(f"No stats found for team: {team_name}")
                return TeamStats(team_name=team_name, recent_games=[])

            # Parse game records
            recent_games = []
            for game_data in data:
                try:
                    # Map result code to enum
                    result_code = game_data.get("result", "")
                    result = None
                    if result_code.upper() in ["W", "D", "L"]:
                        result = ResultEnum(result_code.upper())

                    game = GameStats(
                        result=result,
                        home_score=int(game_data.get("home_score", 0)),
                        away_score=int(game_data.get("away_score", 0)),
                        is_home=game_data.get("is_home", True),
                    )
                    recent_games.append(game)
                except Exception as e:
                    logger.warning(f"Failed to parse game data for {team_name}: {e}")
                    continue

            logger.info(f"Successfully fetched {len(recent_games)} games for {team_name}")
            return TeamStats(team_name=team_name, recent_games=recent_games)

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error fetching stats: {e.response.status_code}")
            raise StatsAPIError(f"Failed to fetch stats for {team_name}: {e}") from e
        except Timeout:
            logger.error(f"Timeout fetching stats for {team_name}")
            raise StatsAPIError(f"Stats API request timed out for {team_name}") from None
        except Exception as e:
            logger.error(f"Unexpected error fetching stats for {team_name}: {e}")
            raise StatsAPIError(f"Unexpected error: {e}") from e

    def close(self) -> None:
        """Close the session."""
        self.session.close()
        logger.debug("StatsFetcher session closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
