"""Result of attempting to run a recommended AUTO-tier action against a
real external system (Linear, Slack) via Arcade.

Kept separate from `ActionRecommendation`: `recommend_actions` decides
policy — which actions are allowed to run automatically. This records
what actually happened when the portal tried to run one, which is a
runtime/integration concern, not a policy one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ExecutionStatus = Literal["executed", "skipped", "needs_authorization", "failed"]


class ExecutionResult(BaseModel):
    action: str
    status: ExecutionStatus
    detail: str
