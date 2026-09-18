"""Test isolation for Arcade credentials.

webapp.app loads .env on import (see app.py) so `uv run support-portal`
works without the caller manually sourcing it first. That means a real
ARCADE_API_KEY/LINEAR_TEAM/SLACK_CHANNEL in a developer's .env would
otherwise leak into every test process and make ordinary classify tests
fire real Linear/Slack calls. Strip them before every test regardless of
what .env contains, so the test suite can never reach a real external
system no matter what's configured locally.
"""

import pytest

_ARCADE_ENV_VARS = ("ARCADE_API_KEY", "ARCADE_USER_ID", "LINEAR_TEAM", "SLACK_CHANNEL")


@pytest.fixture(autouse=True)
def _no_real_arcade_credentials(monkeypatch):
    for name in _ARCADE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
