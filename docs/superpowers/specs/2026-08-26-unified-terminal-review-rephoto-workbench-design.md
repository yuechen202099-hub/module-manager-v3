# Unified Terminal Review and Re-photo Workbench Design

**Target release:** V3.2.10

**Production baseline:** V3.2.9 source commit `f02f5e7229918f5d8e4b7412dc18c5405cc50049`; the feature lineage began on V3.2.8 commit `4c69dd7584d6c0d7fcf6a90f43560165577eeef0` and carries the V3.2.9 Quagga-first scanner source/tests forward.
**Status:** approved approach A; pending written-spec review

## Goal

Restore the old review-workbench interaction as the single administrator workflow for terminal data review and customer-platform re-photography. An administrator searches by terminal number, reviews every constructed meter on the terminal in one page, and unlocks re-photography only when every constructed meter is review-ready. Unconstructed meters remain visible for context but never block or create re-photography work.

## Confirmed Decisions

- Use one integrated page rather than a review dialog plus a separate collector workbench.
- Restore the old three-column review-workbench interaction, but use current production APIs and persistence rather than the obsolete mock `workspace` store.
- Lock re-photography at terminal scope.
- Only constructed meters participate in the lock. Unconstructed meters do not block re-photography.
- Every constructed meter must be review-ready before any re-photography or collector replacement action is enabled.
- Each constructed meter exposes exactly two new-install positions: `module_meter` (电表和模块) and `after_box` (改造完成).
- Collector removals are de-duplicated at terminal scope. A collector shared by several meters appears once.
- Same-number physical collectors remain direct, photo-free inventory confirmations. Missing collectors may use audited random one-time replacement.
- Only administrators can see or call the integrated review/re-photo workflow.
- Constructor accounts have only the construction collection page. They cannot see or directly open review, re-photo, collector inventory, project, data-center, account, or sync pages.
- V3.2.9 remains immutable. This change ships as a new V3.2.10 release and never overwrites the deployed V3.2.9 directory, package, tag, branch, or release record.

## Non-goals

- Do not change the customer platform or send requests to it.
- Do not automate camera capture from the desktop re-photo page.
- Do not invent source photos for incomplete groups.
- Do not duplicate collector removal work per meter.
- Do not reintroduce project, run, or batch selection.
- Do not reuse consumed pool collectors or mutate historical assignments/photos.
- Do not add a database migration unless implementation proves that the existing material-group, photo, verification, and collector-transfer records cannot represent the required state.

## Existing Components to Reuse

- `DataCenterReviewDialog.vue` contains the current production review behavior: protected image loading, photo classification, field correction, barcode rescan, region scan, manual confirmation, exception return, and review reset.
- `ReviewView.vue` contains the retired three-column visual structure, but its `workspace` store and group/task APIs are obsolete and must not become authoritative again.
- `CollectorWorkbenchView.vue` contains the V3.2.9 global terminal picker, fixed two-slot meter display, present/missing/replaced collector states, atomic replacement, rollback, completion, and stale-response handling.
- `PostgresCollectorTransferService` contains bounded terminal paging, source projection, hidden single-terminal snapshots, tenant checks, collector de-duplication, allocation locking, and audit behavior.
- Existing group review persistence (`MaterialGroup.status`, `reviewed_at`, review/barcode/photo data) is sufficient; V3.2.10 should remain on Alembic head `20260824_0016`.

## Authoritative Workflow State

### Meter construction state

Construction state is derived from authoritative active source-photo evidence, not from a client flag:

- `unconstructed`: the group has no active source photo evidence and no persisted construction-photo count.
- `constructed`: the group has at least one active source photo or a positive persisted construction-photo count. This includes groups whose review status is `unreviewed`, `in_review`, `incomplete`, `approved`, or `rejected`.

This intentionally differs from the current data-center label that can call an unreviewed photographed group `in_progress`. For this workbench, photographed work is constructed and therefore must be reviewed before re-photography.

### Meter review readiness

A constructed meter is `review_ready` only when all server-side conditions are true:

