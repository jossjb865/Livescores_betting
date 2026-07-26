"""Betting analysis engine.

Calculates true probabilities and identifies value betting opportunities.
"""

import logging
from typing import List, Optional, Tuple
from src.models.schemas import TeamStats, BettingEdge, Match, Bookmaker, Market, OddsOutcome
from src.config import Settings
from src.utils import clamp, validate_probability, calculate_win_rate


logger = logging.getLogger(__name__)


class BettingEngine:
    """Core betting analysis logic."""

    def __init__(self, config: Settings):
        """Initialize betting engine with configuration.

        Args:
            config: Application settings
        """
        self.config = config

    def calculate_true_probability(self, team_stats: Optional[TeamStats], implied_prob: float) -> float:
        """Calculate the true probability of a team winning.

        Uses team statistics when available, with a conservative adjustment as fallback.

        Args:
            team_stats: Team statistics (can be None/empty)
            implied_prob: Probability implied by bookmaker odds

        Returns:
            Estimated true probability (0-1)
        """
        # Validate inputs
        implied_prob = validate_probability(implied_prob, "implied_probability")

        # Fallback: if no stats, use conservative adjustment
        if not team_stats or not team_stats.recent_games:
            logger.debug(f"No stats available. Using conservative adjustment: {self.config.conservative_adjustment}")
            true_prob = implied_prob + self.config.conservative_adjustment
            return clamp(true_prob, self.config.min_win_probability, self.config.max_win_probability)

        # Calculate metrics from recent games
        total_games = len(team_stats.recent_games)
        wins = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "W")
        draws = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "D")

        # Calculate points (3 for win, 1 for draw, 0 for loss)
        points = wins * 3 + draws * 1
        win_rate = points / (total_games * 3)

        # Calculate goal difference factor
        goal_difference = sum(
            (g.home_score - g.away_score) if g.is_home else (g.away_score - g.home_score)
            for g in team_stats.recent_games
        )
        performance_modifier = goal_difference * self.config.performance_weight

        # Combine metrics
        true_prob = win_rate + performance_modifier

        # Clamp to valid probability range
        true_prob = clamp(true_prob, self.config.min_win_probability, self.config.max_win_probability)

        logger.debug(
            f"Calculated true prob: {true_prob:.3f} "
            f"(win_rate={win_rate:.3f}, modifier={performance_modifier:.3f})"
        )

        return true_prob

    def identify_edges(
        self,
        matches: List[Match],
        team_stats_lookup: dict,
    ) -> List[BettingEdge]:
        """Identify value betting opportunities from matches.

        Args:
            matches: List of matches with odds
            team_stats_lookup: Dictionary mapping team name -> TeamStats

        Returns:
            List of identified betting edges
        """
        edges = []
        processed_keys = set()

        for match in matches:
            for bookmaker in match.bookmakers:
                for market in bookmaker.markets:
                    # Only analyze head-to-head markets
                    if market.key != "h2h":
                        continue

                    for outcome in market.outcomes:
                        team = outcome.name
                        odds = outcome.price

                        # Skip low odds
                        if odds < self.config.min_odds or odds > self.config.max_odds:
                            logger.debug(f"Skipping {team} @ {odds} (outside odds range)")
                            continue

                        # Calculate probabilities
                        implied_prob = 1.0 / odds
                        team_stats = team_stats_lookup.get(team)
                        true_prob = self.calculate_true_probability(team_stats, implied_prob)

                        # Calculate edge
                        edge = true_prob - implied_prob

                        # Create unique key to avoid duplicates
                        edge_key = f"{match.id}-{team}-{bookmaker.title}"

                        if edge_key in processed_keys:
                            continue

                        processed_keys.add(edge_key)

                        # Check if edge meets threshold
                        if edge > self.config.min_edge_threshold:
                            # Build record string if stats available
                            record_str = self._build_record_string(team_stats)

                            betting_edge = BettingEdge(
                                match_id=match.id,
                                home_team=match.home_team,
                                away_team=match.away_team,
                                team=team,
                                bookmaker=bookmaker.title,
                                odds=odds,
                                implied_probability=implied_prob,
                                true_probability=true_prob,
                                edge=edge,
                                recent_record=record_str,
                                recent_games_count=len(team_stats.recent_games) if team_stats else 0,
                            )

                            edges.append(betting_edge)
                            logger.info(
                                f"Found edge: {team} @ {odds} with {edge*100:.1f}% edge "
                                f"(true: {true_prob*100:.1f}%, implied: {implied_prob*100:.1f}%)"
                            )

        return edges

    def rank_edges(self, edges: List[BettingEdge], top_n: Optional[int] = None) -> List[BettingEdge]:
        """Rank edges by edge size (descending).

        Args:
            edges: List of betting edges
            top_n: If specified, return only top N edges

        Returns:
            Sorted list of edges by edge (highest first)
        """
        sorted_edges = sorted(edges, key=lambda e: e.edge, reverse=True)

        if top_n:
            sorted_edges = sorted_edges[:top_n]

        return sorted_edges

    @staticmethod
    def _build_record_string(team_stats: Optional[TeamStats]) -> str:
        """Build a human-readable record string from team stats.

        Args:
            team_stats: Team statistics object

        Returns:
            Record string like "5W-2D-3L"
        """
        if not team_stats or not team_stats.recent_games:
            return "Analyzed by market trend"

        total = len(team_stats.recent_games)
        wins = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "W")
        draws = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "D")
        losses = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "L")

        return f"Record: {wins}W-{draws}D-{losses}L (Last {total} games)"
