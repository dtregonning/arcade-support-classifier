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
  server.py         MCP server (Arcade) exposing the 5 tools — uv run support-mcp
  cli.py            uv run support-demo <ticket.json>
tests/
```

## Demo

```bash
uv sync
uv run pytest
uv run support-demo data/hero_ticket.json
```

For a full walkthrough — a badly-formed ticket, the hero scenario, a
misleading customer hypothesis, and the Arcade/Slack/Linear flow — see
[`DEMO.md`](DEMO.md).

## Web Portal

A mock customer support portal: submit a ticket and watch it run through
the same pipeline as the CLI, then — if Arcade is configured — watch the
AUTO-tier recommended actions actually execute against real Linear and
Slack. No database, no auth; nothing about the ticket itself is persisted
server-side.

```bash
uv run support-portal
```

Then open http://127.0.0.1:8000. Use the "Load an example…" picker to
prefill the form with the hero ticket or any sample ticket, or fill it in
by hand, and click **Classify ticket** to see validation, enrichment,
severity, routing, recommended/rejected actions, and (see below) live
automation results, all rendered on submit.

The classification half of the portal is a thin FastAPI layer
(`src/support_automation/webapp/`) over the exact same `services`/`tools`
functions the CLI calls — it contains no business logic of its own.

### Live Linear/Slack execution

After classifying, the portal calls
`support_automation.services.execution.execute_auto_actions`, which runs
whichever of the recommendation's actions are both in
`{create_linear_issue, notify_support_channel}` **and** marked
`execution="automatic"` — nothing else, and nothing not already
AUTO-tier. It talks to Arcade directly via the `arcadepy` SDK (Arcade's
tool-execution API, not the MCP gateway), so the portal itself never
holds a raw Slack or Linear token — only an `ARCADE_API_KEY`.

This is entirely optional — see `.env.example`:

```bash
ARCADE_API_KEY=...       # required to execute anything at all
ARCADE_USER_ID=...       # identifies *you* (support engineering) to Arcade,
                          # not the customer submitting the ticket
LINEAR_TEAM=...          # a real Linear team name/key in your workspace
SLACK_CHANNEL=...        # a real, already-existing Slack channel
```

Without `ARCADE_API_KEY`, classification still returns the full result —
the portal just reports `create_linear_issue`/`notify_support_channel` as
`skipped` rather than raising, so the demo never breaks for lack of
credentials. With it, each result comes back as one of:

- `executed` — the Linear issue was created / the Slack message was sent;
  `detail` carries the issue URL or a confirmation
- `needs_authorization` — `ARCADE_USER_ID` hasn't granted Linear/Slack
  access yet; `detail` carries a one-time authorization URL to open
- `skipped` — `LINEAR_TEAM`/`SLACK_CHANNEL` isn't set for that action
- `failed` — the Arcade call itself failed; `detail` carries the error
  (e.g. "Team 'X' not found" if `LINEAR_TEAM` doesn't exist)

The Linear issue is created first, and its URL is folded into the Slack
message, mirroring the manual `Linear.CreateIssue` → `Slack.SendMessage`
flow described below.

### Hosting it publicly

To share the portal as a link rather than running it locally, see
[`DEPLOY.md`](DEPLOY.md) — a `Dockerfile` is included, along with steps
to run it on AWS App Runner.

The hero scenario: an enterprise customer (Acme) reports that a third
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

Five composable tools live in `src/support_automation/tools/` and are
exposed as MCP tools by `src/support_automation/server.py` via Arcade's
MCP framework (`arcade-mcp-server`):

- `generate_ticket` — deterministic, seeded mock ticket generator
- `validate_ticket` — deterministic completeness/readiness checks
- `enrich_ticket` — rule-based signal extraction (fact vs. claim vs. hypothesis)
- `route_ticket` — policy-driven routing from `config/routing_rules.yaml`
- `recommend_actions` — policy-gated action recommendations, plus the
  independently assessed severity (there's no separate "assess severity"
  tool — the client-orchestrated chain is exactly the 5 tools above)

Each tool is a thin wrapper around a tested service function — no business
logic lives in `server.py`. The only real work it does is adapting to the
MCP wire format: tickets cross the boundary as `TicketPayload`, identical
to `SupportTicket` except timestamps are ISO-8601 strings rather than
`datetime` objects, since Arcade's tool-schema builder doesn't support
`datetime` as a wire type.

Run the server locally:

```bash
uv run support-mcp stdio   # for Claude Desktop, CLI tools
uv run support-mcp http    # for Cursor, VS Code, an Arcade Gateway, etc.
```

`uv run pytest` includes `tests/test_mcp_server.py`, which calls all five
tools through `arcade_core`'s `ToolExecutor` — the same path Arcade's
runtime uses — so schema generation and tool invocation are both verified
by the test suite, not just by hand.

## Arcade

The server is deployed to Arcade Cloud (`arcade deploy --entrypoint
src/support_automation/server.py`) and connected to Claude Code through a
gateway bundling it with two operational tools:

```bash
arcade connect claude-code --server SupportAutomation \
  --tool Linear.CreateIssue --tool Slack.SendMessage
