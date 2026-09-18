"""Web support portal.

A thin presentation layer over the same deterministic pipeline the CLI
uses (support_automation.tools / services) — no business logic lives
here, and no database: a submitted ticket is classified on the spot and
the result is returned to the browser, nothing is persisted server-side.

After classification, AUTO-tier recommended actions (create_linear_issue,
notify_support_channel) are executed for real via
support_automation.services.execution, which talks to Arcade directly.
This is optional: without ARCADE_API_KEY configured, classification still
returns the full result — execution is just reported as skipped. See
CLAUDE.md's Automation Policy: only execution="automatic" actions run,
and nothing here can execute an APPROVAL_REQUIRED or HUMAN_ONLY action.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from support_automation.models.ticket import SupportTicket
from support_automation.services.execution import execute_auto_actions
from support_automation.services.severity import recommend_severity
from support_automation.tools.enrich_ticket import enrich_ticket
from support_automation.tools.recommend_actions import recommend_actions
from support_automation.tools.route_ticket import route_ticket
from support_automation.tools.validate_ticket import validate_ticket
from support_automation.webapp.schemas import ClassificationResult, TicketSubmission

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"

app = FastAPI(title="Support Automation Portal")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/samples")
def list_samples() -> list[dict]:
    """Sample tickets for the portal's "load example" picker."""
    hero = json.loads((_DATA_DIR / "hero_ticket.json").read_text())
    samples = json.loads((_DATA_DIR / "sample_tickets.json").read_text())
    return [hero, *samples]


@app.post("/api/tickets/classify", response_model=ClassificationResult)
def classify_ticket(payload: TicketSubmission) -> ClassificationResult:
    ticket_id = payload.ticket_id or f"TICK-{uuid.uuid4().hex[:8].upper()}"
    ticket_fields = payload.model_dump(exclude={"ticket_id", "reported_at"})
    ticket = SupportTicket(
        ticket_id=ticket_id,
        reported_at=payload.reported_at or datetime.now(UTC),
        **ticket_fields,
    )

    validation = validate_ticket(ticket)
    enrichment = enrich_ticket(ticket)
    severity = recommend_severity(ticket, enrichment)
    routing = route_ticket(ticket, enrichment)
    recommendation = recommend_actions(ticket, validation, enrichment, severity, routing)
    executions = execute_auto_actions(ticket, enrichment, severity, routing, recommendation)

    return ClassificationResult(
        ticket=ticket,
        validation=validation,
        enrichment=enrichment,
        severity=severity,
        routing=routing,
        recommendation=recommendation,
        executions=executions,
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
