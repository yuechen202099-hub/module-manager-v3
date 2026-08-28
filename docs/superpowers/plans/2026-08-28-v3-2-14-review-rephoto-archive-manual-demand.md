# V3.2.14 Review/Re-photo Archive and Manual Collector Demand Plan

**Goal:** Keep the existing unified `/review-workbench` route while making constructed meter re-photo independent from classification completion, hiding completed re-photo items by default, and allowing an administrator to add an explicit collector demand quantity that is filled atomically from the current project's eligible collector pool.

**Baseline:** Tagged production `V3.2.13` at `bfb6958`; implementation branch `production/V3/3.2.14` in the existing linked worktree.

## Global Constraints

- Do not add a page, database migration, project/run/batch selector, or customer-platform integration.
- Do not mutate production PostgreSQL data or OSS objects during development or acceptance.
- Keep source collector photos optional for terminal re-photo; pool collectors remain eligible only when they have exactly one valid photo.
- Unconstructed rows, missing source collector numbers, and missing source collector photos do not block other constructed meter re-photo items.
- Manual demand uses existing requirement/allocation/workbench/audit persistence. Internal synthetic keys must never be displayed as collector numbers.
- Allocation is team/project scoped, one-time, duplicate-safe, auditable, rollback-compatible, and all-or-nothing when the pool is short.
- Completion retains status, actor, timestamp, and audit history, but completed meter or collector rows are absent from the default workbench list.
- All behavior changes follow test-first red/green verification. Commit only explicit task paths; never include secrets, data, uploads, real photos, backup files, `uv.lock`, or release ZIPs.

## Task 1: Relax terminal projection blockers without losing constructed evidence

**Files:**
- `v2-api/tests/test_terminal_review_domain.py`
- `v2-api/tests/test_collector_transfer_service.py`
- `v2-api/app/domain/terminal_review.py`
- `v2-api/app/services/collector_transfer.py`

1. Add failing domain/service tests proving unconstructed rows, a missing source collector number, and a missing source collector photo do not prevent valid constructed meter re-photo sources from opening.
2. Confirm each test fails for the intended old gate.
3. Make the minimal projection/open-path change so only safe constructed meter evidence drives `rephoto_sources`; preserve identity/address/source ambiguity blockers.
4. Run focused domain and service tests, then commit explicit paths.

## Task 2: Add audited manual collector demand and atomic random matching

**Files:**
- `v2-api/tests/test_collector_transfer_service.py`
- `v2-api/tests/test_collector_transfer_api.py`
- `v2-api/app/api/schemas/collector_transfer.py`
- `v2-api/app/api/routes/collector_transfer.py`
- `v2-api/app/services/collector_transfer.py`

1. Add failing tests for a positive requested quantity, current-project isolation, no duplicate physical collector use, pool-shortage zero mutation, audit creation, rollback compatibility, and authorization.
2. Introduce the smallest request/response contract and administrator route under the existing review-workbench/collector-transfer surface.
3. Represent manual demand through existing `CollectorRequirement.diagnostics` plus unique internal keys; expose a neutral `人工需求` label and never expose the internal key as a real collector number.
4. Reuse the existing canonical lock order and allocation transaction from terminal missing replacement; do not create a second allocation algorithm.
5. Run focused service/API tests, then commit explicit paths.

## Task 3: Reuse a corresponding source-group collector photo for present physical collectors

**Files:**
- `v2-api/tests/test_collector_transfer_service.py`
- `v2-api/app/services/collector_transfer.py`
- related response schema only if the existing workbench item photo contract cannot carry the source reference

1. Add failing service tests for a same-number `present` physical collector whose inventory record has no pool photo but whose corresponding constructed material group has one or more collector source photos.
2. Select one eligible source-group collector photo using deterministic existing photo precedence so repeated opens remain stable; when several meters/groups share the collector, any authorized matching group may supply the photo.
3. Expose that photo only as re-photo source material on the present collector workbench item. Do not create or mutate `CollectorPhoto`, do not admit the source photo to the random pool, and do not change the photo-free inventory rule for same-number physical confirmation.
4. Keep project/team isolation, protected image access, audit history, and existing random replacement eligibility unchanged. Run focused service tests and commit explicit paths.

## Task 4: Hide completed rows and add the compact manual-demand control

**Files:**
- `v2-web/src/views/ReviewRephotoWorkbenchView.vue`
- related `v2-web/src/**/*.spec.ts`
- `v2-web/src/api/services.ts`

1. Add failing frontend/API tests proving completed meter and collector items are not rendered after reopening, and quantity submission calls the new endpoint with the active terminal and positive integer quantity.
2. Filter completed items from the default computed lists while leaving persisted completion evidence untouched.
3. Add a compact integer input and `增加并随机匹配` button inside the existing collector section with shortage/error feedback and refresh-on-success.
4. Keep the selected present-collector source photo rendered through the existing lightbox contract.
5. Run collector frontend tests and type-check, then commit explicit frontend paths.

## Task 5: Prepare V3.2.14 runtime, release facts, and source gates

**Files:**
- runtime/web/manifest/SOP version files currently carrying `V3.2.13`
- `scripts/verify_v3_2_14_release.py`
- `scripts/test_verify_v3_2_14_release.py`
- generic package/SOP verifier tests only where the new version must be registered
- `ops/releases/V3.2.14.md`
- this plan file

1. Add/copy the V3.2.14 release verifier tests first and confirm they fail while source facts remain 3.2.13.
2. Update deployed production baseline references to `V3.2.13`, release candidate and branch to `V3.2.14` / `production/V3/3.2.14`, and every runtime/web/manifest/release-note fact to `3.2.14`.
3. Require the new backend/frontend tests and the V3.2.13 Android/scanner/re-photo regression markers; keep Alembic head `20260824_0016` and forbid migration/package secret/data changes.
4. Create `ops/releases/V3.2.14.md` with local/package/production fields pending. Do not invent hashes, commit IDs, backup paths, listener results, or attestation.
5. Run source verifier tests, the source phase, release SOP source phase, and `git diff --check`; commit explicit release paths.

## Task 6: Verify, review, package, deploy, and attest

1. Run focused backend/frontend tests, full relevant repository tests, type-check, production build, and rebuild tracked Vue assets.
2. Use the Browser plugin to validate `/review-workbench`: completed rows hide, manual quantity allocation refreshes authoritative state in a local disposable/test database, present collectors show the selected source-group photo, lightboxes work, and no camera/customer-platform request occurs.
3. Request independent whole-branch review; fix all Critical/Important findings and re-verify.
4. Build a source-bound immutable V3.2.14 ZIP, verify manifest/CRC/path/case/duplicates/static asset binding/forbidden files, and record local hash/evidence outside the repository.
5. Capture current production state and rollback release, take and verify a fresh backup, upload/hash-check into a new immutable release directory, and preserve `.env`, data, uploads, PostgreSQL, and OSS.
6. Atomically switch, wait for the real Uvicorn listener on `127.0.0.1:8000`, run local/public health, authenticated read-only admin/constructor acceptance, zero-write checks, and a short soak. Roll back immediately on failure.
7. Dry-run release retention and keep the newest five only if every listed target is an old release directory. Then write observed attestation, re-run attestation gates, commit/tag/push the V3.2.14 branch and tag.
