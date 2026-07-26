"""Unit tests for the betting engine.

Tests probability calculations and edge identification logic.
"""

import pytest
from src.config import Settings
from src.models.betting_engine import BettingEngine
from src.models.schemas import TeamStats, GameStats, ResultEnum, Match, Bookmaker, Market, OddsOutcome


@pytest.fixture
def config():
    """Fixture for Settings."""
    return Settings(
        odds_api_key="test_key",
        isports_api_key="test_key",
        telegram_bot_token="test_token",
        telegram_chat_id="123456",
        min_edge_threshold=0.04,
        min_odds=1.01,
        conservative_adjustment=0.06,
        performance_weight=0.02,
    )


@pytest.fixture
def engine(config):
    """Fixture for BettingEngine."""
    return BettingEngine(config)


class TestTrueProbabilityCalculation:
    """Tests for calculate_true_probability method."""

    def test_no_stats_uses_conservative_adjustment(self, engine):
        """Test that fallback adjustment is applied when no stats available."""
        implied_prob = 0.5
        true_prob = engine.calculate_true_probability(None, implied_prob)

        expected = min(implied_prob + 0.06, 0.95)
        assert abs(true_prob - expected) < 0.001

    def test_empty_stats_uses_conservative_adjustment(self, engine):
        """Test that fallback adjustment is applied for empty stats."""
        team_stats = TeamStats(team_name="Test Team", recent_games=[])
        implied_prob = 0.5
        true_prob = engine.calculate_true_probability(team_stats, implied_prob)

        expected = min(implied_prob + 0.06, 0.95)
        assert abs(true_prob - expected) < 0.001

    def test_perfect_win_record(self, engine):
        """Test calculation with perfect win record."""
        games = [
            GameStats(result=ResultEnum.WIN, home_score=2, away_score=1, is_home=True),
            GameStats(result=ResultEnum.WIN, home_score=3, away_score=0, is_home=True),
            GameStats(result=ResultEnum.WIN, home_score=1, away_score=0, is_home=True),
        ]
        team_stats = TeamStats(team_name="Test Team", recent_games=games)
        implied_prob = 0.5
        true_prob = engine.calculate_true_probability(team_stats, implied_prob)

        # Win rate: 9/(3*3) = 1.0, no goal difference (2+3+1 = 6 goals)
        # true_prob = 1.0 * 0.02 = 1.0, clamped to 0.95
        assert true_prob > 0.9

    def test_probability_clamping(self, engine):
        """Test that probability is clamped to valid range."""
        # Test lower clamp
        true_prob_low = engine.calculate_true_probability(None, 0.01)
        assert true_prob_low >= 0.05  # min probability

        # Test upper clamp
        true_prob_high = engine.calculate_true_probability(None, 0.99)
        assert true_prob_high <= 0.95  # max probability


class TestEdgeIdentification:
    """Tests for identify_edges method."""

    def test_no_edges_when_odds_too_low(self, engine):
        """Test that very low odds are skipped."""
        match = Match(
            id="match_1",
            home_team="Team A",
            away_team="Team B",
            bookmakers=[
                Bookmaker(
                    title="Bet365",
                    markets=[
                        Market(
                            key="h2h",
                            outcomes=[
                                OddsOutcome(name="Team A", price=1.01),  # Below threshold
                            ],
                        )
                    ],
                )
            ],
        )

        edges = engine.identify_edges([match], {})
        assert len(edges) == 0

    def test_no_edges_when_market_not_h2h(self, engine):
        """Test that non-h2h markets are skipped."""
        match = Match(
            id="match_1",
            home_team="Team A",
            away_team="Team B",
            bookmakers=[
                Bookmaker(
                    title="Bet365",
                    markets=[
                        Market(
                            key="over_under",  # Not h2h
                            outcomes=[
                                OddsOutcome(name="Over 2.5", price=1.95),
                            ],
                        )
                    ],
                )
            ],
        )

        edges = engine.identify_edges([match], {})
        assert len(edges) == 0

    def test_identifies_edge_above_threshold(self, engine):
        """Test that edges above threshold are identified."""
        match = Match(
            id="match_1",
            home_team="Team A",
            away_team="Team B",
            bookmakers=[
                Bookmaker(
                    title="Bet365",
                    markets=[
                        Market(
                            key="h2h",
                            outcomes=[
                                OddsOutcome(name="Team A", price=3.0),  # Implied: 0.333
                            ],
                        )
                    ],
                )
            ],
        )

        # With no stats, true_prob will be 0.333 + 0.06 = 0.393
        # Edge: 0.393 - 0.333 = 0.06 (6%), which is > 4% threshold
        edges = engine.identify_edges([match], {})
        assert len(edges) > 0
        assert edges[0].edge > 0.04


class TestEdgeRanking:
    """Tests for rank_edges method."""

    def test_edges_sorted_by_edge_descending(self, engine, config):
        """Test that edges are sorted by edge size in descending order."""
        from src.models.schemas import BettingEdge

        edge1 = BettingEdge(
            match_id="1",
            home_team="A",
            away_team="B",
            team="A",
            bookmaker="B365",
            odds=2.0,
            implied_probability=0.5,
            true_probability=0.55,
            edge=0.05,
        )

        edge2 = BettingEdge(
            match_id="2",
            home_team="C",
            away_team="D",
            team="C",
            bookmaker="B365",
            odds=3.0,
            implied_probability=0.33,
            true_probability=0.43,
            edge=0.10,
        )

        ranked = engine.rank_edges([edge1, edge2])
        assert ranked[0].edge > ranked[1].edge
        assert ranked[0].edge == 0.10

    def test_top_n_filtering(self, engine):
        """Test that top_n parameter limits results."""
        from src.models.schemas import BettingEdge

        edges = [
            BettingEdge(
                match_id=str(i),
                home_team="A",
                away_team="B",
                team="A",
                bookmaker="B365",
                odds=2.0,
                implied_probability=0.5,
                true_probability=0.5 + i * 0.01,
                edge=i * 0.01,
            )
            for i in range(10)
        ]

        ranked = engine.rank_edges(edges, top_n=3)
        assert len(ranked) == 3
        assert ranked[0].edge > ranked[1].edge > ranked[2].edge
