# V3.0.80 Final Review Round 2 Findings

Review range: `94bdadc..7cb82bb`
Verdict: `BLOCK`

## Binding Constraints

- Current deployed production remains `V3.0.79`; `V3.0.80` remains a pending candidate.
- No High or Medium finding may remain before packaging or deployment.
- No formal terminal, meter, task, or group mutation may create or persist `00000000`, `未关联终端`, `manual-*`, or `unmatched-*` placeholder identities.
- JSON, PostgreSQL, and supported dual mode must not deadlock or silently diverge.
- Fix every finding below with focused RED/GREEN tests before running the full suite.

## Finding 1: dual HTTP unmatched-review writes deadlock (High)

`persist_local_test_state` in `v2-api/app/main.py` begins and activates an authoritative JSON transaction for every JSON/dual write. `DualWriteStateRepository._strict_unmatched_review_write()` then unconditionally begins another transaction for the same team. The lock is a non-reentrant `threading.Lock`, so save, rescan, confirm, and finalize hang.

A read-only 5-second probe reproduced `DEADLOCK_PROBE_TIMEOUT`: begin and activate an outer transaction for one team, then call `_strict_unmatched_review_write()` for the same team.

Add real FastAPI `STATE_BACKEND=dual` HTTP RED tests for save, rescan, confirm, and finalize. Reuse an already active same-team transaction and make only its creator responsible for finish/abort. Do not treat changing the lock to `RLock` as sufficient.

## Finding 2: PostgreSQL commit can survive JSON persistence failure (High)

The strict dual path mutates JSON working state, calls PostgreSQL methods that commit internally, and only then persists JSON. If JSON atomic persistence fails, PostgreSQL advances to N+1 while JSON stays at N. Retry is stale and the backends remain split.

Add failure-injection RED tests for save, rescan, confirm, and finalize. Prove an injected JSON persistence failure leaves both backends unchanged or enters a durable, automatic recovery path that restores consistency before another write can succeed. Do not swallow the error or return success. Use a coordinated transaction/recovery design; if dual cannot be made safe, fail fast before either backend mutates and explicitly enforce that behavior.

## Finding 3: release truthfulness parser still has prose bypasses (Medium)

The verifier ignores an entire line when any negation token appears and requires a version plus deployment claim on the same line. These contradictory claims can pass with pending status:

```text
V3.0.80 was not deployed yesterday; V3.0.80 was deployed today.
V3.0.80
has been deployed to production.
V3.0.80 尚未部署的记录已过时；V3.0.80 已部署。
```

Parse negation at clause scope and scan complete paragraphs, including cross-line English and Chinese claims. Add focused adversarial tests.

## Finding 4: existing mutations can still persist placeholder formal identity (Medium)

The administrator terminal update route does not apply the shared formal identity validator; PostgreSQL only rejects blank values. The metadata update route allows a reviewer to mutate `meter_no` and `meter_match_key` directly. These paths can create `00000000`, `未关联终端`, `manual-*`, or `unmatched-*` formal identities.

Apply the shared formal identity validation to every formal identity create/update entry point. Formal meter and match-key changes must be administrator-only. Add JSON, PostgreSQL, and API tests proving rejected writes leave business state and audit unchanged.

## Finding 5: camelCase audit fields bypass recursive redaction (Medium)

The audit redactor lowercases and replaces hyphens but does not split camelCase. Fields such as `signedUrl`, `rawUrl`, `storageKey`, `objectKey`, `ossKey`, and `storageBucket` survive persistence and response redaction.

Canonicalize camelCase and mixed-case keys before matching secret tokens. Add nested persistence-before and response-after tests for JSON and PostgreSQL audit paths.

## Finding 6: retired rematch API service remains (Low)

`v2-web/src/api/services.ts` still exports `rematchUnmatchedRecord()`, which calls the retired production `/rematch` route. Remove the service and any associated type if unused, and extend the unmatched UI verifier so it cannot return.

## Required Verification

- Focused RED/GREEN evidence for all six findings.
- Real FastAPI dual HTTP tests, not repository-only tests.
- Failure-injection coverage for JSON persistence after PostgreSQL staging.
- Full `v2-api/tests`, release verifier tests, frontend build, unmatched UI verifier, security verifier, release SOP verifier, and `git diff --check 94bdadc..HEAD`.
- No generated `v2-api/app/static/vue` assets committed.
- Worktree clean and `V3.0.80` still pending after the fix.
