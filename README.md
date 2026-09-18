# Support Automation MCP Demo

A small, credible demonstration of engineering-led support automation:
validate, enrich, assess severity, route, and recommend actions for a
support ticket — deterministically, explainably, and with humans kept in
control of anything risky.

## Problem

Support teams receive incomplete, noisy tickets that mix real evidence with
customer guesses and irrelevant recent events. A customer says "your
servers are down"; the logs say something else entirely. Triage burns time
sorting fact from hypothesis before anyone can act.

## Solution

A composable, MCP-exposed automation layer that:

1. Validates whether a ticket has enough information to act on
2. Extracts technical signals from logs/errors as structured evidence
3. Keeps **facts**, **customer claims**, and **system hypotheses** in
   separate fields — never merged
4. Independently assesses severity instead of trusting the customer's label
5. Routes the ticket using externalized, editable policy (YAML, not code)
6. Recommends actions — and just as importantly, shows what it *declined*
   to do and why

## Architecture

```
                        ┌──────────────────────┐
                        │  Claude / MCP Client │
                        └───────────┬──────────┘
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │  Arcade MCP Gateway  │
                        └───────────┬──────────┘
                                    │
             ┌──────────────────────┼─────────────────────┐
             │                      │                     │
             ▼                      ▼                     ▼
    Support Automation MCP        Slack                Linear
       Custom Server          Arcade Toolkit       Arcade Toolkit
```

The custom server (this repo) owns validation, enrichment, routing,
severity, and support policy. Arcade-provided integrations own execution
into external systems (Slack, Linear). The custom server never calls back
into itself through the gateway — the MCP client orchestrates the tool
sequence.

### Code layout

```
config/            routing_rules.yaml, validation_rules.yaml — editable policy
data/               sample_tickets.json, hero_ticket.json
src/support_automation/
  models/           Pydantic models: ticket, validation, enrichment, routing
  services/         deterministic business logic (validator, enricher, severity, router, recommendations)
  tools/            thin wrappers around services — these become MCP tools
  webapp/           FastAPI web portal (form UI over the same services/tools)
  cli.py            uv run support-demo <ticket.json>
tests/
```

## Demo

```bash
uv sync
uv run pytest
uv run support-demo data/hero_ticket.json
```

## Web Portal

A minimal web front end for submitting a ticket and seeing it run through
the same pipeline as the CLI — no database, no auth, nothing persisted
server-side; a ticket is classified on submit and the result is returned
straight to the browser.

```bash
uv run support-portal
```

Then open http://127.0.0.1:8000. Use the "Load an example…" picker to
prefill the form with the hero ticket or any sample ticket, or fill it in
by hand, and click **Classify ticket** to see validation, enrichment,
severity, routing, and recommended/rejected actions rendered live.

The portal is a thin FastAPI layer (`src/support_automation/webapp/`) over
the exact same `services`/`tools` functions the CLI calls — it contains no
business logic of its own.

The hero scenario: an enterprise customer (Meridian) reports that a third
of their users can't send Gmail, and their AI team suspects Arcade is
losing OAuth tokens. Recent changes on file include an Okta certificate
rotation, some unrelated Salesforce 429s, and a Google toolkit upgrade.
The logs show `required_scopes=[gmail.send,gmail.compose]` vs.
`granted_scopes=[gmail.readonly,gmail.send]`.

The system:

- Detects an **OAuth scope mismatch** (`gmail.compose` required, not granted)
- Recommends **P2**, not the customer's reported P1 — and says why, without
  overwriting the reported severity
- Routes to `identity-integrations`
- Recommends: create an internal investigation issue, notify support
  engineering, request Google reauthorization (human-approval), and
  investigate the Google toolkit upgrade as a correlated lead
- **Rejects** paging infrastructure (no infra evidence) and explicitly
  declines to blame the Okta certificate rotation or the Salesforce 429s —
  both are surfaced as recent changes with **no evidence linking them** to
  the observed signal

## MCP

Five composable tools live in `src/support_automation/tools/`:

- `generate_ticket` — deterministic, seeded mock ticket generator
- `validate_ticket` — deterministic completeness/readiness checks
- `enrich_ticket` — rule-based signal extraction (fact vs. claim vs. hypothesis)
- `route_ticket` — policy-driven routing from `config/routing_rules.yaml`
- `recommend_actions` — policy-gated action recommendations

Each tool is a thin wrapper around a tested service function — no business
logic lives in the MCP layer itself. Exposing them via Arcade's MCP
framework is Phase 2 of this project.

## Arcade

Once the custom tools are verified locally, Arcade can expose this server
alongside operational toolkits (Slack, Linear) behind one MCP Gateway, so
an agent can go straight from `support.recommend_actions` to
`Linear.CreateIssue` or `Slack.PostMessage` — without this server ever
holding a Slack or Linear API token itself.

## Safety Model

**AI reasons. Policy decides. Humans retain control of high-risk actions.**

- Severity thresholds, routing, required fields, and escalation rules are
  deterministic code and YAML — not LLM output.
- Every decision returns `reason_codes` and `evidence`, not just a bare
  classification.
- Three execution classes gate every recommended action:
  - **AUTO** — tagging, classification, routing, internal issues
  - **APPROVAL_REQUIRED** — customer communication, reauthorization requests,
    config changes
  - **HUMAN_ONLY** — destructive, irreversible, or security-sensitive actions
- `recommend_actions` always reports `actions_rejected` alongside `actions`,
  so what the system declined to do is as visible as what it did.

## Engineering Quality

```bash
uv run pytest
uv run ruff check .
```

Typed Pydantic models at every boundary, `RuleBasedEnricher` behind a
`TicketEnricher` protocol (so an AI-backed enricher can be added later
without touching anything downstream), and zero third-party credentials
required to run the full demo.
