"""Alert and notification system.

Handles sending betting alerts to various channels (Telegram, etc.).
"""

import logging
from typing import List, Protocol, Dict, Any
from abc import ABC, abstractmethod
import requests
from requests.exceptions import RequestException, Timeout

from src.config import Settings
from src.models.schemas import BettingEdge
from src.utils import retry_with_backoff, format_percentage


logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Custom exception for notification errors."""

    pass


class Notifier(ABC):
    """Abstract base class for notifiers."""

    @abstractmethod
    def send(self, message: str) -> bool:
        """Send a notification.

        Args:
            message: Message to send

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def send_edges(self, edges: List[BettingEdge]) -> bool:
        """Send a list of betting edges.

        Args:
            edges: List of betting edges to send

        Returns:
            True if successful, False otherwise
        """
        pass


class TelegramNotifier(Notifier):
    """Sends notifications via Telegram."""

    def __init__(self, config: Settings):
        """Initialize Telegram notifier.

        Args:
            config: Application settings

        Raises:
            NotificationError: If configuration is invalid
        """
        if not config.telegram_bot_token or not config.telegram_chat_id:
            raise NotificationError("Telegram credentials not configured")

        self.config = config
        self.session = requests.Session()

    @retry_with_backoff(
        max_retries=3,
        base_delay=0.5,
        exceptions=(RequestException, Timeout),
    )
    def send(self, message: str) -> bool:
        """Send a message via Telegram.

        Args:
            message: Message text (supports Markdown)

        Returns:
            True if successful

        Raises:
            NotificationError: If sending fails after retries
        """
        try:
            payload = {
                "chat_id": self.config.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }

            logger.debug(f"Sending Telegram message to {self.config.telegram_chat_id}")
            response = self.session.post(
                self.config.telegram_url,
                json=payload,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()

            logger.info("Telegram message sent successfully")
            return True

        except requests.exceptions.HTTPError as e:
            logger.error(f"Telegram HTTP error: {e.response.status_code} - {e.response.text}")
            raise NotificationError(f"Telegram HTTP error: {e}") from e
        except Timeout:
            logger.error(f"Telegram request timed out (>{self.config.request_timeout}s)")
            raise NotificationError("Telegram request timed out") from None
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {e}")
            raise NotificationError(f"Unexpected error: {e}") from e

    def send_edges(self, edges: List[BettingEdge]) -> bool:
        """Send betting edges as formatted Telegram messages.

        Args:
            edges: List of betting edges (typically top N)

        Returns:
            True if all messages sent successfully
        """
        if not edges:
            logger.info("No edges to send")
            return True

        success = True
        for i, edge in enumerate(edges, 1):
            try:
                message = self._format_edge_message(edge, position=i, total=len(edges))
                self.send(message)
            except NotificationError as e:
                logger.error(f"Failed to send edge {i}: {e}")
                success = False

        return success

    @staticmethod
    def _format_edge_message(edge: BettingEdge, position: int = 1, total: int = 1) -> str:
        """Format a betting edge as a Telegram message.

        Args:
            edge: Betting edge to format
            position: Position in list (for numbering)
            total: Total edges in list

        Returns:
            Formatted Markdown message
        """
        message = (
            f"🚨 *VALUE BET #{position}/{total}* 🚨\n\n"
            f"⚽ *Match:* {edge.home_team} vs {edge.away_team}\n"
            f"📈 *Selection:* {edge.team}\n"
            f"🏦 *Bookmaker:* {edge.bookmaker}\n"
            f"💰 *Odds:* {edge.odds:.2f}\n"
            f"  └─ Implied: {format_percentage(edge.implied_probability)}\n"
            f"📊 *True Probability:* {format_percentage(edge.true_probability)}\n"
            f"🔥 *EDGE:* {format_percentage(edge.edge)}\n"
        )

        if edge.recent_record:
            message += f"\n📌 *Record:* {edge.recent_record}\n"

        message += f"\n⏰ Analysis: {edge.analysis_timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"

        return message

    def close(self) -> None:
        """Close the session."""
        self.session.close()
        logger.debug("TelegramNotifier session closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