1. `MaterialGroup.status == GroupStatus.APPROVED`.
2. Terminal number and meter number are nonblank and non-placeholder values.
3. Module number is nonblank after applying the existing module-number precedence rules.
4. Exactly one active `module_meter` source photo and one active `after_box` source photo are selected by the existing photo-precedence rules; missing, duplicate, or conflicting slots block readiness.
5. Photo classification is complete for the selected source evidence.
6. Durable barcode verification is passed or manually confirmed for the current evidence version.
7. There is no open exception, address conflict, or source diagnostic that makes the group unsafe to re-photograph.

An administrator may classify photos, correct fields, rescan, use region scan, manually confirm, approve, mark incomplete, or return an exception from the same page. Approval alone cannot bypass missing source evidence; the terminal gate recomputes all conditions from the database after every mutation.

### Terminal workflow state

The server partitions every terminal candidate into `constructed_meters` and `unconstructed_meters`, then derives one state:

- `no_construction`: zero constructed meters. The page shows context only and creates no hidden run or re-photo items.
- `needs_review`: at least one constructed meter is not `review_ready`. The page shows review controls; every re-photo, collector replacement, rollback, completion, and snapshot-refresh mutation is locked.
- `blocked`: identity, address, source, or cross-project ambiguity prevents a safe terminal projection.
- `needs_replacement`: all constructed meters are review-ready and at least one de-duplicated collector has no same-number physical item.
- `pool_shortage`: all constructed meters are review-ready, but the eligible random pool cannot cover every missing collector atomically.
- `ready`: all constructed meters are review-ready and every collector is direct-ready or replaced.
- `in_progress` / `completed`: the existing hidden snapshot has progressed or completed.

Unconstructed meters are returned with `construction_state="unconstructed"`, displayed in a muted list section, excluded from readiness counts, excluded from source revision for re-photo work, and excluded from meter/collector requirements.

## Server Architecture

### Pure domain projection

Add a pure terminal review projection beside the collector-transfer domain helpers. It consumes selected material-group/photo/verification rows and produces:

- constructed/unconstructed classification;
- per-meter review state and exact blockers;
- the constructed-only source revision;
- terminal workflow state;
- the exact set of meter and de-duplicated collector requirements.

The collector-number, module-number, photo-precedence, trimming, leading-zero, and arbitrary-text rules must be shared with the V3.2.8 projection rather than duplicated.

### Bounded service query

Extend the bounded global terminal query so each candidate includes:

- `constructed_meter_count`;
- `unconstructed_meter_count`;
- `review_ready_count`;
- `review_required_count`;
- `workflow_state` including `no_construction` and `needs_review`;
- a readable label and opaque internal `terminal_key` as separate fields.

The terminal detail query loads selected columns for one authenticated-team terminal only. It returns all meter review rows, but it passes only constructed and review-ready rows into the collector-transfer snapshot builder.

### Unified open contract

Introduce an administrator-only unified open endpoint under the existing collector-transfer router:

```text
POST /collector-transfer/review-workbench/terminals/open
```

Request fields:

```json
{
  "terminal_key": "opaque internal key",
  "source_revision": "candidate revision"
}
```

Response shape:

```json
{
  "terminal": {},
  "workflow_state": "needs_review",
  "source_revision": "...",
  "constructed_meter_count": 2,
  "unconstructed_meter_count": 1,
  "review_ready_count": 1,
  "review_required_count": 1,
  "review_blockers": [],
  "meters": [],
  "rephoto": null
}
```

When the terminal is `needs_review`, `blocked`, or `no_construction`, `rephoto` is null and no hidden collector-transfer run is created. When every constructed meter is review-ready, the same endpoint creates or reuses the immutable single-terminal hidden run and returns the existing meter-install, collector-removal, pool-summary, completion, and source-change detail under `rephoto`.

Existing review mutations remain group-scoped and audited. After each mutation the client reopens the terminal with a new request serial. Existing collector mutations remain terminal/item scoped, but every mutation must recheck the constructed-only review gate before locking or mutating collector state.

### Concurrency and stale evidence

