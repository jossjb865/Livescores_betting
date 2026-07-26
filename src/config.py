"""Configuration management using Pydantic.

Supports environment-specific settings with validation and type safety.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseSettings, validator, Field
from pydantic.env_settings import SettingsSourceCallable


class Settings(BaseSettings):
    """Application settings with environment variable support.

    All credentials should be provided via environment variables.
    Example:
        ODDS_API_KEY=your_key TELEGRAM_BOT_TOKEN=token python -m src.main
    """

    # ====== API Credentials (from environment) ======
    odds_api_key: str = Field(..., env="ODDS_API_KEY")
    isports_api_key: str = Field(..., env="ISPORTS_API_KEY")
    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(..., env="TELEGRAM_CHAT_ID")

    # ====== API Endpoints ======
    odds_api_url: str = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
    isports_stats_url: str = "http://api.isportsapi.com/sport/football/team/recent"
    telegram_api_url: str = Field(default="https://api.telegram.org/bot")

    # ====== Request Configuration ======
    request_timeout: int = 5  # seconds
    request_retries: int = 3
    retry_backoff_factor: float = 0.5  # seconds between retries

    # ====== Data Fetching ======
    odds_regions: str = "eu,us"
    odds_markets: str = "h2h"
    odds_format: str = "decimal"
    stats_limit: int = 5  # number of recent games to fetch

    # ====== Betting Engine ======
    min_edge_threshold: float = 0.04  # 4% edge threshold
    min_odds: float = 1.01
    max_odds: float = 10.0
    min_win_probability: float = 0.05
    max_win_probability: float = 0.95
    conservative_adjustment: float = 0.06  # if no stats available
    performance_weight: float = 0.02  # weight for goal difference

    # ====== Filtering & Output ======
    top_bets_count: int = 5  # top N bets to send
    cache_ttl_seconds: int = 3600  # 1 hour

    # ====== Logging ======
    log_level: str = "INFO"
    log_file: Optional[Path] = None
    use_json_logging: bool = False

    # ====== Environment ======
    environment: str = Field(default="development", env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @validator("odds_api_key", "isports_api_key", "telegram_bot_token", "telegram_chat_id")
    def validate_secrets_not_empty(cls, v: str) -> str:
        """Ensure API keys are not empty."""
        if not v or not v.strip():
            raise ValueError("API keys and tokens cannot be empty")
        return v

    @validator("min_edge_threshold")
    def validate_edge_threshold(cls, v: float) -> float:
        """Ensure edge threshold is between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("min_edge_threshold must be between 0 and 1")
        return v

    @validator("top_bets_count")
    def validate_top_bets(cls, v: int) -> int:
        """Ensure top_bets_count is positive."""
        if v <= 0:
            raise ValueError("top_bets_count must be positive")
        return v

    @property
    def telegram_url(self) -> str:
        """Construct full Telegram API URL."""
        return f"{self.telegram_api_url}{self.telegram_bot_token}/sendMessage"

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"

    def dict_masked(self) -> Dict[str, Any]:
        """Return config as dict with masked secrets."""
        config_dict = self.dict()
        secrets = ["odds_api_key", "isports_api_key", "telegram_bot_token", "telegram_chat_id"]
        for secret in secrets:
            if secret in config_dict and config_dict[secret]:
                config_dict[secret] = f"***{config_dict[secret][-4:]}"
        return config_dict


def get_settings() -> Settings:
    """Load and cache settings instance.

    Returns:
        Settings instance

    Raises:
        ValueError: If required environment variables are missing
    """
    try:
        return Settings()
    except Exception as e:
        raise ValueError(
            f"Failed to load settings. Ensure all required environment variables are set. Error: {e}"
        )
