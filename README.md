# jason-skills

Skills I use for day-to-day project maintenance, mostly on [cc-switch](https://github.com/farion1231/cc-switch).

| Skill | What it does |
|---|---|
| [jason-review](jason-review/SKILL.md) | Evidence-first PR review: purpose, approach, a quantified necessity verdict, then a deep review with merge-tree verification. Runs an independent Codex review in parallel when the Codex CLI is installed. |
| [jason-post-review](jason-post-review/SKILL.md) | Turns a review verdict into a GitHub review comment, shows the draft, and posts it only after confirmation. |
| [jason-pr-triage](jason-pr-triage/SKILL.md) | Syncs PRs into a private local ledger, batch-classifies them by category and priority, and prints action queues (merge-ready, re-verify, to-review, to-thank…). |
| [jason-issue-triage](jason-issue-triage/SKILL.md) | Syncs issues into a private local ledger, batch-triages them into verdicts and root-cause groups, and answers "which issues does this release fix". |
| [jason-update-model](jason-update-model/SKILL.md) | Audits the built-in model pricing table against models.dev and helps add a newly released model's price. |
| [jason-run-workload](jason-run-workload/SKILL.md) | Drives a real AI coding client through the cc-switch local proxy on a fixed task set (bundled `fixture/`) to generate real conversion-layer traffic. |

## Built for Claude Code

These skills are written for [Claude Code](https://claude.com/claude-code). Each one is a folder with a `SKILL.md`; copy the folder into `.claude/skills/` of your project (or `~/.claude/skills/`) and invoke it as `/<skill-name>`.

They lean on Claude Code features, so using them with another coding agent takes some adapting:

| Claude Code feature | Used by | What to change elsewhere |
|---|---|---|
| Workflow scripts (`triage-workflow.js`: `agent()` / `pipeline()`) | pr-triage, issue-triage | Run the batches as plain parallel sub-tasks, or triage inline one batch at a time |
| Subagents pinned to a model (Opus) | review, pr-triage, issue-triage | Use your agent's sub-task mechanism, or do it in the main session |
| Background commands with completion notifications | review (parallel Codex run) | Start the command in the background and poll for the output file |
| Session scratchpad directory | review, post-review, run-workload | Any temporary directory |
| Memory directory (`~/.claude/projects/<project>/memory/`) | review, post-review, pr-triage | Point it at wherever your agent keeps notes, or drop the memory steps |
| Skill frontmatter (`argument-hint`) and `/jason-*` cross-references | all | Follow your agent's own skill or prompt format |

The shell scripts (`sync.sh`, `audit.py`) and the `fixture/` project are plain bash / Python and work anywhere.

## Other notes

- The triage skills keep their ledgers in `~/.cc-switch-triage/`, outside any repository; nothing in that directory is published here.
- These skills are written for my own setup. Some paths (for example the cc-switch checkout location) are hardcoded and need adjusting before reuse. `audit.py` expects to live at `<repo>/.claude/skills/jason-update-model/`.
