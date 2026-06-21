# Project Decisions

This document records the current user meeting decisions. Read `AGENTS.md` before changing requirements, design, tests, or code.

## V2 Workflow

- V2 main workflow is spreadsheet import.
- V2 must not depend on the Ezcodes backend API.
- Existing Ezcodes sync logic, if present, is compatibility/debug support only and must not drive the product path.

## Photo Handling

- Imported photo data stores URL references and metadata only.
- The application loads photos from URL when reviewers inspect a group.
- Do not download spreadsheet-imported photos to local disk as part of the product workflow.
- Manual补图 uses administrator image upload because the missing photos are local operator files. Store the resulting served path or OSS object key as a normal photo reference.

## Review Experience

- Classification must be keyboard-first.
- Shortcuts are a primary acceptance requirement, not a later enhancement.
- The reviewer must be able to move through groups/photos and classify quickly without a mouse-only critical path.

## UI Standard

- Rebuild the UI to an advanced workstation standard.
- The product is an operational review cockpit: dense, readable, calm, precise, and fast.
- Avoid marketing-page layout, oversized hero sections, decorative gradients, and generic demo styling.

## Multi-Agent Collaboration

- Future development must be split by role: product, frontend, backend, database, test, and visual/CSS.
- Each role owns its file area and acceptance responsibility as defined in `AGENTS.md`.
- Agents must not make overlapping edits unless the collaboration lead explicitly coordinates the overlap.
- Cross-role work must be handed off through documentation before implementation.
