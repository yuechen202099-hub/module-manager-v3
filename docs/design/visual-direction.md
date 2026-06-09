# Visual Direction

The interface is an operational review tool, not a marketing site.

## Principles

- Dense but readable.
- Stable layouts for long review sessions.
- No oversized hero sections.
- No decorative card-heavy pages.
- Review page prioritizes image visibility and fast classification.
- Color is reserved for status, risk, and primary action emphasis.
- Tables and toolbars should remain compact enough for repeated daily use.

## Target Layout

- Left: task and meter group queue.
- Center: primary image preview.
- Right: photo status, category controls, exception controls, save state.

## V2.1 Local Workbench

- Local test entry: `v2-api/app/static/v201.html`.
- Layout uses three stable work zones on desktop: task hall, meter group queue, and review inspector.
- Metrics stay compact above the work zones so reviewers can scan totals without pushing the table below the fold.
- Status color is reserved for operational meaning: pending neutral, incomplete amber, unmatched/exception red, approved green.
- Long Chinese labels, addresses, notes, and file paths must wrap or ellipsize inside their own cell or control.
- Review surfaces should remain readable for long sessions: restrained borders, low-noise backgrounds, tabular numerals, and compact row heights.

## Status Semantics

- Pending: neutral.
- In review: blue.
- Complete: green.
- Exception: red.
- Incomplete: amber.
- Locked: gray.

## Implemented Assets

- CSS entry: `v2-web/src/styles/index.css`
- Tokens: `v2-web/src/styles/tokens.css`
- Visual components: `v2-web/src/components`
- Detailed spec: `docs/design/visual-system.md`
