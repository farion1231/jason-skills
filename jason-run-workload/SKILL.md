---
name: jason-run-workload
description: Drive a real AI coding client through the cc-switch proxy on a fixed task set, generating real conversion-layer traffic — tool calls, multi-turn history, cache reads. Works with any proxied client that has a headless CLI (codex/claude/gemini/opencode/...). The skill only runs the workload and reports task outcomes + the time window; the user observes errors and cache hit rate in the usage dashboard themselves.
argument-hint: "[client] [rounds] — client to drive (ask if omitted); rounds of the task sequence (default 4)"
---

# Run Workload

Generate **real agentic traffic** through the cc-switch proxy so conversion-layer changes
can be observed under genuine load. Real traffic (real tool schemas, real multi-turn
history, naturally growing prompt prefixes) exercises the bridges in ways synthetic
probes cannot.

This skill **only runs tasks and reports task outcomes + the time window**. It does NOT
query the database, compute cache-hit rates, or judge the numbers — observation belongs
to the user, in the cc-switch usage dashboard.

Client choice = bridge choice. `$ARGUMENTS` names the client; **if empty, ask the user
which client/bridge to exercise** — don't assume a default. Known mappings:

| Client | Proxy entry | Conversion path exercised |
|--------|-------------|---------------------------|
| `codex` | `/v1/responses` | Responses ↔ upstream (Chat / native Messages) bridge |
| `claude` | `/v1/messages` | Anthropic Messages entry (incl. Messages → Responses/Chat upstream) |
| `gemini` | `/gemini/v1beta/*` | Gemini bridge |

Any other proxied client with a headless mode (opencode, hermes, ...) works the same
way — the client only needs to run the fixed tasks below while its traffic flows through
the proxy.

## Steps

### 1. Preflight (keep it to two commands)

```bash
curl -sf http://127.0.0.1:15721/health   # proxy alive?
command -v <client>                       # client CLI installed?
```

If either fails, stop and tell the user (start proxy takeover in cc-switch / install the
client). If the user runs the proxy on a non-default port, they'll say so — don't go
hunting for it.

### 2. Sandbox (one per round)

The workload runs the task sequence for **multiple rounds** — default 4. Calibration
after the 2026-07-20 reshape (codex + third-party grok-4.5, no compact step, codex's
own "tokens used" counter): two same-day runs on different channels of the same relay
measured ≈0.07M and ≈0.25–0.32M tokens/round — a 4× spread, so treat per-round volume
as provider-specific and recalibrate per run; dashboard raw tokens ≠ client counter.
The user can pass a different round count as the second argument.

Each round gets its **own fresh** sandbox copied from the bundled `fixture/` directory
(next to this SKILL.md): `<scratchpad>/minishop-run-1`, `minishop-run-2`, … Always start
from a pristine copy — a byte-identical starting state is what makes rounds and
before/after runs comparable. Never run the client anywhere else.

Then `git init` the sandbox and commit the baseline (some clients, e.g. codex, refuse to
run in a non-git directory):

```bash
git init -q && git add -A && git -c user.email=fixture@local -c user.name=fixture commit -qm "fixture baseline"
```

The fixture ships with exactly 6 deterministic bugs (25 tests: 19 pass, 4 fail + 2
errors), so Task 2 has an objective success criterion.

### 3. Record the start time

`date '+%Y-%m-%d %H:%M:%S'` — this bounds the observation window.

### 4. Run the task sequence (repeat per round)

Run inside the round's sandbox, in order, with these **exact prompts** (fixed prompts
keep runs comparable; don't reword them). Rounds run **sequentially, never in
parallel** — `resume --last` style flags grab the most recent session, which breaks
under concurrency:

| # | Session | Prompt |
|---|---------|--------|
| T1 | new session | `Read every file in this project and write NOTES.md summarizing what each module does and how they interact.` |
| T2 | new session | `Run python3 -m unittest -v. Fix all failing tests by fixing bugs in the source modules - do not modify test_minishop.py. Re-run the suite until it fully passes.` |
| C | **resume T2's session** | the literal string `/compact` — the client's built-in compact command, not a task prompt (claude only for now; codex must skip, see below) |
| T3 | **resume again** (same session, now compacted) | `Add one more unit test for an edge case you consider untested, then make sure the whole suite still passes.` |

T3 must resume T2's session — session resume replays the full accumulated history through
the bridge, which is where history-conversion bugs (id mapping, orphaned reasoning items)
live. The compact step in between makes T3 replay a *compacted* history: summary items
and an abruptly changed prompt prefix are exactly the shapes conversion layers get wrong.
Compaction also naturally lowers the absolute cache-hit number — expected, and one more
reason numbers only compare within the same workload shape. If the compact command
reports the session is too short (e.g. claude's "Not enough messages to compact."),
record that in the report and continue with T3 anyway.

Per-client commands (cwd = sandbox):

| Client | New session | Resume |
|--------|-------------|--------|
| codex | `codex exec --dangerously-bypass-approvals-and-sandbox "<prompt>" </dev/null` | `codex exec resume --last --dangerously-bypass-approvals-and-sandbox "<prompt>" </dev/null` |
| claude | `claude -p --dangerously-skip-permissions "<prompt>"` | `claude -c -p --dangerously-skip-permissions "<prompt>"` |
| gemini | `gemini --yolo -p "<prompt>"` | no reliable resume — run T3 as a new session, skip the compact step, note both in the report |

The compact step is the resume command with `/compact` as the prompt, and it only counts
if the CLIENT executes it (claude does: the CLI itself prints a status line such as "Not
enough messages to compact."). ⚠️ codex exec does NOT support `/compact` — the string
reaches the model as a plain prompt, and models MIMIC compaction (Grok replied "Context
compacted." while the rollout contained no compaction record; verified 2026-07-20). Skip
C for codex and note it. For any client, verify via the session/rollout file — never
trust stdout alone, models imitate command output.

For a client not in this table, find its equivalents via `<client> --help` before
running: non-interactive/headless run, auto-approve mode, and session resume. If it has
no resume, run T3 as a new session, skip the compact step, and note the weaker
history-replay coverage in the report.

If a resume flag errors, check `<client> --help` for the current syntax before falling
back to a new session. Give each task up to 15 minutes; kill and mark failed beyond that.

### 5. Record the end time, then report

The report is the skill's entire output:

- **Per round × per task, pass/fail on the objective criterion** — T1: `NOTES.md` exists
  and is non-empty; T2: `python3 -m unittest` exits 0; C: client-verified compact
  outcome (compacted / too-short / skipped — see the caveat above); T3: suite still
  passes. Also note any
  client-side error/crash/hang observed mid-run.
- **The time window** (start – end), phrased as: filter the cc-switch usage dashboard to
  this window to inspect errors and cache hit rate for this run.

## Rules

- Auto-approve flags (`--dangerously-bypass-approvals-and-sandbox` /
  `--dangerously-skip-permissions` / `--yolo`) are acceptable **only because cwd is the
  disposable sandbox**. Never point the client at a real project. codex ≥0.149 removed
  `--full-auto`; do NOT substitute `--approve-for-me` — it adds automatic-review calls
  that pollute the traffic shape.
- This skill changes nothing: no cc-switch config, no provider, no live client config.
  It only generates traffic.
- Don't edit the fixture or the task prompts casually — comparability across runs is the
  whole point. If the fixture must change, tell the user prior baselines are invalidated.