- `terminal_key` is an identifier, never an authorization token. The server revalidates authenticated `team_id`, project, and terminal on every request.
- Review changes update the constructed-only source revision.
- If an unprogressed hidden run exists and review/source evidence changes, it may be superseded and recreated using the existing safe-release rules.
- If a progressed run exists and evidence changes or a constructed group becomes non-ready, the server returns `source_changed=true`, locks further mutations, and requires administrator refresh/rollback according to current assignment safety rules.
- Review readiness is checked inside the same canonical lock order used before allocation, rollback, completion, and refresh. Pool shortage remains all-or-nothing with zero mutations.

### Stable errors

Use stable API errors without leaking cross-team existence:

- `terminal_not_found` — no selectable terminal for the authenticated team;
- `terminal_has_no_constructed_meter` — context exists but no re-photo work can be created;
- `terminal_review_required` — one or more constructed meters are not ready;
- `terminal_source_changed` — client revision or progressed snapshot is stale;
- existing pool-shortage, permission, replacement, rollback, and completion errors remain unchanged.

`terminal_review_required` returns safe group IDs and blocker codes for rows already present in the authorized terminal detail. Cross-team and cross-project rows are never returned.

## Frontend Architecture

### Canonical page and route compatibility

Create `ReviewRephotoWorkbenchView.vue` as the canonical `/review-workbench` page and navigation item titled `审阅与翻拍工作台`.

Compatibility redirects:

- `/collector-workbench` -> `/review-workbench`;
- `/collector-batches` -> `/review-workbench`;
- `/review/:groupId` -> `/review-workbench?group_id=:groupId`;
- existing saved global-search review links continue opening the data-center dialog and are not broken.

Retire `CollectorWorkbenchView.vue` only after the unified page owns all tested terminal search, replacement, rollback, meter completion, and stale-response behaviors.

### Restored three-column interaction

The unified desktop page restores the useful old review-workbench layout:

1. **Left — terminal meter queue:** constructed meters first with review status and blockers, then muted unconstructed meters labeled `未施工，不参与本次翻拍`.
2. **Center — evidence/re-photo stage:** while locked, show the active meter's protected source photo and inspector; after unlock, show its two fixed re-photo positions with meter/module barcodes.
3. **Right — review/action panel:** fields, category actions, rescan, region scan, manual confirmation, final approve/incomplete/exception actions, audit summary, and terminal lock status.

A terminal-level collector section appears below the meter workspace after review unlock. It shows each de-duplicated collector once in `present`, `missing`, or `replaced` state, with the existing random replace/rollback controls and barcodes/photos.

The page never calls a camera API. It presents source material for a handheld device to re-photograph into the customer platform.

### Unlock behavior

- The UI never unlocks from locally edited fields.
- After the final required meter mutation, it reloads the unified terminal response.
- Only a server response with a non-null `rephoto` block enables replacement, meter completion, collector completion, or navigation through re-photo items.
- If another administrator changes the source while the page is open, request serials discard late responses and the next server response returns to the locked review state.

## Authorization

- `/review-workbench` and every unified/open/collector-inventory/collector-workbench API require administrator authentication.
- Constructor navigation contains only `/construction` plus login/logout account chrome.
- Direct constructor navigation to an administrator page redirects to `/construction`.
- Direct constructor API calls to review, collector inventory, terminal open, replacement, rollback, refresh, and completion return HTTP 403 before any query or mutation.
- Administrator access to `/construction` remains available for support.
- Existing production reviewer compatibility endpoints may remain for legacy review links, but they do not grant access to the unified terminal or collector APIs.

## Data Integrity and Audit

- Original material groups, source photos, total-catalog data, historical review audit, collector photos, assignments, and scan events remain immutable except through their existing audited mutation services.
- Direct same-number collectors never receive a fake website photo and never enter the random pool.
- Random pool collectors remain team/project scoped and are consumed once.
- A collector shared by several constructed meters creates one requirement and one workbench item.
- Unconstructed groups create no meter item, collector requirement, assignment, or workbench item.
- Every approval, incomplete/rejected decision, field correction, photo classification, manual confirmation, replacement, rollback, refresh, and completion retains actor/time/before/after audit evidence.

