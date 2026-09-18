# Demo Script (5-10 minutes)

A walkthrough for presenting this project live. Each step is a command you
run and a point it proves. Total run time is a few seconds — the minutes
are you narrating, not the system thinking.

Setup, once, before you start talking:

```bash
uv sync
uv run pytest    # 31 passed — confirms the system is in a known-good state
```

---

## 1. A badly formed ticket (validator catches missing information)

```bash
uv run support-demo data/insufficient_info_ticket.json
```

The ticket is just `"Things are broken" / "It's not working."` — no logs,
no impact numbers, no product, nothing.

Point out:
- `Completeness: 30%`, `Valid: NO`, `Automation Ready: NO` — all
  **deterministic**, derived from a visible list of missing fields, not an
  LLM guess.
- Because no technical signal was detected, the routing engine's own
  fallback rule fires (`Matched rule: unknown`) and severity defaults
  conservatively to P3 rather than inventing a P1/P2 story out of nothing.
- Under Recommended/Rejected: the system still creates an internal ticket
  and notifies support, but **rejects `automated_remediation`** — "no
  technical signal was detected with enough confidence... requires human
  triage." It doesn't guess at a fix it has no evidence for.

This is the validator doing its job: stopping automation from acting
confidently on a ticket that doesn't support confidence.

---

## 2. The hero ticket (Meridian — Gmail OAuth scope mismatch)

```bash
uv run support-demo data/hero_ticket.json
```

This is the flagship scenario: an enterprise customer reports ~33% of
users can't send Gmail, and their own AI team's hypothesis is "Arcade is
losing tokens." The ticket also carries three recent changes: an Okta
certificate rotation, some Salesforce 429s, and a Google toolkit upgrade.

Walk through the sections in order:

- **VALIDATION** — 95% complete, ready for automation. One warning:
  the customer said P1, but the described impact (33%) doesn't clearly
  support that on its own — flagged, not silently accepted.
- **SIGNALS & ENRICHMENT** — this is the core of the story:
  - `Fact: gmail.compose scope is required` / `Fact: gmail.compose scope
    was not granted` — pulled straight from the log line, labeled as facts.
  - `Customer hypothesis (not treated as fact): "Arcade is losing tokens"`
    — kept in its own field, never promoted to a cause.
  - `Possible cause: OAuth scope mismatch (confidence 96%)` — the
    system's own conclusion, with `reason_codes` attached.
  - The Google toolkit upgrade is listed under **correlated recent
    changes** — a plausible investigation lead, explicitly *not* claimed
    as a confirmed cause.
  - The Okta rotation and the Salesforce 429s are listed under **recent
    changes NOT implicated** — each with the reason `"No evidence links
    this change to the observed signals."` This is the negative case the
    demo exists to prove: three plausible-sounding distractors were on the
    ticket, and the system named two of them and explicitly declined to
    blame either.
- **SEVERITY** — `Customer: P1`, `Recommended: P2`, with the reasoning
  spelled out (33% of users maps to P2) and an explicit note that the
  reported severity is *preserved, not overwritten*.
- **ROUTING** — `identity-integrations`, matched by rule `oauth-google`
  at 96% confidence, with `reason_codes` you can trace straight back to
  the signals above.
