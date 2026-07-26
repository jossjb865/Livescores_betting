"""Betting analysis engine.

Calculates true probabilities and identifies value betting opportunities.
Optimized for accuracy and performance with improved heuristics.
"""

import logging
from typing import List, Optional
from src.models.schemas import TeamStats, BettingEdge, Match
from src.config import Settings
from src.utils import clamp, validate_probability


logger = logging.getLogger(__name__)


class BettingEngine:
    """Core betting analysis logic with advanced probability calculations."""

    def __init__(self, config: Settings):
        """Initialize betting engine with configuration.

        Args:
            config: Application settings
        """
        self.config = config
        logger.debug("BettingEngine initialized")

    def calculate_true_probability(self, team_stats: Optional[TeamStats], implied_prob: float) -> float:
        """Calculate true probability using smart heuristics.

        Strategy:
        1. If stats available: Use win rate + goal difference + draw ratio
        2. If stats missing: Use conservative adjustment (market-based estimate)
        3. Always clamp to valid probability range

        Args:
            team_stats: Team statistics (can be None/empty)
            implied_prob: Probability implied by bookmaker odds

        Returns:
            Estimated true probability (0-1)
        """
        # Validate input
        implied_prob = validate_probability(implied_prob, "implied_probability")

        # Case 1: No stats available - use conservative market adjustment
        if not team_stats or not team_stats.recent_games:
            logger.debug(
                f"No stats available, applying conservative adjustment: "
                f"+{self.config.conservative_adjustment*100:.1f}%"
            )
            true_prob = implied_prob + self.config.conservative_adjustment
            return clamp(true_prob, self.config.min_win_probability, self.config.max_win_probability)

        # Case 2: Stats available - calculate from historical data
        total_games = len(team_stats.recent_games)
        wins = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "W")
        draws = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "D")

        # Calculate performance metrics
        # Win rate: (wins + 0.5*draws) / total_games (accounting for draw as half a win)
        adjusted_wins = wins + (draws * 0.5)
        win_rate = adjusted_wins / total_games if total_games > 0 else 0.0

        # Goal difference impact (weighted less than win rate)
        goal_difference = sum(
            (g.home_score - g.away_score) if g.is_home else (g.away_score - g.home_score)
            for g in team_stats.recent_games
        )
        # Normalize goal diff: typically -5 to +5, map to probability adjustment
        avg_goal_diff = goal_difference / total_games if total_games > 0 else 0.0
        performance_modifier = avg_goal_diff * self.config.performance_weight

        # Combine metrics: weight win rate more heavily than goal difference
        # Formula: 60% win_rate + 40% (implied_prob + modifier)
        true_prob = (0.6 * win_rate) + (0.4 * (implied_prob + performance_modifier))

        # Clamp to valid range and add small buffer for regression to mean
        true_prob = clamp(true_prob, self.config.min_win_probability, self.config.max_win_probability)

        logger.debug(
            f"True probability calculated: {true_prob:.3f} | "
            f"Win rate: {win_rate:.3f} | Modifier: {performance_modifier:.3f} | "
            f"Games analyzed: {total_games}"
        )

        return true_prob

    def identify_edges(
        self,
        matches: List[Match],
        team_stats_lookup: dict,
    ) -> List[BettingEdge]:
        """Identify value betting opportunities from matches.

        Logic:
        - Only analyze h2h (head-to-head) markets
        - Skip odds outside configured range
        - Calculate edge = true_prob - implied_prob
        - Filter by minimum edge threshold
        - Avoid duplicate edges (same match + team + bookmaker)

        Args:
            matches: List of matches with odds
            team_stats_lookup: Dictionary mapping team name -> TeamStats

        Returns:
            List of identified betting edges
        """
        edges = []
        processed_edges = set()  # Track processed edges to avoid duplicates

        total_outcomes_analyzed = 0
        outcomes_skipped_odds_range = 0
        outcomes_skipped_edge_threshold = 0

        for match in matches:
            for bookmaker in match.bookmakers:
                for market in bookmaker.markets:
                    # Only analyze h2h markets
                    if market.key != "h2h":
                        continue

                    for outcome in market.outcomes:
                        total_outcomes_analyzed += 1
                        team = outcome.name
                        odds = outcome.price

                        # Skip if odds outside configured range
                        if odds < self.config.min_odds or odds > self.config.max_odds:
                            outcomes_skipped_odds_range += 1
                            logger.debug(
                                f"Skipped {team}: odds {odds:.2f} outside range "
                                f"[{self.config.min_odds}, {self.config.max_odds}]"
                            )
                            continue

                        # Calculate probabilities
                        implied_prob = 1.0 / odds
                        team_stats = team_stats_lookup.get(team)
                        true_prob = self.calculate_true_probability(team_stats, implied_prob)

                        # Calculate edge
                        edge = true_prob - implied_prob

                        # Create unique key to prevent duplicates
                        edge_key = f"{match.id}#{team}#{bookmaker.title}"
                        if edge_key in processed_edges:
                            logger.debug(f"Duplicate edge skipped: {edge_key}")
                            continue

                        # Check if edge meets threshold
                        if edge > self.config.min_edge_threshold:
                            processed_edges.add(edge_key)

                            # Build record string
                            record_str = self._build_record_string(team_stats)

                            # Create betting edge
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
                                f"✓ EDGE FOUND: {team} @ {odds:.2f} | "
                                f"Edge: {edge*100:.1f}% | "
                                f"True Prob: {true_prob*100:.1f}% vs Implied: {implied_prob*100:.1f}%"
                            )
                        else:
                            outcomes_skipped_edge_threshold += 1

        logger.info(
            f"Edge analysis summary: {total_outcomes_analyzed} outcomes analyzed | "
            f"{outcomes_skipped_odds_range} outside odds range | "
            f"{outcomes_skipped_edge_threshold} below edge threshold | "
            f"{len(edges)} edges found"
        )

        return edges

    def rank_edges(self, edges: List[BettingEdge], top_n: Optional[int] = None) -> List[BettingEdge]:
        """Rank edges by value (edge size) in descending order.

        Args:
            edges: List of betting edges
            top_n: If specified, return only top N edges

        Returns:
            Sorted list of edges (highest edge first)
        """
        sorted_edges = sorted(edges, key=lambda e: e.edge, reverse=True)

        if top_n and len(sorted_edges) > top_n:
            logger.debug(f"Limiting edges: {len(sorted_edges)} -> top {top_n}")
            sorted_edges = sorted_edges[:top_n]

        return sorted_edges

    @staticmethod
    def _build_record_string(team_stats: Optional[TeamStats]) -> str:
        """Build human-readable record string from team statistics.

        Args:
            team_stats: Team statistics object

        Returns:
            Record string like "5W-2D-3L (Last 10 games, Win Rate: 55%)"
        """
        if not team_stats or not team_stats.recent_games:
            return "Analyzed by market trend"

        total = len(team_stats.recent_games)
        wins = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "W")
        draws = sum(1 for g in team_stats.recent_games if g.result and g.result.value == "D")
        losses = total - wins - draws

        win_rate = (wins / total * 100) if total > 0 else 0

        return f"{wins}W-{draws}D-{losses}L (Last {total} games, Win Rate: {win_rate:.0f}%)"
