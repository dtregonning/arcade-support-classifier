"""Test isolation for third-party API credentials.

webapp.app loads .env on import (see app.py) so `uv run support-portal`
works without the caller manually sourcing it first. That means real
credentials in a developer's .env would otherwise leak into every test
process: ARCADE_API_KEY/LINEAR_TEAM/SLACK_CHANNEL could make ordinary
classify tests fire real Linear/Slack calls (this actually happened once
-- see the execution.py fix commit), and ANTHROPIC_API_KEY could make
enrich_ticket tests fire real Anthropic API calls via the AI area
classifier (services/ai_area_classifier.py). Strip all of them before
every test regardless of what .env contains, so the test suite can never
reach a real external system no matter what's configured locally.
"""

import pytest

_THIRD_PARTY_ENV_VARS = (
    "ARCADE_API_KEY",
    "ARCADE_USER_ID",
    "LINEAR_TEAM",
    "SLACK_CHANNEL",
    "ANTHROPIC_API_KEY",
)


@pytest.fixture(autouse=True)
def _no_real_third_party_credentials(monkeypatch):
    for name in _THIRD_PARTY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
