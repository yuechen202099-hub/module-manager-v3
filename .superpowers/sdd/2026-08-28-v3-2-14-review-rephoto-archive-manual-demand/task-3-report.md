# Task 3 Report: present collector source-photo reuse

## Implementation

`PostgresCollectorTransferService.global_terminal_detail` now selects an active
`Photo.category == "collector_barcode"` only through the current requirement's
`CollectorRequirementMeter` links. The query is constrained to the authenticated
team, active global-terminal run, terminal, project, and linked material group.
It orders by the existing terminal meter order and then `Photo.sort_order` / ID,
so a shared collector gets one deterministic source photo. The selected `Photo`
is returned only in the existing workbench item's `photo` response for a
`present` collector; it is not copied into `CollectorPhoto`, assigned, or added
to the pool. With no eligible source photo, the existing `None` response remains.

## Files changed

- `v2-api/app/services/collector_transfer.py`
- `v2-api/tests/test_collector_transfer_service.py`

## TDD evidence

### RED

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_collector_transfer_service.py::test_global_terminal_detail_reuses_authorized_source_photo_for_present_collector -q
```

Result before implementation: `1 failed, 1 warning in 1.38s`.
The expected failure was `TypeError: 'NoneType' object is not subscriptable` at
`present["photo"]["id"]`, proving a scanned, photo-free direct collector exposed
no corresponding constructed source photo.

The initial attempt with the system `python` could not collect the test because
it lacked `fastapi`; no code was changed until the repository `.venv` command
above produced the expected functional RED result.

### GREEN

Same focused command after the minimal service change:

```text
1 passed, 1 warning in 1.07s
```

The test uses two authorized same-number source groups, excludes a lower-order
inactive photo, verifies the first active source photo by deterministic order,
opens the detail twice for stability, and checks that the physical collector is
still `direct`, has no assignment, has no `CollectorPhoto`, and does not affect
the random-pool summary.

## Regression verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_collector_transfer_service.py -q
```

Fresh result: `132 passed, 1 warning in 7.60s`.

`git diff --check` completed without output. The only warning is the existing
Starlette `TestClient` deprecation warning from the environment.

## Self-review

- The source query joins only requirement-linked meter items and source groups;
  it cannot select an unrelated group merely because the collector number matches.
- Team, project, run, terminal, active status, and `collector_barcode` category
  are all explicit filters. `_photo_response` preserves the existing protected
  image-response path.
- The map keeps only the first ordered result per de-duplicated requirement.
- Random replacement still reads only `CollectorPhoto`; this change reads
  `Photo` and adds no write/audit/pool action.
- The existing direct-without-source assertion in
  `test_global_terminal_detail_projects_present_missing_and_replaced_collectors`
  remains green, covering the photo-empty fallback.

## Concerns

No implementation concern found. The source photo is live active material, not
a persisted `CollectorPhoto` snapshot; the existing source-change workflow is
unchanged. The only test-output concern is the pre-existing TestClient
deprecation warning noted above.