## Testing Strategy

### Domain and service tests

- Constructed/unconstructed partitioning for mixed terminals.
- Unconstructed rows neither block nor enter source revision/requirements.
- Any non-ready constructed meter locks the entire terminal.
- A final review approval unlocks all constructed meters only after exact evidence revalidation.
- Zero constructed meters creates no run.
- Collector de-duplication across multiple constructed meters remains one-to-one.
- Review/source changes before and after snapshot progress preserve current supersede/source-changed safety.
- Bounded candidate/detail query count and no source ORM materialization regression.
- Team/project isolation and canonical lock ordering under PostgreSQL concurrency.

### API tests

- Unified candidate/open DTOs for mixed, locked, ready, shortage, and blocked terminals.
- `rephoto=null` and zero hidden-run mutation while review is required.
- Stable 409 errors for server-side review rechecks on every collector mutation.
- Constructor receives 403 for every unified/review/collector API before repository work.
- Administrator behavior and legacy redirects remain valid.

### Frontend tests

- Terminal search displays readable labels while submitting the opaque key.
- Constructed and unconstructed meter sections render separately.
- One incomplete constructed meter disables every re-photo and collector mutation.
- Unconstructed meters do not appear in re-photo item counts.
- Final server-confirmed approval switches the same page from review to re-photo mode.
- Review inspector cleanup, object URL cleanup, abort behavior, and late-response guards.
- Exactly two meter slots and one de-duplicated collector section.
- Existing atomic replacement, rollback, completion, shortage, and stale-source behaviors.
- Constructor navigation contains only construction and direct forbidden routes redirect.
- Desktop and 390x844 responsive rendering, with no camera request from the unified page.

### Release verification

- Focused backend and frontend matrices, PostgreSQL concurrency tests, type-check, production build, and full repository suite must finish with explicit zero-failure summaries.
- Rebuild tracked Vue assets from the final source commit.
- Build a new source-bound V3.2.10 ZIP; verify `SOURCE_COMMIT`, manifest bytes, CRC/path/case/duplicate rules, Vue asset binding, V3.2.9 scanner-regression markers, and forbidden files.
- Never package `v2-api/uv.lock`, `.env`, uploads, backups, caches, or repository metadata.

## Production Rollout and Rollback

- Deploy V3.2.10 to a new immutable release directory; never overwrite V3.2.9.
- Capture a fresh local streamed backup and exact V3.2.9 rollback directory immediately before cutover.
- Keep maintenance services in their captured state until listener, health, version, route, authorization, read-only mixed-terminal, and real-browser acceptance pass.
- Wait for a real Uvicorn listener on `127.0.0.1:8000`; systemd `active` alone is insufficient.
- Production acceptance uses authenticated read-only terminals unless a designated test terminal is explicitly approved. It must not approve a real group, allocate a real collector, or complete a real re-photo item.
- Verify an administrator can see the unified page and a constructor can see only construction.
- Verify old URLs redirect to `/review-workbench` and the page makes no customer-platform network request.
- Roll back atomically to the captured V3.2.9 release on listener, health, authorization, data-integrity, or workbench failure.

## Acceptance Criteria

The change is complete only when all of the following are proven:

1. An administrator can search a terminal and see every meter on one page.
2. Unconstructed meters are visibly excluded and do not block or create re-photo work.
3. Every constructed meter must be server-confirmed review-ready before the terminal unlocks.
4. All constructed meters then expose exactly the two approved new-install positions.
5. Terminal collectors are de-duplicated and retain direct/missing/replaced behavior.
6. Review, random replacement, rollback, and completion remain audited and tenant-safe.
7. Constructor accounts can access only construction collection and receive 403/redirect elsewhere.
8. Legacy review/collector/batch URLs converge on the unified administrator workflow without breaking data-center saved links.
9. V3.2.10 passes local, package, browser, production, rollback, and requirement-by-requirement verification without regressing the V3.2.9 inventory scanner hotfix.
