# V2.0 Web Visual System

This system supports a dense review and management product. It should feel calm, precise, and operational.

## Principles

- Keep the screen useful before it is expressive.
- Prefer restrained contrast, small radii, clear borders, and stable row heights.
- Use color mainly for state and action priority.
- Keep review workflows in a three-zone layout: queue, image stage, inspector.
- Avoid marketing composition, decorative gradients, nested cards, and oversized headings.

## Frontend Entry

Import the visual system once in the Vue app entry:

```ts
import "@/styles/index.css";
```

The CSS is split by responsibility:

- `tokens.css`: color, spacing, type, dimensions, and status variables.
- `base.css`: document reset, page shell, utility text classes.
- `states.css`: status badges and row state classes.
- `components.css`: toolbar, table shell, table, review layout, inspector blocks.
- `element-plus.css`: Element Plus token bridge for the same restrained visual language.
- `index.css`: single import surface.

## Status Semantics

| State | Class | Meaning |
| --- | --- | --- |
| Pending | `.v2-status--pending` | Neutral backlog or unclaimed item |
| In review | `.v2-status--reviewing` / `.v2-status--in-review` | Active claim or current reviewer work |
| Complete | `.v2-status--complete` / `.v2-status--completed` | Reviewed and ready for downstream use |
| Exception | `.v2-status--exception` / `.v2-status--error` | Data or photo condition requiring intervention |
| Incomplete | `.v2-status--incomplete` / `.v2-status--warning` | Missing required photo or field |
| Locked | `.v2-status--locked` | Temporarily unavailable due to claim or admin lock |

## Toolbar Rules

- Default toolbar height is `44px`.
- Toolbars are horizontal, compact, and border-separated from content.
- Icon buttons should be `32px` square with visible focus states.
- Use the left group for scope and filters, the center/default slot for local tools, and the right group for primary actions.
- Do not place long guidance text in the toolbar; expose labels through tooltips or nearby column headers.

## Table Rules

- Use `.v2-data-shell` around table surfaces that need title, metadata, or actions.
- Use `.v2-table` for dense operational tables.
- Header height is `36px`; body row height is `40px`.
- Keep identifiers in monospace with `.v2-mono`.
- Use `.v2-row-state--selected`, `.v2-row-state--stale`, and `.v2-row-state--danger` for row emphasis.

## Review Layout

`V2ReviewLayout` defines the default review screen:

- Queue pane: meter groups, claim state, progress, and search filters.
- Stage pane: primary image preview with dark neutral background.
- Inspector pane: photo status, meter facts, category controls, exceptions, and save state.

The layout uses fixed side widths and a fluid center to protect image visibility. Below `1080px`, the inspector moves under the queue and stage. Below `760px`, panes stack vertically.

## V2.1 Static Local Workbench

`v2-api/app/static/v201.html` mirrors the same operational language without importing the Vue CSS bundle.

- Desktop layout: `260px / fluid / 380px` working columns for task hall, data queue, and review inspector.
- Density target: 34px table headers, 40px body rows, 42px panel headers, and compact metric tiles.
- Text containment: table cells, task metadata, photo records, and detail fields use wrapping safeguards so Chinese addresses and notes do not overflow.
- Status palette: pending is neutral gray, incomplete is amber, unmatched and exception are red, approved is green.
- Responsive behavior: below `1180px`, the inspector moves under the first two columns; below `840px`, all work zones stack vertically.

## Component Usage

```vue
<V2Toolbar>
  <template #title>Review Workspace</template>
  <template #right>
    <button class="v2-icon-button" title="Refresh">...</button>
  </template>
</V2Toolbar>

<V2DataShell title="Task Hall" meta="23,000 groups">
  <table class="v2-table">...</table>
</V2DataShell>

<V2StatusBadge status="reviewing" />
```

Visual components are slot-based and should not own business fetching, mutation, or routing.

Components can also be imported from `@/components` after path alias setup.
