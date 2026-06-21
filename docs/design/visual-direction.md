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

## Client Demo Shell

The first client-facing web build uses a dark application top bar across login-adjacent work surfaces and a calm light-gray operational canvas.

- Top navigation must feel like a real deployed management system, not a prototype: dark shell, low-noise buttons, clear account state, and consistent exit behavior.
- Dashboard cards use compact metric blocks with strong numeric hierarchy and restrained borders.
- Review and claim pages keep three working zones visible on desktop. The left side is task context, the middle is the data/photo queue, and the right side is the current review workspace.
- Manual recovery tools are visible to admins, but they should remain grouped as operations tools rather than floating forms.
- Decorative gradients, oversized cards, and explanatory marketing text remain out of scope for this product.

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