- **RECOMMENDED ACTIONS** — create an internal issue and notify support
  (both automatic), request Google reauthorization (△ — human approval
  required, since it's customer-facing), and investigate the toolkit
  upgrade as a lead (automatic — investigating is low-risk; concluding
  isn't).
- **REJECTED ACTIONS** — paging infrastructure (no infra evidence), and,
  explicitly, attributing root cause to either the Okta rotation or the
  Salesforce 429s. The system shows its restraint as clearly as its
  actions.

This scenario has an automated test (`tests/test_demo_scenarios.py`) that
pins all of the above — the mismatch signal, the P2 recommendation, the
route, and both rejections — so this exact story can't silently drift.

---

## 3. A misleading customer hypothesis ("Your servers are down")

```bash
uv run support-demo data/misleading_hypothesis_ticket.json
```

The customer's own words are the subject line: *"Your servers are down."*
The logs say something else entirely — `HTTP 401`, `error=invalid_scope`,
a Google Drive scope never granted. Only 12 of 600 users are affected.

Point out:
- Enrichment again separates the customer's claim from the evidence:
  the hypothesis "Your servers are down" is recorded, but the detected
  cause is `OAuth scope mismatch (confidence 96%)` — driven entirely by
  the scope facts, not the customer's framing.
- Severity: customer said P1 ("down" implies total outage); the system
  recommends P3 because only 2% of users are affected, and says so.
- An unrelated "Marketing site redesign" recent change is present on the
  ticket and explicitly rejected as a cause — same pattern as the hero
  scenario, on a completely different distractor.

Together, scenarios 2 and 3 show this isn't a scenario-specific hack —
the same evidence-over-hypothesis policy holds across different domains
and different misleading claims.

---

## 4. Recommended vs. rejected actions, and the policy boundary

Look at any of the three reports above and point at the execution marks:

- `✓` = **AUTO** — internal, low-risk, reversible (issue creation,
  notifications, investigation tasks)
- `△` = **APPROVAL_REQUIRED** — customer-facing or config-changing
  (reauthorization requests)
- (not seen in these examples, but defined) `⛔` = **HUMAN_ONLY** —
  destructive, irreversible, or security-sensitive

This mapping lives in `services/recommendations.py`, not in a prompt.
No LLM call can move an action from HUMAN_ONLY to AUTO — the execution
class is a property of the action itself, decided by code.

---

## 5. Arcade: connecting reasoning to real systems

The five tools above (`generate_ticket`, `validate_ticket`,
`enrich_ticket`, `route_ticket`, `recommend_actions`) are exposed as MCP
tools by `server.py` and deployed to Arcade Cloud. Once connected:

```bash
arcade connect claude-code --server SupportAutomation \
  --tool Linear.CreateIssue --tool Slack.SendMessage
```

an agent can walk the same pipeline you just ran on the command line, and
then — for the two AUTO-tier actions above — actually call
`Linear.CreateIssue` and `Slack.SendMessage` through Arcade's own OAuth,
without this server ever holding a Slack or Linear token. If you have a
live gateway connected, run the hero ticket through Claude Code/Claude
Desktop and let it call the tools live; if not, narrate the flow from the
CLI output — the pipeline output is identical either way, since the MCP
tools are thin wrappers over the exact same service functions
(`tests/test_mcp_server.py` proves this by invoking all five tools through
Arcade's own `ToolExecutor`).

```
ticket → validate_ticket → enrich_ticket → route_ticket → recommend_actions
       → Linear.CreateIssue   (internal investigation issue)
       → Slack.SendMessage    (notify support engineering)
```

Note what's *not* in that chain: no customer-facing message is ever sent
automatically. `request_google_reauthorization` stays at △ — a human has
to approve it — by design, not by omission.

**If you're running this live rather than narrating it:** the gateway
login (`authenticate`/`complete_authentication`) only grants tool
*discovery* — `Linear.CreateIssue` and `Slack.SendMessage` each need their
own separate OAuth consent the first time they're actually called. Batch
that ask up front with `System_ManageAuthorization(action="authorize",
tools=["Linear_CreateIssue", "Slack_SendMessage"])` so the user authorizes
both services once instead of hitting a consent screen mid-demo. Also:
`identity-integrations` and `support-engineering` are this repo's policy
names, not real Linear/Slack targets — `Linear.CreateIssue` needs an
actual team and `Slack.SendMessage` needs an actual, already-existing
channel in whatever workspace you've connected. Check with
`Arcade_ListApps` or just try the call — both tools return the real
available teams/channels on a "not found" error — and confirm the target
with whoever's driving the demo before you create a real issue or post a
real message.

---

## Closing point

Three things happened across these runs, and none of them were an LLM
guessing:
1. A ticket with no evidence got flagged as not automation-ready.
2. A ticket with strong evidence and a wrong customer hypothesis got
   routed and assessed correctly anyway — and the system said, in its own
   output, what it refused to blame.
3. Every one of those decisions came with `reason_codes` and evidence,
   not a bare classification.

**AI reasons. Policy decides. Humans retain control of high-risk actions.**
That's the whole system.
