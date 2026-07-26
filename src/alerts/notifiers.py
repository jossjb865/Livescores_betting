"""Alert and notification system.

Handles sending betting alerts to various channels (Telegram, etc.).
Optimized to prevent duplicate sends and manage state efficiently.
"""

import logging
from typing import List, Set, Dict, Any, Optional
from abc import ABC, abstractmethod
import requests
from requests.exceptions import RequestException, Timeout
from datetime import datetime, timedelta

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


class NotificationManager:
    """Manages notification state and prevents duplicates."""

    def __init__(self, cache_ttl_minutes: int = 60):
        """Initialize notification manager.

        Args:
            cache_ttl_minutes: How long to remember sent notifications
        """
        self._sent_edges: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)

    def _get_edge_key(self, edge: BettingEdge) -> str:
        """Generate unique key for an edge.

        Args:
            edge: Betting edge

        Returns:
            Unique identifier for the edge
        """
        return f"{edge.match_id}_{edge.team}_{edge.bookmaker}"

    def should_send(self, edge: BettingEdge) -> bool:
        """Check if edge should be sent (not duplicate).

        Args:
            edge: Betting edge to check

        Returns:
            True if edge hasn't been sent recently, False otherwise
        """
        self._cleanup_expired()
        edge_key = self._get_edge_key(edge)
        return edge_key not in self._sent_edges

    def mark_sent(self, edge: BettingEdge) -> None:
        """Mark an edge as sent.

        Args:
            edge: Betting edge to mark
        """
        edge_key = self._get_edge_key(edge)
        self._sent_edges[edge_key] = datetime.utcnow()
        logger.debug(f"Marked edge as sent: {edge_key}")

    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        now = datetime.utcnow()
        expired_keys = [
            key for key, sent_time in self._sent_edges.items()
            if now - sent_time > self.cache_ttl
        ]
        for key in expired_keys:
            del self._sent_edges[key]
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired notifications")

    def stats(self) -> Dict[str, int]:
        """Get notification manager statistics.

        Returns:
            Dictionary with stats
        """
        return {
            "cached_notifications": len(self._sent_edges),
            "cache_ttl_minutes": int(self.cache_ttl.total_seconds() / 60),
        }


class TelegramNotifier(Notifier):
    """Sends notifications via Telegram with duplicate prevention."""

    def __init__(self, config: Settings, notification_manager: Optional[NotificationManager] = None):
        """Initialize Telegram notifier.

        Args:
            config: Application settings
            notification_manager: Optional notification manager for deduplication

        Raises:
            NotificationError: If configuration is invalid
        """
        if not config.telegram_bot_token or not config.telegram_chat_id:
            raise NotificationError("Telegram credentials not configured")

        self.config = config
        self.session = requests.Session()
        self.notification_manager = notification_manager or NotificationManager(
            cache_ttl_minutes=int(config.cache_ttl_seconds / 60)
        )
        logger.info("TelegramNotifier initialized")

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

            logger.debug(f"Sending Telegram message ({len(message)} chars)")
            response = self.session.post(
                self.config.telegram_url,
                json=payload,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()

            logger.info("✓ Telegram message sent successfully")
            return True

        except requests.exceptions.HTTPError as e:
            logger.error(f"Telegram HTTP error: {e.response.status_code}")
            raise NotificationError(f"Telegram HTTP error: {e}") from e
        except Timeout:
            logger.error(f"Telegram request timed out (>{self.config.request_timeout}s)")
            raise NotificationError("Telegram request timed out") from None
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram: {e}")
            raise NotificationError(f"Unexpected error: {e}") from e

    def send_edges(self, edges: List[BettingEdge]) -> bool:
        """Send unique betting edges, avoiding duplicates.

        Uses notification manager to prevent sending the same edge multiple times.

        Args:
            edges: List of betting edges (typically top N, already sorted)

        Returns:
            True if all messages sent successfully
        """
        if not edges:
            logger.info("No edges to send")
            return True

        # Filter out already-sent edges
        edges_to_send = [edge for edge in edges if self.notification_manager.should_send(edge)]

        if not edges_to_send:
            logger.info("All edges already sent recently, skipping notifications")
            return True

        logger.info(f"Sending {len(edges_to_send)} edge(s) out of {len(edges)}")

        success = True
        for i, edge in enumerate(edges_to_send, 1):
            try:
                message = self._format_edge_message(edge, position=i, total=len(edges_to_send))
                if self.send(message):
                    # Mark as sent only if message was successfully sent
                    self.notification_manager.mark_sent(edge)
                else:
                    logger.warning(f"Failed to send edge {i}")
                    success = False
            except NotificationError as e:
                logger.error(f"Failed to send edge {i}: {e}")
                success = False

        logger.info(
            f"Notification batch complete: {len(edges_to_send)} sent, "
            f"{len(edges) - len(edges_to_send)} deduplicated"
        )
        logger.debug(f"Notification manager stats: {self.notification_manager.stats()}")
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
        # Calculate ROI (Return on Investment)
        roi = ((edge.true_probability * (edge.odds - 1)) - (1 - edge.true_probability)) * 100

        message = (
            f"🚨 *VALUE BET #{position}/{total}* 🚨\n\n"
            f"⚽ *Match:* {edge.home_team} vs {edge.away_team}\n"
            f"📈 *Selection:* *{edge.team}*\n"
            f"🏦 *Bookmaker:* {edge.bookmaker}\n"
            f"💰 *Odds:* {edge.odds:.2f}\n"
            f"  └─ Implied Win Prob: {format_percentage(edge.implied_probability)}\n\n"
            f"📊 *Calculated True Probability:* {format_percentage(edge.true_probability)}\n"
            f"🔥 *EDGE (Value):* {format_percentage(edge.edge)}\n"
            f"📉 *Expected ROI:* {roi:.1f}%\n"
        )

        if edge.recent_record:
            message += f"\n📌 *Form:* {edge.recent_record}"

        message += f"\n⏰ _Analysis: {edge.analysis_timestamp.strftime('%H:%M:%S UTC')}_"

        return message

    def close(self) -> None:
        """Close the session."""
        try:
            self.session.close()
            logger.debug("TelegramNotifier session closed")
        except Exception as e:
            logger.error(f"Error closing TelegramNotifier: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
