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
