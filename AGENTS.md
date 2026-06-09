# Project Required Reading

All agents must read this file before making changes. This is mandatory for every change request, including documentation-only work.

## Current Product Direction

V2.0 is a multi-user web review system. The main workflow is no longer backend Ezcodes synchronization. The supplier does not provide a stable official API, so the product direction is:

1. Import scan/photo data from spreadsheets.
2. Match imported rows to the total catalog and stage catalog.
3. Store photo URLs and metadata only.
4. Load photos in the browser from URL when a reviewer opens a group.
5. Generate archive/export names from backend classification metadata.
6. Keep review classification keyboard-first.

The old Ezcodes backend sync code is compatibility/debug code only. Do not make it the primary user flow, do not add new product dependencies on Ezcodes backend API behavior, and do not design acceptance criteria around API availability.

## Non-Negotiable Business Rules

- The total catalog is the only source of installation address.
- Installation address must not be deduplicated. It is one-to-one with meter rows.
- Display meter number must use the total catalog original meter number.
- Long scanned barcode match key: remove the first 11 chars and the last 1 char.
- Total catalog short meter match key: remove the first 2 chars.
- Imported photo rows keep URL references. Do not download photos to local disk.
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
