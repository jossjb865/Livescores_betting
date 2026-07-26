"""Main orchestration module.

Coordinates the entire betting analysis pipeline.
"""

import logging
import time
from typing import Optional, List
from datetime import datetime

from src.config import Settings, get_settings
from src.logger import Logger
from src.data.fetchers import OddsFetcher, StatsFetcher, OddsAPIError, StatsAPIError
from src.models.betting_engine import BettingEngine
from src.alerts.notifiers import TelegramNotifier, NotificationError
from src.cache import MemoryCache
from src.models.schemas import BettingReport


logger = logging.getLogger(__name__)


class BettingPipeline:
    """Orchestrates the complete betting analysis workflow."""

    def __init__(self, config: Optional[Settings] = None):
        """Initialize the pipeline.

        Args:
            config: Settings instance (loads from environment if not provided)

        Raises:
            ValueError: If configuration is invalid
        """
        self.config = config or get_settings()
        self.odds_fetcher = OddsFetcher(self.config)
        self.stats_fetcher = StatsFetcher(self.config)
        self.betting_engine = BettingEngine(self.config)
        self.notifier = TelegramNotifier(self.config)
        self.cache = MemoryCache(
            max_size=1000,
            default_ttl=self.config.cache_ttl_seconds,
        )

        logger.info("BettingPipeline initialized")
        logger.debug(f"Config (masked): {self.config.dict_masked()}")

    def run(self) -> BettingReport:
        """Execute the complete betting analysis pipeline.

        Returns:
            BettingReport with results and statistics
        """
        start_time = time.time()
        logger.info("="*60)
        logger.info("Starting betting analysis pipeline")
        logger.info(f"Environment: {self.config.environment.upper()}")
        logger.info("="*60)

        try:
            # Step 1: Fetch odds
            logger.info("[STEP 1] Fetching live odds...")
            matches = self._fetch_odds()
            if not matches:
                logger.warning("No matches found")
                return self._create_report(0, [], 0, start_time)

            logger.info(f"✓ Retrieved {len(matches)} matches")

            # Step 2: Fetch team statistics
            logger.info("[STEP 2] Fetching team statistics...")
            team_stats_lookup = self._fetch_team_stats(matches)
            logger.info(f"✓ Retrieved stats for {len(team_stats_lookup)} teams")
            logger.debug(f"Cache stats: {self.cache.stats()}")

            # Step 3: Identify betting edges
            logger.info("[STEP 3] Analyzing for betting edges...")
            edges = self.betting_engine.identify_edges(matches, team_stats_lookup)
            logger.info(f"✓ Found {len(edges)} value opportunities")

            # Step 4: Rank and filter
            logger.info("[STEP 4] Ranking opportunities...")
            top_edges = self.betting_engine.rank_edges(edges, self.config.top_bets_count)
            logger.info(f"✓ Top {len(top_edges)} edges selected")

            # Step 5: Send notifications
            if top_edges:
                logger.info("[STEP 5] Sending alerts...")
                self._send_alerts(top_edges)
                logger.info(f"✓ Sent {len(top_edges)} alerts")
            else:
                logger.info("[STEP 5] No edges to send")

            # Create report
            duration = time.time() - start_time
            report = self._create_report(len(matches), top_edges, len(edges), start_time)
            report.analysis_duration_seconds = duration

            logger.info("="*60)
            logger.info(f"Pipeline completed successfully in {duration:.2f}s")
            logger.info(f"Matches: {len(matches)} | Opportunities: {len(edges)} | Top: {len(top_edges)}")
            logger.info("="*60)

            return report

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            raise
        finally:
            self.close()

    def _fetch_odds(self) -> List:
        """Fetch live odds from API.

        Returns:
            List of matches with odds
        """
        try:
            matches = self.odds_fetcher.fetch_live_odds()
            return matches
        except OddsAPIError as e:
            logger.error(f"Failed to fetch odds: {e}")
            raise

    def _fetch_team_stats(self, matches) -> dict:
        """Fetch team statistics for all teams in matches.

        Args:
            matches: List of matches

        Returns:
            Dictionary mapping team name -> TeamStats
        """
        team_stats = {}
        teams_to_fetch = set()

        # Collect unique team names
        for match in matches:
            teams_to_fetch.add(match.home_team)
            teams_to_fetch.add(match.away_team)

        logger.debug(f"Fetching stats for {len(teams_to_fetch)} unique teams")

        for team_name in teams_to_fetch:
            # Try cache first
            cached = self.cache.get(f"stats_{team_name}")
            if cached:
                logger.debug(f"Cache hit for {team_name}")
                team_stats[team_name] = cached
                continue

            # Fetch from API
            try:
                stats = self.stats_fetcher.fetch_team_stats(team_name)
                self.cache.set(f"stats_{team_name}", stats)
                team_stats[team_name] = stats
            except StatsAPIError as e:
                logger.warning(f"Failed to fetch stats for {team_name}: {e}")
                # Return empty stats to continue analysis
                from src.models.schemas import TeamStats
                team_stats[team_name] = TeamStats(team_name=team_name, recent_games=[])

        return team_stats

    def _send_alerts(self, edges: List) -> None:
        """Send alerts for top edges.

        Args:
            edges: List of betting edges to alert
        """
        try:
            success = self.notifier.send_edges(edges)
            if success:
                logger.info(f"Successfully sent {len(edges)} alerts")
            else:
                logger.warning("Some alerts failed to send")
        except NotificationError as e:
            logger.error(f"Failed to send alerts: {e}")
            if self.config.is_production:
                raise

    @staticmethod
    def _create_report(total_matches: int, top_bets: List, total_opportunities: int, start_time: float) -> BettingReport:
        """Create a summary report.

        Args:
            total_matches: Total matches analyzed
            top_bets: Top N betting edges
            total_opportunities: Total edges found
            start_time: Pipeline start time

        Returns:
            BettingReport object
        """
        return BettingReport(
            total_matches_analyzed=total_matches,
            opportunities_found=total_opportunities,
            top_bets=top_bets,
            report_timestamp=datetime.utcnow(),
            analysis_duration_seconds=time.time() - start_time,
        )

    def close(self) -> None:
        """Clean up resources."""
        try:
            self.odds_fetcher.close()
            self.stats_fetcher.close()
            self.notifier.close()
            logger.debug("Pipeline resources closed")
        except Exception as e:
            logger.error(f"Error closing resources: {e}")


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        # Setup logging
        config = get_settings()
        Logger.setup(
            name="livescores_betting",
            level=getattr(logging, config.log_level.upper()),
            log_file=config.log_file,
            use_json=config.use_json_logging,
        )

        # Run pipeline
        pipeline = BettingPipeline(config)
        report = pipeline.run()

        # Log summary
        logger.info(f"\nReport Summary:")
        logger.info(f"  - Matches analyzed: {report.total_matches_analyzed}")
        logger.info(f"  - Opportunities found: {report.opportunities_found}")
        logger.info(f"  - Top bets sent: {len(report.top_bets)}")
        logger.info(f"  - Duration: {report.analysis_duration_seconds:.2f}s")

        return 0

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        return 130
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