```

This lets an agent go straight from `recommend_actions` to
`Linear.CreateIssue` or `Slack.SendMessage` — without this server ever
holding a Slack or Linear API token itself; Arcade handles that OAuth
entirely. The demo flow this enables:

```
ticket → validate_ticket → enrich_ticket → route_ticket → recommend_actions
       → Linear.CreateIssue (internal investigation issue)
       → Slack.SendMessage (notify support engineering)
```

Both of those are internal-facing actions from `recommend_actions`'
AUTO-tier action list — per the Automation Policy below, no customer-facing
communication is ever sent automatically.

There are now two independent ways to walk this flow:
- **Agent-orchestrated** (above): an MCP client (Claude Desktop, Claude
  Code) calls the five tools itself, then decides to call
  `Linear.CreateIssue`/`Slack.SendMessage` — the pattern CLAUDE.md
  specifies, useful when a human or agent is driving interactively.
- **Portal-orchestrated** (see Web Portal above): the web portal calls
  Arcade directly and fires the AUTO-tier actions itself, immediately
  after classifying — useful for the "customer submits a ticket, support
  engineering's Slack/Linear just... happens" demo, with no agent in the
  loop at all.

Both paths reach the same two tools through the same Arcade OAuth
grants; neither ever holds a raw Slack or Linear token.

A few things worth knowing if you redo this setup:
- Arcade's toolkit catalog indexes a deployed server by a PascalCase
  version of its `MCPApp(name=...)` (here, `SupportAutomation`), not the
  literal server name shown by `arcade server list`.
- `arcade connect --preset` isn't repeatable (a second `--preset` silently
  replaces the first); use `--tool <Toolkit>.<ToolName>` for precise,
  combinable control instead.
- `arcade connect` always creates a new gateway and a new top-level
  `mcpServers` entry in `~/.claude.json` rather than updating a previous
  one — clean up stray entries by hand if you iterate on the setup.
- Connecting the gateway itself (via `mcp__<server>__authenticate`) is a
  separate OAuth step from authorizing the Slack/Linear *tools* — the
  gateway login gets you tool discovery, but `Linear.CreateIssue` and
  `Slack.SendMessage` each still need their own per-service consent the
  first time they're used. Call `System_ManageAuthorization` with
  `action: "authorize"` and every tool the job will touch up front — it
  batches all the needed service grants into one consolidated ask instead
  of walking the user through a fresh OAuth screen per tool call.
- The `identity-integrations` / `support-engineering` names in this repo's
  routing policy and sample data are illustrative — they won't exist in a
  fresh Linear/Slack workspace. `Linear.CreateIssue` needs a real team
  (name, key, or UUID) and `Slack.SendMessage` needs a real, existing
  channel; both fail with a clear "not found" error (Linear lists your
  actual teams, Slack lists your actual channels) rather than silently
  falling back to something else. Point them at a real team/channel — or
  create one first — before running the live Arcade flow end-to-end.

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
