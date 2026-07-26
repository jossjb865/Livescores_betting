"""Configuration for pytest.

Provides shared fixtures and configuration for all tests.
"""

import pytest
import logging
from pathlib import Path


# Disable logging during tests for cleaner output
logging.disable(logging.CRITICAL)


@pytest.fixture(scope="session")
def test_data_dir():
    """Fixture for test data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging after each test."""
    yield
    logging.disable(logging.NOTSET)
