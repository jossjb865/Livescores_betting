"""Data models and schemas for betting data.

Defines Pydantic models for type-safe data validation and serialization.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime
from enum import Enum


class ResultEnum(str, Enum):
    """Possible match results."""

    WIN = "W"
    DRAW = "D"
    LOSS = "L"


class GameStats(BaseModel):
    """Statistics for a single game."""

    result: Optional[ResultEnum] = Field(None, description="Match result (W/D/L)")
    home_score: int = Field(default=0, ge=0, description="Home team score")
    away_score: int = Field(default=0, ge=0, description="Away team score")
    is_home: bool = Field(default=True, description="Whether team was home")

    class Config:
        """Pydantic configuration."""

        use_enum_values = True
        json_schema_extra = {"example": {"result": "W", "home_score": 2, "away_score": 1, "is_home": True}}


class TeamStats(BaseModel):
    """Statistics collection for a team."""

    team_name: str = Field(..., description="Team name")
    recent_games: List[GameStats] = Field(default_factory=list, description="Recent game records")
    cached_at: datetime = Field(default_factory=datetime.utcnow, description="When stats were cached")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "team_name": "Manchester United",
                "recent_games": [{"result": "W", "home_score": 2, "away_score": 1, "is_home": True}],
                "cached_at": "2026-07-26T12:00:00",
            }
        }


class OddsOutcome(BaseModel):
    """Odds outcome for a team."""

    name: str = Field(..., description="Team name")
    price: float = Field(..., gt=1.0, description="Decimal odds")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {"example": {"name": "Manchester United", "price": 1.95}}


class Market(BaseModel):
    """Betting market."""

    key: str = Field(..., description="Market type (e.g., 'h2h')")
    outcomes: List[OddsOutcome] = Field(default_factory=list, description="Possible outcomes")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "key": "h2h",
                "outcomes": [{"name": "Manchester United", "price": 1.95}],
            }
        }


class Bookmaker(BaseModel):
    """Bookmaker information."""

    title: str = Field(..., description="Bookmaker name")
    markets: List[Market] = Field(default_factory=list, description="Available markets")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "title": "Bet365",
                "markets": [{"key": "h2h", "outcomes": [{"name": "Manchester United", "price": 1.95}]}],
            }
        }


class Match(BaseModel):
    """Match information with odds."""

    id: str = Field(..., description="Unique match identifier")
    home_team: str = Field(..., description="Home team name")
    away_team: str = Field(..., description="Away team name")
    bookmakers: List[Bookmaker] = Field(default_factory=list, description="Available bookmakers")

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "id": "match_123",
                "home_team": "Manchester United",
                "away_team": "Liverpool",
                "bookmakers": [],
            }
        }


class BettingEdge(BaseModel):
    """Identified betting edge/opportunity."""

    match_id: str = Field(..., description="Match identifier")
    home_team: str = Field(..., description="Home team")
    away_team: str = Field(..., description="Away team")
    team: str = Field(..., description="Selected team for betting")
    bookmaker: str = Field(..., description="Bookmaker name")
    odds: float = Field(..., gt=1.0, description="Decimal odds")
    implied_probability: float = Field(..., ge=0.0, le=1.0, description="Probability implied by odds")
    true_probability: float = Field(..., ge=0.0, le=1.0, description="Calculated true probability")
    edge: float = Field(..., description="True prob - Implied prob (edge percentage)")
    recent_record: Optional[str] = Field(None, description="Team's recent record")
    recent_games_count: int = Field(default=0, description="Number of recent games analyzed")
    analysis_timestamp: datetime = Field(default_factory=datetime.utcnow, description="When analysis was run")

    class Config:
        """Pydantic configuration."""

        json_encoders = {datetime: lambda v: v.isoformat()}

    @validator("edge")
    def validate_edge(cls, v: float) -> float:
        """Ensure edge is reasonable."""
        if not -0.5 <= v <= 0.5:
            raise ValueError("Edge should be between -0.5 and 0.5")
        return v


class BettingReport(BaseModel):
    """Summary report of betting analysis."""

    total_matches_analyzed: int = Field(..., ge=0, description="Total matches processed")
    opportunities_found: int = Field(..., ge=0, description="Total edges found")
    top_bets: List[BettingEdge] = Field(default_factory=list, description="Top N opportunities")
    report_timestamp: datetime = Field(default_factory=datetime.utcnow, description="Report generation time")
    analysis_duration_seconds: float = Field(default=0.0, ge=0, description="How long analysis took")

    class Config:
        """Pydantic configuration."""

        json_encoders = {datetime: lambda v: v.isoformat()}
