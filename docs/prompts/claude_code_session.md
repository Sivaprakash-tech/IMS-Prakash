# Claude Code prompt log — IMS build session

> Per submission rule 4: "All markdowns and prompts used to create this repository should be checked in."

This file captures the prompts used to drive Claude Code in building this repository. The implementation was driven by [`/CLAUDE.md`](../../CLAUDE.md) (the project-level system prompt) plus the conversational prompts below.

---

## Persistent context (always loaded)

The file at the repo root, [`CLAUDE.md`](../../CLAUDE.md), is the standing brief. It contains:

- Mission, deadline, audience profile.
- Decoded original assignment (rubric requirements).
- Tech stack lock-ins (FastAPI, Postgres+Timescale, Mongo, Redis, Streamlit).
- Repo structure to create.
- Critical implementation details (`POST /signals` contract, debouncer, State pattern, RCA gate, MTTR, backpressure).
- Build order (10 steps).
- Pitfalls to avoid.
- Definition of done.
- Style preferences (senior SRE).

That file is loaded automatically on every Claude Code invocation in this directory. Treat everything below as the *delta* over CLAUDE.md.

---

## Session prompts (chronological)

### Prompt 1 — kickoff

> read the CLAUDE.md file and assist me in building the UI and the remaining workflow which was asked to submit by 5th May 2026

Resolution: Claude Code asked two clarifying questions (existing code? full vs. UI-only build?) before writing anything.

### Prompt 2 — scope decision

> 1. This is from scratch, I don't know how to code to develop UI, I need help everything from you until the setup is complete as per the ask.
> 2. Full build

Resolution: full repo build, commit-by-checkpoint per CLAUDE.md's 10-step plan.

### Prompt 3 — assignment PDF reference

> @Engineering_Assignment__Incident_Management_System(1).pdf

Resolution: Claude Code read the PDF, confirmed alignment with CLAUDE.md, and noted two deviations to call out in README:
- Spec says "React, Vue, or HTMX" frontend; we use Streamlit (justified in README).
- Spec says `/backend` and `/frontend`; we use `/backend` and `/dashboard` (note in README).

### Prompt 4 — permissions

> Granting You full permissions on current folder/directory

Resolution: continued the build with full file/git permissions on `/home/vinod/inc-proj`.

---

## Build checkpoints (each = one git commit)

| # | Subject                                                                  |
|---|--------------------------------------------------------------------------|
| 1 | feat: initial repo skeleton with docker-compose and /health endpoint     |
| 2 | feat: postgres schema with TimescaleDB hypertable for signal_metrics     |
| 3 | feat: SQLAlchemy + Pydantic models, Postgres repo with tenacity retries  |
| 4 | feat: State + Strategy patterns with RCA gate inside state object        |
| 5 | test: pytest suite for RCA validator, state transitions, alerter, debouncer |
| 6 | feat: ingestion API with bounded queue, async workers, debouncer, throughput logger |
| 7 | feat: REST endpoints for incidents and RCA                               |
| 8 | feat: Streamlit dashboard with 3 tabs (Live Feed, Detail, RCA Form)      |
| 9 | feat: locust load file (10k/sec target) + simulate_outage cascade script |
| 10| docs: README, architecture, backpressure, prompts log                    |

Run `git log --oneline` to see the live history.

---

## How to reproduce this build with Claude Code

1. Drop `CLAUDE.md` (and optionally the assignment PDF) into an empty directory.
2. Open Claude Code in that directory.
3. Issue prompt 1 (or any equivalent kickoff). Claude Code will read CLAUDE.md and follow the 10-step plan.
4. Approve commits at each checkpoint.

The full repo can be regenerated from CLAUDE.md plus the four prompts above; no out-of-band guidance was needed.
