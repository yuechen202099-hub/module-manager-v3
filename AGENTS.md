# Project Required Reading

All agents must read this file before making changes. This is mandatory for every change request, including documentation-only work.

## Current Product Direction

V2.0 is a multi-user web review system. The main workflow is no longer backend Ezcodes synchronization. The supplier does not provide a stable official API, so the product direction is:

1. Import scan/photo data from spreadsheets.
2. Match imported rows to the total catalog and stage catalog.
3. Store imported photo URLs and metadata.
4. Load imported photos in the browser from URL when a reviewer opens a group.
5. Allow administrators to upload manual missing-photo images for incomplete groups; the upload result becomes a normal photo URL record for review and export.
6. Generate archive/export names from backend classification metadata.
7. Keep review classification keyboard-first.

The old Ezcodes backend sync code is compatibility/debug code only. Do not make it the primary user flow, do not add new product dependencies on Ezcodes backend API behavior, and do not design acceptance criteria around API availability.

## Non-Negotiable Business Rules

- The total catalog is the only source of installation address.
- Installation address must not be deduplicated. It is one-to-one with meter rows.
- Display meter number must use the total catalog original meter number.
- Long scanned barcode match key: remove the first 11 chars and the last 1 char.
- Total catalog short meter match key: remove the first 2 chars.
- Imported photo rows keep URL references. Do not download imported spreadsheet photos to local disk.
- Manual missing-photo handling uses image upload because the operator will have local missing photos. Store the resulting served path or OSS key as the photo URL record.
- Classification must be fast: keyboard shortcuts are a core requirement, not a nice-to-have.
- Classified photo archive filename equals the category label, with a suitable file extension.

## Team Model

Future work must use multiple focused agents when the task is broad enough:

- Product Manager: owns requirements, workflow, acceptance criteria, release notes, and scope cuts. Must not modify implementation files unless explicitly assigned.
- Frontend Engineer: owns frontend state, routes, review interactions, keyboard shortcuts, and `v2-api/app/static/*.html` / `v2-web` UI behavior. Must not change backend schemas or migrations.
- Backend Engineer: owns FastAPI routes, services, authorization, import orchestration, and URL-loading contracts. Must not redesign UI/CSS or database migrations without coordination.
- Database Engineer: owns schema, import mapping, migrations, data integrity, indexes, and query performance. Must not change frontend behavior or visual presentation.
- Visual/CSS Director: owns workstation visual system, information density, typography, spacing, responsive layout, and interaction feel. Must not alter business logic or backend contracts.
- Test Engineer: owns regression tests, fixture coverage, manual verification scripts, and acceptance checks. Must not alter product behavior to make tests pass without product/backend/frontend agreement.

## Ownership And Edit Boundaries

- Agents must not edit overlapping files unless explicitly asked by the collaboration lead.
- If a change crosses ownership boundaries, split the work and document the handoff before editing.
- If a file is already changed by another agent, inspect and integrate with that change. Never revert blindly.
- Product decisions belong in `README.md`, `AGENTS.md`, or `docs/*.md` before implementation begins.
- Code changes that contradict this file are out of scope and must be stopped before review.

## Product Evaluation Discipline

- Product evaluation rules live in `docs/PRODUCT_EVALUATION_RULES.md`.
- After any meaningful change to import, review, construction collection, exception orders, export, permissions, storage, deployment, or data persistence, generate or update an evaluation report under `docs/evaluations/`.
- Run `powershell -ExecutionPolicy Bypass -File scripts\run-product-evaluation.ps1 -Change "change summary"` after each core workflow change.
- The report must calculate the weighted score from the local rule file and include automatic checks, score caps, strengths, weaknesses, risks, and no-extra-budget upgrade steps.
- Weekly production evaluation can be registered with `scripts\register-product-evaluation-task.ps1`; do not rely on memory for periodic review.
- Small documentation or style-only changes may append a short note to the latest report instead of creating a new report.
- Do not mark a production patch complete if it changes a core workflow and has no evaluation note or report.

## Versioning Discipline

- Current product version: `V2.6.3`.
- Every shipped change must update the product version before completion.
- Major workflow, architecture, database, deployment, or UI experience changes increment the minor version by `0.1`.
  - Example: `V2.4.11` -> `V2.5.0`.
- Small bug fixes, copy changes, focused UI adjustments, and low-risk patches increment the patch version by `0.0.1`.
  - Example: `V2.4.13` -> `V2.4.14`.
- Update all visible app version labels, release notes, and deployment notes consistently.
- Do not finish a production update without stating the old version and new version in the final report.

## Frontend Migration Rule

- Vue is the target production frontend. Static HTML pages under `v2-api/app/static/*.html` are compatibility surfaces only.
- Do not add new production static HTML pages.
- Every remaining static production page must be registered in `v2-web/src/router/staticPages.ts` with a migration status.
- Run `python scripts/verify_vue_migration_gate.py` after frontend routing changes.
- Before claiming the frontend structure is production-complete, `python scripts/verify_vue_migration_gate.py --strict-native` must pass.

## UI Bar

The UI must be rebuilt as an advanced workstation for operational review, not a marketing site or simple demo page. The interface must feel precise, calm, and high-quality:

- Dense but readable.
- Minimal decoration.
- Strong hierarchy.
- Fast keyboard flow.
- Clear current task, current group, current photo, current classification.
- Shortcut-first classification with visible focus state and no mouse-only critical path.
- Efficient task hall, review queue, photo panel, metadata panel, and progress feedback.
- No generic AI-purple gradient styling.
- No oversized landing-page hero sections.
