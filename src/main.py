"""Main orchestration module.

Coordinates the entire betting analysis pipeline with optimized flow and duplicate prevention.
"""

import logging
import time
from typing import Optional, List, Set, Dict
from datetime import datetime

from src.config import Settings, get_settings
from src.logger import Logger
from src.data.fetchers import OddsFetcher, StatsFetcher, OddsAPIError, StatsAPIError
from src.models.betting_engine import BettingEngine
from src.alerts.notifiers import TelegramNotifier, NotificationError, NotificationManager
from src.cache import MemoryCache
from src.models.schemas import BettingReport, TeamStats


logger = logging.getLogger(__name__)


class BettingPipeline:
    """Orchestrates the complete betting analysis workflow with optimized logic."""

    def __init__(self, config: Optional[Settings] = None):
        """Initialize the pipeline.

        Args:
            config: Settings instance (loads from environment if not provided)

        Raises:
            ValueError: If configuration is invalid
        """
        self.config = config or get_settings()
        
        # Initialize components
        self.odds_fetcher = OddsFetcher(self.config)
        self.stats_fetcher = StatsFetcher(self.config)
        self.betting_engine = BettingEngine(self.config)
        
        # Shared notification manager to prevent duplicates
        self.notification_manager = NotificationManager(
            cache_ttl_minutes=int(self.config.cache_ttl_seconds / 60)
        )
        self.notifier = TelegramNotifier(self.config, self.notification_manager)
        
        # Data cache
        self.cache = MemoryCache(
            max_size=1000,
            default_ttl=self.config.cache_ttl_seconds,
        )

        logger.info("BettingPipeline initialized successfully")
        logger.debug(f"Config (masked): {self.config.dict_masked()}")

    def run(self) -> BettingReport:
        """Execute the complete betting analysis pipeline.

        Pipeline Flow:
        1. Fetch live odds from bookmakers
        2. Fetch team statistics (with caching)
        3. Analyze and identify betting edges
        4. Rank edges by value (highest edge first)
        5. Send unique notifications (prevent duplicates)
        6. Generate summary report

        Returns:
            BettingReport with results and statistics
        """
        start_time = time.time()
        logger.info("="*70)
        logger.info("🚀 BETTING ANALYSIS PIPELINE STARTED")
        logger.info(f"Environment: {self.config.environment.upper()} | Time: {datetime.utcnow().isoformat()}")
        logger.info("="*70)

        try:
            # Step 1: Fetch odds
            logger.info("\n[1/5] FETCHING LIVE ODDS...")
            matches = self._fetch_odds()
            if not matches:
                logger.warning("⚠ No matches available")
                return self._create_report(0, [], 0, start_time)
            logger.info(f"✓ Retrieved {len(matches)} matches")

            # Step 2: Fetch team statistics
            logger.info("\n[2/5] FETCHING TEAM STATISTICS...")
            team_stats_lookup = self._fetch_team_stats(matches)
            logger.info(f"✓ Retrieved stats for {len(team_stats_lookup)} unique teams")
            self._log_cache_stats()

            # Step 3: Identify betting edges
            logger.info("\n[3/5] ANALYZING FOR VALUE OPPORTUNITIES...")
            all_edges = self.betting_engine.identify_edges(matches, team_stats_lookup)
            logger.info(f"✓ Found {len(all_edges)} total opportunities")

            # Step 4: Rank and filter
            logger.info("\n[4/5] RANKING OPPORTUNITIES...")
            top_edges = self.betting_engine.rank_edges(all_edges, self.config.top_bets_count)
            logger.info(f"✓ Selected TOP {len(top_edges)} best opportunities")
            self._log_edges_summary(top_edges)

            # Step 5: Send notifications (with duplicate prevention)
            notification_success = True
            if top_edges:
                logger.info("\n[5/5] SENDING ALERTS...")
                notification_success = self._send_alerts_smart(top_edges)
            else:
                logger.info("\n[5/5] No opportunities to send")

            # Generate report
            duration = time.time() - start_time
            report = self._create_report(len(matches), top_edges, len(all_edges), start_time)
            report.analysis_duration_seconds = duration

            # Summary
            logger.info("\n" + "="*70)
            logger.info("✅ PIPELINE COMPLETED SUCCESSFULLY")
            logger.info(f"Duration: {duration:.2f}s")
            logger.info(f"Matches: {len(matches)} | Opportunities: {len(all_edges)} | Top Picks: {len(top_edges)}")
            logger.info(f"Notifications: {'✓ Sent' if notification_success else '⚠ Some failed'}")
            logger.info("="*70)

            return report

        except Exception as e:
            logger.error(f"\n❌ PIPELINE FAILED: {e}", exc_info=True)
            raise
        finally:
            self.close()

    def _fetch_odds(self) -> List:
        """Fetch live odds from API with error handling.

        Returns:
            List of matches with odds
        """
        try:
            matches = self.odds_fetcher.fetch_live_odds()
            logger.debug(f"Odds fetched: {len(matches)} matches with bookmakers")
            return matches
        except OddsAPIError as e:
            logger.error(f"Failed to fetch odds: {e}")
            raise

    def _fetch_team_stats(self, matches: List) -> Dict[str, TeamStats]:
        """Fetch team statistics with intelligent caching.

        Strategy:
        - Collect unique teams from matches
        - Check cache first (TTL-based)
        - Fetch from API if not cached
        - Handle failures gracefully with empty stats

        Args:
            matches: List of matches

        Returns:
            Dictionary mapping team name -> TeamStats
        """
        team_stats = {}
        teams_to_fetch = set()

        # Collect unique teams
        for match in matches:
            teams_to_fetch.add(match.home_team)
            teams_to_fetch.add(match.away_team)

        logger.debug(f"Processing {len(teams_to_fetch)} unique teams")

        cache_hits = 0
        cache_misses = 0
        fetch_failures = 0

        for team_name in teams_to_fetch:
            # Check cache
            cache_key = f"stats_{team_name}"
            cached_stats = self.cache.get(cache_key)
            
            if cached_stats:
                logger.debug(f"Cache HIT: {team_name}")
                team_stats[team_name] = cached_stats
                cache_hits += 1
                continue

            cache_misses += 1
            # Fetch from API
            try:
                logger.debug(f"Cache MISS: Fetching {team_name} from API")
                stats = self.stats_fetcher.fetch_team_stats(team_name)
                self.cache.set(cache_key, stats, ttl=self.config.cache_ttl_seconds)
                team_stats[team_name] = stats
            except StatsAPIError as e:
                logger.warning(f"Failed to fetch stats for {team_name}: {e}")
                fetch_failures += 1
                # Continue with empty stats
                team_stats[team_name] = TeamStats(team_name=team_name, recent_games=[])

        logger.info(
            f"Stats retrieval: {cache_hits} from cache, {cache_misses - fetch_failures} from API, "
            f"{fetch_failures} failures (fallback)"
        )
        return team_stats

    def _send_alerts_smart(self, edges: List) -> bool:
        """Send alerts with duplicate prevention.

        Uses NotificationManager to avoid sending the same edge twice
        within the cache TTL window.

        Args:
            edges: List of top betting edges

        Returns:
            True if all notifications sent successfully
        """
        try:
            success = self.notifier.send_edges(edges)
            if success:
                logger.info(f"✓ Alert batch completed successfully")
            else:
                logger.warning("⚠ Some alerts failed to send")
            return success
        except NotificationError as e:
            logger.error(f"Failed to send alerts: {e}")
            if self.config.is_production:
                raise
            return False

    @staticmethod
    def _create_report(
        total_matches: int,
        top_bets: List,
        total_opportunities: int,
        start_time: float,
    ) -> BettingReport:
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

    def _log_cache_stats(self) -> None:
        """Log cache statistics."""
        stats = self.cache.stats()
        logger.info(
            f"Cache: {stats['size']}/{stats['max_size']} | "
            f"Hit Rate: {stats['hit_rate']*100:.1f}% "
            f"({stats['hits']}/{stats['total_requests']})"
        )

    @staticmethod
    def _log_edges_summary(edges: List) -> None:
        """Log summary of top edges.

        Args:
            edges: List of edges to summarize
        """
        if not edges:
            return

        logger.info("\nTop Opportunities:")
        for i, edge in enumerate(edges, 1):
            logger.info(
                f"  {i}. {edge.team} ({edge.bookmaker}) @ {edge.odds:.2f} | "
                f"Edge: {edge.edge*100:.1f}% | "
                f"True Prob: {edge.true_probability*100:.1f}%"
            )

    def close(self) -> None:
        """Clean up resources gracefully."""
        logger.debug("Closing pipeline resources...")
        try:
            self.odds_fetcher.close()
            self.stats_fetcher.close()
            self.notifier.close()
            logger.debug("✓ All resources closed")
        except Exception as e:
            logger.error(f"Error closing resources: {e}")


def main() -> int:
    """Main entry point with error handling and exit codes.

    Exit Codes:
        0: Success
        1: Configuration or unexpected error
        130: Interrupted by user (Ctrl+C)

    Returns:
        Exit code
    """
    try:
        # Load configuration
        config = get_settings()
        
        # Setup logging
        Logger.setup(
            name="livescores_betting",
            level=getattr(logging, config.log_level.upper()),
            log_file=config.log_file,
            use_json=config.use_json_logging,
        )

        # Run pipeline
        pipeline = BettingPipeline(config)
        report = pipeline.run()

        # Print summary
        logger.info("\n📊 FINAL REPORT:")
        logger.info(f"  • Matches analyzed: {report.total_matches_analyzed}")
        logger.info(f"  • Total opportunities: {report.opportunities_found}")
        logger.info(f"  • Top picks sent: {len(report.top_bets)}")
        logger.info(f"  • Analysis time: {report.analysis_duration_seconds:.2f}s")

        return 0

    except KeyboardInterrupt:
        logger.info("\n⚠ Pipeline interrupted by user")
        return 130
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
