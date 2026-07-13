# V3.0.80 Final Review Round 3 Findings

Review range: `94bdadc..98cdaa6`
Verdict: `BLOCK`

## Binding Constraints

- Current deployed production remains `V3.0.79`; `V3.0.80` remains pending.
- No Medium finding may remain before packaging or deployment.
- No formal task, group, terminal, meter, or match key may use placeholder identities.
- Release source and package truthfulness must be fail-closed.
- Fix every finding below with focused RED/GREEN evidence.

## Finding 1: JSON legacy unmatched assign can create a placeholder formal task (Medium)

`assign_unmatched_record()` passes the unmatched record terminal directly to `ensure_task_for_terminal()` without formal identity validation. A read-only probe assigned a record with `terminal=00000000`, created a published formal task, and wrote update/assignment audit events. `manual-*` and `unmatched-*` are affected too.

Validate before any unmatched, task, summary, audit, or persistence mutation, or prohibit legacy unmatched assignment from creating formal tasks. Add JSON repository and real HTTP tests for `00000000`, `未关联终端`, `manual-*`, and `unmatched-*`. Assert rejected task, unmatched, summary, audit, and persisted file state are unchanged.

## Finding 2: release truth parser still has bypasses and false positives (Medium)

These pending claims are not rejected:

```text
V3.0.80 was not deployed yesterday and was deployed today.
V3.0.80 昨日未部署并于今日已部署。
V3.0.80

has been deployed to production.
```

`V3.0.80 hasn't been deployed` and `was not currently deployed` can be misclassified as affirmative. Explicit claims such as `is now live in production` and `生产部署已完成` are not recognized.

Build version context across the complete document while preserving dots in version numbers. Evaluate negation at semantic clause scope across conjunctions, contractions, paragraphs, and English/Chinese deployment synonyms. Add focused adversarial tests for every example and pure negative/pending/future controls.

## Finding 3: package verifier accepts forged version and deployment truth (Medium)

`verify-client-release.py` allows a manifest without `Version`, skips static version checks in that case, and only checks that `ops/releases/V3.0.80.md` exists. A forged archive containing all required files, no manifest version, packaged AGENTS claiming V3.0.80 deployed, and a `Status: deployed` record without evidence is accepted.

Require the package version and require it to agree with the packaged static version. Parse packaged `AGENTS.md` markers and the candidate release record with the shared truthfulness parser. Before deployment, the packaged record must remain pending and may not contain unsupported deployment claims. Add forged-archive negative tests for missing/mismatched version, contradictory markers, deployed status without evidence, and affirmative prose bypasses.

## Finding 4: PostgreSQL concurrent first finalization can create duplicate terminal tasks (Medium)

Finalization serializes by `(project_id, meter_match_key)`, but `_ensure_task_for_terminal()` uses a query-then-insert sequence without a terminal-scoped lock or `(team_id, terminal)` uniqueness. Two different meter keys for the same terminal can therefore create two formal tasks and split groups/KPI.

Serialize task creation with a stable `(team_id, terminal)` PostgreSQL transaction advisory lock or a database uniqueness/upsert design. Lock ordering must be deterministic and must not create a new deadlock. Add a real PostgreSQL concurrency/materialization regression for the same terminal with different meter keys, proving exactly one task is created and both groups reference it.

## Required Verification

- Focused RED/GREEN for all four findings.
- Real HTTP rejected-assign tests proving no state/audit/persistence mutation.
- Full adversarial release parser and forged package tests.
- Real PostgreSQL same-terminal/different-meter concurrent finalization coverage, not only mocked helper calls.
- Full `v2-api/tests`, release/package verifier tests, frontend build, UI/security/release gates, and `git diff --check 94bdadc..HEAD`.
- No generated `v2-api/app/static/vue` assets committed.
- Worktree clean and candidate still pending.
