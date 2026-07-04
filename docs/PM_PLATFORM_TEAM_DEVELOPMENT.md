# PM Platform Team Development Operating Model

Last updated: 2026-07-03

This document records the standing team model for the operations engineering platform work. It is a context recovery file: every future Codex session or delegated agent should be able to read it and continue without relying on chat history.

## Chinese Context Anchor

本文件是“运维工程管理平台”团队开发的上下文锚点。后续如果 Codex 上下文变长、压缩、换线程或拆给多个智能体，先读本文件，再按这里的角色和节奏继续。

当前用户确认的产品方向：

- 平台不只服务“更换模块”一个项目，后续要能同步管理更换终端、台区线损排查等不同运维工程项目。
- 每个项目允许有独特字段，但必须围绕一个主字段、一个聚合字段和若干子字段建模。
- 字段要区分“初始建单可导入字段”和“现场施工采集字段”，并明确格式、扫码、拍照、手工录入等采集方式。
- 平台必须保留 KPI 必备字段，例如安装人员、安装时间、完成时间、在线时长、上传时间、照片数量、旧设备回收等。
- 项目流程要可视化、可拖拽、可按项目启用/停用模块，因为不同项目不一定走完全相同流程。
- 团队开发采用“一个总集成者 + 多个专项智能体”的方式；专项智能体可以拆包开发，但最终由 Codex Integrator 汇总、审阅、验证和交付。

## Mission

Build the existing module-manager project into a configurable operations engineering management platform. The platform must keep following the production line, while platform work stays isolated from production releases until reviewed and merged through the normal path.

The near-term product direction is:

- Project progress visibility.
- Project delivery capability and KPI measurement.
- Synchronized field construction data collection.
- Review, return, exception handling, and delivery archive.
- Configurable project templates, field schemas, import templates, and project workflows.

## Field Hierarchy Product Contract

This contract is the current product rule for configurable project fields:

- A project has exactly one active aggregate field at a time, such as station area, region, or manufacturer.
- Non-aggregate import fields belong to the task core layer and may choose whether they appear on the construction panel.
- Module replacement is modeled as an accessory-device replacement under one task object, for example an electric meter task object with old module, new module, collector replacement confirmation, and evidence photos under it.
- Terminal replacement is modeled as a main-device replacement under one terminal task object: old terminal/device recovered, new terminal installed, and then accessory replacement confirmations for communication module and SIM card.
- Every device replacement, accessory confirmation, accessory old/new value, and evidence photo must keep an explicit parent link to the task object so the visual field graph never falls back to a flat field list.
- Accessory fields use confirmation fields such as `communication_module_replace_confirm` or `sim_card_replace_confirm`; old/new accessory numbers and related photos become required through `required_when` only when the confirmation equals replacement.
- The graphical field designer should show aggregate -> task core -> device/accessory/evidence layers, with solid parent-child lines and conditional requirement lines where `required_when` applies.

## Dashboard Metrics Product Contract

Dashboard metrics are part of the project field schema, not a hardcoded one-project dashboard. Each project may keep its own `dashboard_metrics` list with `key`, `label`, optional `source`, and optional `scope`.

- The default metrics remain progress, collection, completion, exception, online duration, and completion duration.
- Custom metrics must round-trip through backend schema normalization and frontend save payloads.
- Project board should expose the configured metric口径 so operators can understand which fields are feeding project progress, delivery capability, field collection, review quality, and KPI calculations.
- Field graph configuration should provide operator-facing metric preset cards for project progress, delivery capability, field collection, review quality, and KPI efficiency, so metric口径 can be edited without writing raw JSON.
- Device hierarchy remains the source of meaning for replacement metrics: module replacement measures accessory replacement under one task object, while terminal replacement measures main-device replacement plus accessory replacement confirmation.

## Production Baseline Rules

- Default upstream repository: `https://github.com/yuechen202099-hub/module-manager-v3`.
- Platform development starts from the latest production branch, currently `production/V3/3.0.77`.
- Feature branches use `pm-platform/<short-feature>`.
- Do not commit directly to any `production/*` branch.
- Do not change official production version numbers.
- Do not create tags.
- Do not publish to the production server.
- Do not submit `.env`, secrets, real data, upload images, database dumps, or build archives.
- Do not overwrite production `.env`, `data`, `uploads`, OSS objects, or PostgreSQL data.
- Any change touching project configuration, permissions, database schema, import/export, or core business rules must include migration notes and rollback notes.

## Team Roles

### Team Topology

The team is organized as a hub-and-spoke delivery model. Specialist agents may implement isolated work packages, but the Codex Integrator remains the single owner of sequencing, shared-file edits, review, verification, and user-facing handoff.

```mermaid
flowchart LR
    User["User / product owner"] --> Integrator["Codex Integrator"]
    Integrator --> Field["Backend Field Schema Agent"]
    Integrator --> Flow["Backend Flow Engine Agent"]
    Integrator --> Import["Backend Import And Template Agent"]
    Integrator --> Review["Backend Construction And Review Agent"]
    Integrator --> Canvas["Frontend Workflow Canvas Agent"]
    Integrator --> Graph["Frontend Field Graph Agent"]
    Integrator --> QA["QA And Verification Agent"]
    Integrator --> Ops["Ops And Release Agent"]
    Field --> Integrator
    Flow --> Integrator
    Import --> Integrator
    Review --> Integrator
    Canvas --> Integrator
    Graph --> Integrator
    QA --> Integrator
    Ops --> Integrator
```

### Standing Team Setting

固定团队设定如下，后续上下文压缩、换线程或拆给多个智能体时按此执行：

- `Codex Integrator` 是唯一总集成者，负责拆包、排期、共享文件串行化、最终审阅、验证和交付说明。
- 后端拆成三个常驻方向：字段模型、导入模板、施工审阅；涉及同一共享文件时必须由总集成者合并。
- 前端拆成两个常驻方向：流程画布、字段关系图；面向用户的改动必须做浏览器冒烟。
- `QA And Verification Agent` 每包都要补守卫或测试，并记录命令结果。
- `Ops And Release Agent` 负责生产基线、敏感路径、迁移/回滚说明，不负责直接发布生产。
- 当前节奏是“一次只完成一个可验证小包”：计划 -> 守卫红绿 -> 实现 -> 构建/浏览器验证 -> 文档归档 -> 再进入下一包。

### Codex Integrator

The current main Codex agent is the project manager, architect, reviewer, and integrator.

Responsibilities:

- Keep the branch aligned with the latest production baseline.
- Split work into isolated packages with clear file ownership.
- Prevent two agents from editing the same files at the same time.
- Review all code before integration.
- Run verification and record results.
- Maintain migration, rollback, and release-risk notes.
- Keep documentation updated so context survives long sessions.

### Backend Field Schema Agent

Owns configurable project fields.

Responsibilities:

- Primary field, aggregate field, child fields, required platform fields, and capture rules.
- Field data types and capture methods such as scan, photo, manual input, time, user, and select.
- Compatibility between imported work orders, completed external data, and field collection data.
- Field hierarchy rules used by the future graphical field designer.

Typical owned files:

- `v2-api/app/services/platform/*field*`
- `v2-api/app/services/platform/*template*`
- backend tests for schema, import, and project creation behavior
- verification scripts related to field schema configuration

### Backend Flow Engine Agent

Owns configurable project workflow definitions.

Responsibilities:

- Workflow nodes, edges, enabled modules, statuses, and transition rules.
- Per-project differences in process order and optional functions.
- API for reading and saving project workflow configuration.
- Compatibility with existing project modules and dashboard status cards.

Typical owned files:

- `v2-api/app/services/platform/workflow.py`
- project API route files that expose workflow endpoints
- backend tests for workflow defaults and round-trip saves

### Backend Import And Template Agent

Owns import and template onboarding.

Responsibilities:

- Initial project import templates.
- Mid-project takeover templates for already-running projects.
- Completed external-data import behavior, where platform-owned fields are filled at upload time when missing.
- Validation reports that are useful to non-technical operators.

Typical owned files:

- platform template services
- import task services
- import verification scripts and tests

### Backend Construction And Review Agent

Owns field execution and review loops.

Responsibilities:

- Construction collection payloads.
- Required evidence such as installer, install time, online time, photos, old-device recovery, and operator identity.
- Review pass, reject, rework, exception, and archive states.
- KPI source data needed for efficiency, quality, and delivery dashboards.

Typical owned files:

- construction APIs
- review APIs
- backend status aggregation and KPI tests

### Frontend Workflow Canvas Agent

Owns the draggable visual workflow editor.

Responsibilities:

- Node palette.
- Draggable workflow lane or canvas.
- Connection preview between steps.
- Node configuration panel.
- Enable, disable, reorder, and save workflow behavior.
- Non-technical operator language.

Typical owned files:

- `v2-web/src/components/project-workflow/*`
- project configuration views that open workflow editing
- frontend API client additions for workflow endpoints

### Frontend Field Graph Agent

Owns the graphical field configuration experience.

Responsibilities:

- Drag-and-drop field hierarchy editing.
- Main field, aggregate field, and child field relationships.
- Capture method and data type controls.
- Template preview and required field warnings.

Typical owned files:

- project field configuration components
- `v2-web/src/views/ProjectsView.vue` only when coordinated by Codex Integrator

### QA And Verification Agent

Owns repeatable verification.

Responsibilities:

- Focused backend tests.
- Frontend build checks.
- Guard scripts that catch accidental regressions.
- Browser verification for visible user flows.
- Sensitive path and dirty-state checks before handoff.

Typical owned files:

- `scripts/verify_*`
- focused backend/frontend tests
- documentation of test commands and observed results

### Ops And Release Agent

Owns release readiness and operational safety.

Responsibilities:

- Baseline commit tracking.
- Rebase or merge strategy against latest production line.
- Backup, validation, and rollback notes.
- Production safety checklist.
- PR handoff summary.

Typical owned files:

- release notes, SOP notes, and handoff reports
- no production deployment files unless explicitly approved

## Work Package Contract

Every delegated task must include:

- Objective.
- Production baseline and feature branch.
- Files the agent may edit.
- Files the agent must not edit.
- Data safety constraints.
- Expected tests or verification commands.
- Output format: changed files, behavior summary, test result, risks, rollback notes.

Agents should not make broad refactors. They should make the smallest useful change that advances the current platform milestone.

## Delegation And Merge Rules

Use these rules whenever the project is split across multiple agents:

- One package, one owner. A package has a named lead role and a bounded file list.
- Shared files are serialized by the Codex Integrator. No specialist agent should independently edit shared integration files without an explicit handoff.
- Backend packages should expose stable data contracts before frontend packages consume them.
- Frontend packages should add guard scripts when the behavior is mostly visual or structural.
- Every package must leave a plan or report file under `docs/superpowers/plans/` when it changes platform behavior.
- Every package must report verification evidence, not only a narrative summary.
- If the production baseline advances, the Ops And Release Agent first checks the new branch and the Codex Integrator rebases or merges before more feature work continues.

Current integration hotspots:

- `v2-api/app/api/routes/projects.py`
- `v2-api/app/services/platform/catalog.py`
- `v2-api/app/services/platform/templates.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectsView.vue`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/views/ConstructionView.vue`
- `v2-web/src/views/ReviewView.vue`

## Standing Execution Rhythm

Use this rhythm when the platform work continues across long Codex contexts or multiple agents:

1. Read `AGENTS.md`, `docs/AGENT_REQUIRED_READING.md`, `docs/sop/README.md`, this document, and the active plan under `docs/superpowers/plans/`.
2. Confirm the current production baseline branch and local feature branch before editing code.
3. Prefer `codebase-memory-mcp` for code discovery. If the graph is stale or shallow, fall back to direct file reads and focused local tests.
4. Keep one main Codex Integrator responsible for sequencing, integration, review, and final reporting.
5. Split implementation into small packages that can be tested independently.
6. Use test-first work for backend behavior and guard scripts for frontend structure.
7. After each package, record changed files, verification commands, risk, and rollback notes.
8. Before handoff, check sensitive paths and generated assets separately.

## Team Execution Cadence

Use this cadence for every platform package:

1. Codex Integrator turns the user request into one small work package.
2. The package names a lead role, file boundary, verification command, migration note, rollback note, and UI acceptance signal.
3. Backend contract work is completed before frontend consumption, unless the work is only visual copy or layout.
4. Frontend visual work gets a guard script when browser-only verification would be too fragile.
5. Browser smoke checks are required when the user-facing screen changes.
6. Shared integration files are edited serially by Codex Integrator.
7. Completed package results are written into the active plan and this operating model when they change team rhythm or product sequencing.

## Minimum Acceptance Gate

No package is accepted from narrative alone. A completed package must record:

- changed files,
- the owner role and file boundary,
- at least one focused test, guard script, build, browser smoke, or API verification result,
- a non-technical UI acceptance signal when the screen changes,
- migration notes and rollback notes for configuration, permissions, database, import/export, or core business rule changes,
- sensitive path status for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads`, plus a live OSS/PostgreSQL change-path guard.

## Context-Stable Team Contract

This section is the authoritative team setting when context is compacted, a new thread takes over, or the work is split across multiple intelligent agents.

- Codex Integrator remains the single project manager and final integrator. Specialist agents may implement bounded packages, but the integrator owns sequencing, shared-file edits, review, verification, and the user-facing handoff.
- Backend work is split into four lanes: Field Schema, Flow Engine, Import And Template, and Construction And Review. These lanes should not edit the same shared backend contract files in parallel.
- Frontend work is split into three lanes: Workflow Canvas, Field Graph, and Operator Workbench UI. User-facing frontend work must include a visible acceptance signal and browser smoke validation.
- QA And Verification owns guard scripts, focused tests, builds, browser checks, and sensitive-path checks. No package is accepted from narrative alone.
- Ops And Release owns production baseline tracking, branch discipline, migration notes, rollback notes, and PR or patch packaging. It must not publish, tag, bump official version numbers, or touch production data without explicit user approval.
- Each package uses the same rhythm: plan -> failing guard or focused test -> implementation -> build/browser/API verification -> plan evidence -> team memory update.
- If production advances to a newer `production/V3/<version>` branch, feature work pauses until the baseline is checked and the platform branch is merged or rebased in a controlled way.
- Shared hotspots are serialized by Codex Integrator: `v2-api/app/api/routes/projects.py`, `v2-api/app/services/platform/templates.py`, `v2-api/app/services/platform/catalog.py`, `v2-web/src/api/types.ts`, `v2-web/src/api/services.ts`, `v2-web/src/views/ProjectsView.vue`, `v2-web/src/views/ConstructionView.vue`, and generated Vue static assets.
- Production safety shorthand for this platform stream: no tag, no deploy, no official version bump, no production data edit, and no production OSS/PostgreSQL write without explicit user approval.

### Agent Dispatch Packet Template

Every subagent package must be dispatched with this fixed packet. If a future context is compacted, rebuild the packet from this section before asking another worker to implement anything.

```text
Package:
Owner role:
Objective:
Production baseline:
Feature branch:
Allowed files:
Forbidden files:
Shared-file coordination:
Data safety constraints:
Expected verification:
Migration note:
Rollback note:
UI acceptance signal:
Output required:
```

Required meanings:

- `Owner role` must be one of the standing roles in this document, such as Backend Field Schema Agent, Backend Flow Engine Agent, Backend Import And Template Agent, Backend Construction And Review Agent, Frontend Workflow Canvas Agent, Frontend Field Graph Agent, QA And Verification Agent, Ops And Release Agent, or Codex Integrator.
- `Allowed files` must be narrow. Shared hotspots stay with Codex Integrator unless the packet explicitly grants a specialist edit.
- `Forbidden files` must include `.env`, real data, uploads, database dumps, secrets, production release artifacts, and any production OSS/PostgreSQL write path unless the user separately approves the risky action.
- `Expected verification` must name concrete commands or browser/API checks.
- `Migration note` and `Rollback note` are required when touching project configuration, permissions, database schema, import/export, or core business rules.
- `Output required` must include changed files, behavior summary, verification result, risks, rollback notes, and unresolved questions.

### Two-Stage Review Gate

No specialist package is accepted only because the implementer says it is done. Codex Integrator owns the review loop and must apply both gates before the package becomes part of the handoff.

```mermaid
flowchart LR
    Package["Specialist package"] --> Spec["Spec compliance review"]
    Spec -->|Mismatch| FixSpec["Return to implementer"]
    FixSpec --> Spec
    Spec -->|Matches plan| Quality["Code quality review"]
    Quality -->|Issue found| FixQuality["Return to implementer"]
    FixQuality --> Quality
    Quality -->|Approved| Verify["Integrator verification"]
    Verify --> Memory["Plan evidence and team memory update"]
```

- Spec compliance review checks that the package matches the user request, the active plan, the product direction, and the agreed file boundary.
- Code quality review checks maintainability, compatibility with existing replacement-project behavior, data safety, verification evidence, and rollback clarity.
- If either review finds an issue, the package returns to the same package owner or a focused fixer before any next package starts.
- QA And Verification Agent may review guard scripts and command results, but Codex Integrator remains accountable for final acceptance.

### Backend Team Split Contract

Backend work is split to reduce context load and prevent one worker from owning too much logic at once.

- Backend Field Schema Agent owns primary field, aggregate field, child fields, field source, capture method, required KPI field alignment, and field hierarchy contracts.
- Backend Flow Engine Agent owns workflow nodes, module toggles, status transitions, workflow persistence contracts, and project-readiness flow checks.
- Backend Import And Template Agent owns initial work-order templates, external-completed takeover templates, validation, import execution, and platform-owned field defaults at upload time.
- Backend Construction And Review Agent owns construction payloads, site evidence, installer/time/online/KPI fields, review status, rework, exception, archive, and delivery-quality summaries.
- Shared backend files are serialized by Codex Integrator, especially project routes, shared platform catalog/template services, and contract snapshots.
- No production database migration may start without explicit user approval.

### Frontend Team Split Contract

Frontend work is split by user workflow rather than by technical file alone.

- Frontend Workflow Canvas Agent owns visual workflow editing, module switches, node order, enabled/disabled functions, and workflow acceptance signals.
- Frontend Field Graph Agent owns draggable field hierarchy, main/aggregate/child relationships, capture controls, template actions, and schema warnings.
- Operator Workbench UI Agent owns project list, project cockpit, construction page, review workbench, and non-technical copy that operators see daily.
- Frontend UI packages that change visible behavior require a browser smoke result or a guard script that proves the expected visible tokens and interactions.
- Shared files such as `ProjectsView.vue`, API service/type files, generated Vue assets, and page-level routing remain integration hotspots controlled by Codex Integrator.

### Next Execution Queue

Continue in this order unless the user reprioritizes:

1. Keep the PR/patch handoff ready and refresh its evidence when new packages are added.
2. Platform Handoff Readiness Summary is now the current review entry: `GET /projects/handoff/readiness` and `/platform-projects` show `交付就绪`, `可评审包`, `production/V3/3.0.77`, and `生产迁移未放行`.
3. Before new implementation work, refresh the production baseline branch and confirm the platform branch still follows `production/V3/3.0.77` or the newest user-approved production branch.
4. If the user chooses PR, use the prepared PR body and target the current production branch without version bump, tag, or deployment.
5. If the user chooses patch, export a reviewable patch against the same production baseline and include the handoff report.
6. If the user explicitly approves persistence migration, create the first Alembic/PostgreSQL migration as a separate high-risk package with backup, dry-run, verification, and rollback rehearsal.
7. After a migration package exists, add persistence-backed contract tests before enabling production reads from PostgreSQL.

## Team Memory Snapshot

This section is the short version for context recovery. If a future thread is compacted, read this before continuing development.

- Current production baseline: `production/V3/3.0.77`.
- Current feature branch: `pm-platform/production-3.0.77-sync`.
- GitHub Issue #1 follow-up: production has advanced to `production/V3/3.0.77`; handoff readiness and team memory now use the 3.0.77 baseline, and the next platform PR/patch must include `平台版本号评估`.
- Platform versioning recommendation: use `PM-V1.0.xx` only as a platform development progress version, always paired with the production baseline, and never as a replacement for production `V3.0.xx`.
- Current platform direction: configurable operations engineering management, not a single replacement-module project.
- Current delivery style: small work packages, each with owner role, file boundary, verification, migration note, rollback note, and browser smoke when UI changes.
- Current integrator rule: specialist agents may work on isolated packages, but Codex Integrator owns shared files, final review, verification, and user handoff.
- Current data safety rule: no production `.env`, real data, uploads, OSS, PostgreSQL, version tag, release, or server publish changes.
- Current code discovery rule: use `codebase-memory-mcp` first; current graph is ready but shallow, so direct file reads and focused tests are allowed when symbol-level graph search is insufficient.
- Context compression rule: after any compaction or thread handoff, read this snapshot first, then the active plan; do not rely only on chat history.
- Current active package: continue configurable field schema, readiness, construction, review, and workflow refinements in small verified packages, then refresh PR/patch handoff notes before final delivery.
- Last completed package: Project List Config Preflight Details; `/platform-projects` now shows top-level `项目列表预检阻断` details with store issues, blocked project names, first fix message, project id, and issue count when local drafts block normal list loading.
- Latest project list config preflight details plan: `docs/superpowers/plans/2026-07-04-project-list-config-preflight-details.md`.
- Latest project list config preflight details report: `docs/reports/pm-platform-project-list-config-preflight-details-2026-07-04.md`.
- Previous completed package: Device Hierarchy Contract Notes; backend `device_hierarchy` readiness now exposes the operator contract for module replacement, terminal replacement, and `required_when` conditional accessory collection, and the field graph shows `后端层级口径`.
- Latest device hierarchy contract notes plan: `docs/superpowers/plans/2026-07-03-device-hierarchy-contract-notes.md`.
- Latest device hierarchy contract notes report: `docs/reports/pm-platform-device-hierarchy-contract-notes-2026-07-03.md`.
- Earlier completed package: Project List Config Preflight Fallback; `GET /projects` now degrades to built-in project rows plus read-only `config_preflight` when local draft config is blocked, and `/platform-projects` shows `项目列表预检`.
- Latest project list config preflight fallback plan: `docs/superpowers/plans/2026-07-03-project-list-config-preflight-fallback.md`.
- Latest project list config preflight fallback report: `docs/reports/pm-platform-project-list-config-preflight-fallback-2026-07-03.md`.
- Previous completed package: Handoff Config Preflight Summary; `GET /projects/handoff/readiness` now includes read-only `config_preflight`, reports `fix_config_preflight_blockers` without loading broken drafts, and `/platform-projects` shows top-level `配置预检`.
- Latest handoff config preflight summary plan: `docs/superpowers/plans/2026-07-03-handoff-config-preflight-summary.md`.
- Latest handoff config preflight summary report: `docs/reports/pm-platform-handoff-config-preflight-summary-2026-07-03.md`.
- Previous completed package: Rework Resubmission Audit Trail; returned platform work orders now append `rework_submitted` history when construction resubmits, and the UI labels the event as `返工重新提交`.
- Latest rework resubmission audit plan: `docs/superpowers/plans/2026-07-03-rework-resubmission-audit-trail.md`.
- Latest rework resubmission audit report: `docs/reports/pm-platform-rework-resubmission-audit-2026-07-03.md`.
- Previous completed package: Construction Rework Gap Panel; returned platform work orders now expose structured `rework_evidence_gap_groups`, and the construction page shows a `退回补采清单` that preserves module/terminal device replacement hierarchy.
- Latest construction rework gap panel plan: `docs/superpowers/plans/2026-07-03-construction-rework-gap-panel.md`.
- Latest construction rework gap panel report: `docs/reports/pm-platform-construction-rework-gap-panel-2026-07-03.md`.
- Earlier completed package: Review Return Reason Suggestions; imported hierarchy gaps now become a suggested return reason, and blank returned review actions fall back to that reason.
- Latest review return reason suggestions plan: `docs/superpowers/plans/2026-07-03-review-return-reason-suggestions.md`.
- Latest review return reason suggestions report: `docs/reports/pm-platform-review-return-reason-suggestions-2026-07-03.md`.
- Earlier completed package: Review Hierarchy Gap Follow-up; external-completed takeover work orders now carry imported `missing_conditional_field` warnings into review as `导入层级缺口`, keeping terminal accessory confirmation gaps visible before approval.
- Latest review hierarchy gap follow-up plan: `docs/superpowers/plans/2026-07-03-review-hierarchy-gap-followup.md`.
- Latest review hierarchy gap follow-up report: `docs/reports/pm-platform-review-hierarchy-gap-followup-2026-07-03.md`.
- Earlier completed package: Import Draft Hierarchy Gap Summary; import draft dry-run results now carry `hierarchy_gap_count` and `hierarchy_gap_items`, and the import preview card keeps `层级缺口` visible after validation.
- Latest import draft hierarchy gap summary plan: `docs/superpowers/plans/2026-07-03-import-draft-hierarchy-gap-summary.md`.
- Latest import draft hierarchy gap summary report: `docs/reports/pm-platform-import-draft-hierarchy-gap-summary-2026-07-03.md`.
- Earlier completed package: Template Validation Hierarchy Panel; external-completed import validation now shows a dedicated `层级证据缺口` panel for conditional accessory evidence warnings before the generic issue table.
- Latest template validation hierarchy panel plan: `docs/superpowers/plans/2026-07-03-template-validation-hierarchy-panel.md`.
- Latest template validation hierarchy panel report: `docs/reports/pm-platform-template-validation-hierarchy-panel-2026-07-03.md`.
- Earlier completed package: External Completed Hierarchy Validation; system-external completed template validation now warns when a replacement confirmation triggers missing conditional child fields or photo evidence, without blocking project connection.
- Latest external completed hierarchy validation plan: `docs/superpowers/plans/2026-07-03-external-completed-hierarchy-validation.md`.
- Latest external completed hierarchy validation report: `docs/reports/pm-platform-external-completed-hierarchy-validation-2026-07-03.md`.
- Earlier completed package: Field Template Hierarchy Hints; template preview and downloaded workbook guidance now preserve field hierarchy metadata, including task core, accessory confirmation, conditional collection, parent field, and platform-fill hints.
- Latest field template hierarchy hints plan: `docs/superpowers/plans/2026-07-03-field-template-hierarchy-hints.md`.
- Latest field template hierarchy hints report: `docs/reports/pm-platform-field-template-hierarchy-hints-2026-07-03.md`.
- Earlier completed package: Field Graph Backend Readiness Echo; saved project field configuration now passes backend `device_hierarchy` readiness into the graphical field designer, renders `后端上线检查回显`, and highlights field graph nodes named by backend hierarchy evidence.
- Latest field graph backend readiness echo plan: `docs/superpowers/plans/2026-07-03-field-graph-backend-readiness-echo.md`.
- Latest field graph backend readiness echo report: `docs/reports/pm-platform-field-graph-backend-readiness-echo-2026-07-03.md`.
- Earlier completed package: Field Graph Hierarchy Save Gate; `/platform-projects` field graph now shows `层级完整性`, `换模块完整性`, and `换终端完整性`, and create/save flows block incomplete device-replacement hierarchy before sending the API request.
- Latest field graph hierarchy save gate plan: `docs/superpowers/plans/2026-07-03-field-graph-hierarchy-save-gate.md`.
- Latest field graph hierarchy save gate report: `docs/reports/pm-platform-field-graph-hierarchy-save-gate-2026-07-03.md`.
- Earlier completed package: Delivery Archive Hierarchy Evidence Summary; project board delivery package preview now groups required evidence by main device, task-object accessory device, accessory confirmation, conditional follow-up, photo evidence, and KPI data, while the backend manifest preserves platform KPI archive evidence.
- Latest delivery archive hierarchy evidence summary plan: `docs/superpowers/plans/2026-07-03-delivery-archive-hierarchy-evidence-summary.md`.
- Latest delivery archive hierarchy evidence summary report: `docs/reports/pm-platform-delivery-archive-hierarchy-evidence-summary-2026-07-03.md`.
- Previous completed package: Review Hierarchy Intent Labels; platform review evidence rows now show intent labels matching construction collection semantics.
- Earlier completed package: Review Required Evidence Gate; platform review now shows grouped missing required field/photo evidence and backend approval rejects incomplete evidence, while return and exception actions remain available.
- Previous completed package: Construction Submit Gap Preview; the construction page now groups missing required fields, photos, and KPI inputs into a visible submission gap and disables platform final submit until the gap is cleared, while draft save remains available.
- Earlier completed package: Construction Required Collection Gate; submitted construction collections now reject missing active required fields/photos, including conditional accessory values/photos when an accessory replacement confirmation is triggered, while cached drafts remain allowed.
- Previous completed package: Device Replacement Hierarchy Drops; the field graph now treats module replacement as task-object -> accessory-device replacement and terminal replacement as task-object -> main-device replacement -> accessory confirmation, with smart-drop behavior preserving those relationships.
- Earlier completed package: Workflow Selected Node Order Controls; the workflow editor right-side node panel now shows current position, previous node, next node, and selected-node up/down controls for tablet-friendly process editing.
- Earlier completed package: Platform LAN Tablet Access; `scripts/start-platform-local.ps1` now keeps `127.0.0.1` as the default local-only mode, supports explicit `-HostAddress 0.0.0.0` for trusted LAN tablet review, prints a `LAN URL`, and is guarded by `scripts/verify_platform_local_start_script.py`.
- Current GitHub action item: before final PR/patch, merge or rebase the platform branch onto `production/V3/3.0.77`, then refresh handoff reports, tests, baseline SHA, and the concrete `PM-V1.0.xx` progress label.
- Baseline sync readiness result: do not merge directly in the current dirty worktree. Production `3.0.77` changes 145 paths, current platform WIP has 192 dirty paths, and 43 paths overlap, including `projects.py`, frontend API files, `ProjectsView.vue`, and generated Vue assets.
- Previous completed package: Platform Handoff Readiness Summary; `GET /projects/handoff/readiness` aggregates readiness, persistence, migration gates, production safety, and next actions, while `/platform-projects` shows `交付就绪`, `可评审包`, `production/V3/3.0.77`, and `生产迁移未放行` before `上线检查`.
- Previous completed package: Platform Migration Readiness Gate; `/projects/persistence/migration-readiness` and the `持久化准备` panel now show backup, dry-run, verification, rollback, approval, and cutover-flag gates as blocked before any migration can proceed.
- Previous completed package: Project Persistence Readiness Frontend; `/platform-projects` field configuration now shows `持久化准备`, current storage, PostgreSQL migration approval state, target tables, round-trip preservation, and safety gates by consuming existing read-only persistence endpoints.
- Earlier completed package: Project readiness action filter; `/platform-projects` lets operators click a `接入待办` action count, shows `筛选中`, filters the table through `filteredProjects`, and restores the full list through `清除筛选`.
- Earlier completed package: Project readiness action todos; `/platform-projects` now consumes `GET /projects/readiness/summary` action counts and shows `接入待办` next to `上线状态` without adding row-level operation buttons.
- Earlier completed package: Project readiness summary list; `/platform-projects` consumes `GET /projects/readiness/summary` and shows `上线状态` for every project.
- Earlier completed package: Team Operating Model Lock; the multi-agent team setting, dispatch packet, two-stage review gate, backend/frontend split, and next execution queue are now guarded by `scripts/verify_pm_platform_team_operating_model.py`.
- Earlier completed package: frontend project readiness panel; `/platform-projects` field configuration consumes `GET /projects/{project_id}/readiness` and shows a visible `上线检查` result.
- Previous backend package: project readiness check; `GET /projects/{project_id}/readiness` tells whether a project has enough field schema, site evidence, KPI, module, and workflow configuration to be taken over or launched.

Current code discovery state:

- `codebase-memory-mcp` project: `C-Users-Yuech-Documents-module-manager-v3`.
- Current graph status: ready, but shallow file-level indexing only.
- Use graph tools first for architecture/file discovery, then fall back to direct file reads and focused local tests when symbol-level search is insufficient.

## Context Recovery Protocol

When a Codex context becomes long, compacted, or resumed by another worker, recover in this order:

1. Read the production guardrails: `AGENTS.md`, `docs/AGENT_REQUIRED_READING.md`, and `docs/sop/README.md`.
2. Read this file as the team operating model.
3. Check the local branch and baseline with Git before editing.
4. Use `codebase-memory-mcp` first for code discovery. If it only has shallow file-level indexing, record that and fall back to direct file reads.
5. Read the most recent plan files in `docs/superpowers/plans/` for the active milestone.
6. Run the smallest relevant guard or test before claiming a package is complete.
7. Update this file if the team shape, ownership rules, active package, or next package queue changes.

## Active Task Board

The current platform build should proceed in this order unless the user reprioritizes:

| Order | Work package | Lead role | Completion signal |
| --- | --- | --- | --- |
| 1 | Team operating model and context recovery | Codex Integrator | Done: this document records roles, rhythm, task board, and recovery rules |
| 2 | Workflow status summary for dashboards | Backend Flow Engine Agent | Done: project overview exposes workflow-aware current node and enabled modules |
| 3 | Workflow status display in project list | Frontend Workflow Canvas Agent | Done: non-technical users can see configured flow state from `/platform-projects` |
| 4 | Field graph designer plan | Backend Field Schema Agent + Frontend Field Graph Agent | Done: main field, aggregate field, child field, import field, and site-capture field rules have a design spec |
| 5 | Import template handoff | Backend Import And Template Agent | Done for current pass: initial and external-completed templates are explained, downloadable, validated, and guided through next actions |
| 6 | Construction and review loop | Backend Construction And Review Agent | In progress: KPI fields, site evidence, review, rework, exception, and archive states are connected; next pass links delivery KPI to review quality |
| 7 | Project cockpit KPI band | Frontend Workflow Canvas Agent + QA And Verification Agent | Done: `/project-board` shows platform operation-stage and delivery-capability KPI cards |
| 8 | Workflow module toggles | Frontend Workflow Canvas Agent + QA And Verification Agent | Done for current pass: workflow editor shows module switches, affected node counts, required-node counts, and keeps required nodes enabled |
| 9 | Field graph designer implementation | Frontend Field Graph Agent + Backend Field Schema Agent | Done for current pass: field configuration shows visual hierarchy, role buckets, drop zones, selected details, and drag/drop parent reassignment |
| 10 | Field graph to template contract alignment | Backend Import And Template Agent + Frontend Field Graph Agent | Done for current pass: field graph exposes initial/external template download and validation actions, and the construction checklist keeps platform KPI required fields visible |
| 11 | Construction checklist consumption and QA/PR handoff | Backend Construction And Review Agent + QA And Verification Agent + Ops And Release Agent | Done for current pass: construction-side collection consumes the configured checklist |
| 12 | Backend shared contract snapshot | Backend Field Schema Agent + Backend Import And Template Agent + Backend Construction And Review Agent + QA And Verification Agent | Done: `contracts.py` exposes template, field, construction, KPI, and review contract names with pytest and script guards |
| 13 | Platform persistence status | Backend Flow Engine Agent + Ops And Release Agent + QA And Verification Agent | Done: `/projects/persistence/status` exposes read-only storage/backend status with pytest and script guards |
| 14 | PostgreSQL persistence design | Backend Flow Engine Agent + Ops And Release Agent + QA And Verification Agent | Done: `postgres_design.py` defines the first schema/workflow persistence slice, indexes, migration steps, and rollback steps without touching the database |
| 15 | PR/patch handoff or user-approved Alembic migration | Codex Integrator + Ops And Release Agent | Done for handoff: report, PR body draft, package guard, focused verification, and production-safety notes are prepared; wait for user choice before PR, patch, or Alembic migration |
| 16 | Project config persistence contract preview | Backend Flow Engine Agent + QA And Verification Agent + Ops And Release Agent | Done for current pass: `GET /projects/{project_id}/persistence/contract` previews field schema/workflow persistence rows and round-trip readiness without a migration |
| 17 | Persistence contract in backend shared snapshot | Backend Flow Engine Agent + QA And Verification Agent | Done: `contracts.py` exposes `persistence.project_config` and guards route, table, record, round-trip, migration, and safety names |
| 18 | Project readiness check | Backend Flow Engine Agent + Backend Field Schema Agent + QA And Verification Agent | Done: `GET /projects/{project_id}/readiness` checks field schema, site evidence, KPI, module, and workflow readiness without writing data |
| 19 | Frontend project readiness panel | Frontend Field Graph Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: field configuration dialog shows backend `上线检查`, readiness checks, next actions, and refresh behavior without adding more row-level operation buttons |
| 20 | Team Operating Model Lock | Codex Integrator + QA And Verification Agent | Done: team setting, subagent dispatch packet, two-stage review gate, backend/frontend split, next execution queue, and guard script are recorded |
| 21 | Project readiness summary list | Backend Flow Engine Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: `GET /projects/readiness/summary` and `/platform-projects` `上线状态` column show scan-friendly multi-project readiness |
| 22 | Project readiness action todos | Backend Flow Engine Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: readiness summary returns `action_counts` and `/platform-projects` shows `接入待办` action counts |
| 23 | Project readiness action filter | Operator Workbench UI Agent + QA And Verification Agent | Done: clicking a `接入待办` tag filters `/platform-projects`, shows `筛选中`, and `清除筛选` restores the full list |
| 24 | Project Persistence Readiness Frontend | Operator Workbench UI Agent + Ops And Release Agent + QA And Verification Agent | Done: field configuration shows `持久化准备`, storage backend, PostgreSQL approval state, target tables, round-trip status, and safety gates without running a migration |
| 25 | Platform Migration Readiness Gate | Backend Flow Engine Agent + Operator Workbench UI Agent + Ops And Release Agent + QA And Verification Agent | Done: read-only migration gate exposes backup, dry-run, verification, rollback, approval, and cutover-flag blockers before any PostgreSQL migration |
| 26 | Platform Handoff Readiness Summary | Codex Integrator + Operator Workbench UI Agent + Ops And Release Agent + QA And Verification Agent | Done: `/projects/handoff/readiness` and `/platform-projects` show `交付就绪`, `可评审包`, target baseline, migration block state, and PR/patch next action |
| 27 | Platform LAN Tablet Access | Ops And Release Agent + QA And Verification Agent | Done: local start script defaults to `127.0.0.1`, supports explicit `-HostAddress 0.0.0.0`, prints LAN URL, and verifies both local and LAN HTTP access |
| 28 | GitHub Issue #1 Platform Versioning Follow-up | Codex Integrator + Ops And Release Agent | In progress: PR/patch docs now include `平台版本号评估`; next required step is to follow `production/V3/3.0.77` before final handoff |
| 29 | Production 3.0.77 Sync Readiness | Codex Integrator + Ops And Release Agent + QA And Verification Agent | Done for readiness: drift, dirty overlap, merge-tree conflicts, and safe sync sequence are recorded; actual merge waits for WIP snapshot/isolation |
| 30 | Field Graph Smart Drop | Frontend Field Graph Agent + QA And Verification Agent | Done: field graph smart-drop targets apply task-core, main-device, accessory-confirmation, conditional accessory, and evidence-photo semantics while keeping module and terminal replacement hierarchy explicit |
| 31 | Field Graph Tap Drop | Frontend Field Graph Agent + QA And Verification Agent | Done: selected custom fields can apply smart-drop hierarchy rules by click/tap or keyboard, making field configuration usable on tablets when native drag/drop is unreliable |
| 32 | Workflow Selected Node Order Controls | Frontend Workflow Canvas Agent + QA And Verification Agent | Done: selected workflow nodes can be moved up/down from the right node configuration panel with current/previous/next context for tablet operators |
| 33 | Device Replacement Hierarchy Drops | Frontend Field Graph Agent + QA And Verification Agent | Done: device-node smart drops preserve module replacement and terminal replacement hierarchy instead of flattening replacement fields |
| 34 | Device Hierarchy Readiness Gate | Backend Field Schema Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: `/projects/{project_id}/readiness` includes `device_hierarchy`, blocks flat device replacement fields, and the field configuration UI labels the required fix in business language |
| 35 | Construction Required Collection Gate | Backend Construction And Review Agent + QA And Verification Agent | Done: submitted construction collections reject missing active required fields/photos, including conditional accessory collection triggered by replacement confirmation, while cached drafts remain allowed |
| 36 | Construction Submit Gap Preview | Operator Workbench UI Agent + QA And Verification Agent | Done: construction collection forms show grouped submit gaps for required fields/photos/KPI inputs and disable platform final submit until cleared |
| 37 | Review Required Evidence Gate | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: platform review shows grouped evidence gaps and backend approval rejects missing required field/photo evidence |
| 38 | Main Old Device Hierarchy | Frontend Field Graph Agent + QA And Verification Agent | Done: field graph treats unconditional old devices as main-device-before fields when the schema also has a main replacement device, while conditional old devices remain accessory follow-up collection |
| 39 | Delivery Archive Readiness Summary | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: read-only delivery archive readiness classifies approved archive, pending review, returned rework, evidence gaps, exceptions, and not-ready work orders before any archive write |
| 40 | Delivery Archive Manifest Preview | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: read-only delivery package manifest previews ready items, blockers, required field/photo evidence, and export eligibility without creating an archive |
| 41 | Delivery Archive Evidence Details | Operator Workbench UI Agent + QA And Verification Agent | Done: project board delivery package preview shows required field/photo evidence details and conditional trigger labels without adding archive writes |
| 42 | Delivery Archive Blocker Details | Operator Workbench UI Agent + QA And Verification Agent | Done: delivery package preview lists blocker work-order details with reason, work object, aggregate value, and handling detail without archive writes |
| 43 | Device Replacement Hierarchy Mode | Frontend Field Graph Agent + Backend Field Schema Agent + QA And Verification Agent | Done: field graph and readiness evidence explicitly classify module replacement as accessory-under-task-object and terminal replacement as main-device-with-accessory-confirmation |
| 44 | Construction Hierarchy Intent Labels | Operator Workbench UI Agent + QA And Verification Agent | Done: construction collection checklist, fields, and photo slots show collection intent labels for main device, accessory, confirmation, conditional follow-up, photo evidence, and KPI data |
| 45 | Review Hierarchy Intent Labels | Backend Construction And Review Agent + QA And Verification Agent | Done: review workbench field, photo, and KPI evidence rows show intent labels matching construction collection semantics |
| 46 | Delivery Archive Hierarchy Evidence Summary | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: delivery archive preview groups required evidence by main device, task-object accessory device, accessory confirmation, conditional follow-up, photo evidence, and KPI data |
| 47 | Field Graph Hierarchy Save Gate | Frontend Field Graph Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: field configuration shows hierarchy completeness cards and blocks save/create for incomplete module or terminal replacement hierarchy |
| 48 | Field Graph Backend Readiness Echo | Frontend Field Graph Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: field configuration passes backend `device_hierarchy` readiness into the field graph, shows backend issue details, and highlights affected nodes |
| 49 | Field Template Hierarchy Hints | Backend Template Agent + Frontend Field Graph Agent + QA And Verification Agent | Done: template preview and downloaded workbook guidance preserve task core, accessory confirmation, conditional collection, parent field, and platform-fill hints |
| 50 | External Completed Hierarchy Validation | Backend Template Agent + QA And Verification Agent | Done: external completed template validation warns when replacement confirmation triggers missing conditional child fields or photo evidence without blocking project connection |
| 51 | Template Validation Hierarchy Panel | Operator Workbench UI Agent + QA And Verification Agent | Done: template validation dialog shows `层级证据缺口` for missing conditional accessory evidence warnings |
| 52 | Import Draft Hierarchy Gap Summary | Backend Import And Template Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: import draft preview keeps `层级缺口` count and items visible after dry-run generation |
| 53 | Review Hierarchy Gap Follow-up | Backend Import And Template Agent + Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: external-completed import execution preserves hierarchy gaps and review workbench shows them as `导入层级缺口` blockers |
| 54 | Review Return Reason Suggestions | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: imported hierarchy gaps become suggested return reasons in both review entry points and backend blank-return fallback |
| 55 | Construction Rework Gap Panel | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: returned platform work orders expose structured rework evidence gaps and construction forms show `退回补采清单` for missing hierarchy fields/photos |
| 56 | Rework Resubmission Audit Trail | Backend Construction And Review Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: returned platform work orders append `rework_submitted` history on resubmit and review history labels it as `返工重新提交` |
| 57 | Replacement Hierarchy Template Apply | Frontend Field Graph Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: field graph exposes module and terminal replacement hierarchy templates and applies them to new-project and draft-schema field forms |
| 58 | Template Impact Preview | Frontend Field Graph Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: draft field graph previews initial import, system-external completed, and upload-time platform generated template data with hierarchy hints |
| 59 | Template Workbook Instructions | Backend Import And Template Agent + QA And Verification Agent | Done: downloaded templates include an `instructions` sheet explaining field hierarchy, parent fields, conditional collection, upload-time generated fields, and module/terminal replacement hierarchy modes |
| 60 | Template Download Guidance | Frontend Field Graph Agent + QA And Verification Agent | Done: field graph template preview now explains the downloaded workbook sheets and shows the inferred module/terminal replacement hierarchy before download |
| 61 | Project Type Preset Guidance | Operator Workbench UI Agent + QA And Verification Agent | Done: create-project preset selector now explains the selected preset's main field, aggregate field, one-active-aggregate rule, and module/terminal replacement hierarchy |
| 62 | Single Aggregate Device Hierarchy Guard | Backend Field Schema Agent + QA And Verification Agent | Done: backend project schema normalization rejects extra aggregate fields and terminal main-device replacement schemas that lack accessory confirmation hierarchy |
| 63 | Field Graph Aggregate Guard | Frontend Field Graph Agent + QA And Verification Agent | Done: graphical field designer shows the one-active-aggregate rule, hides aggregate relation roles from custom fields, and validates aggregate misuse before create/save |
| 64 | Single Aggregate Readiness | Backend Field Schema Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: project readiness now exposes `single_aggregate_field`, maps `fix_aggregate_field`, and keeps aggregate misuse visible in onboarding status |
| 65 | Terminal Accessory Confirmation Gate | Frontend Field Graph Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: field graph selected-field hints and project save validation now make terminal accessory replacement confirmation explicit before backend submission |
| 66 | Project Config Preflight | Backend Field Schema Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: read-only config preflight reports legacy draft field/workflow blockers before project load, save, migration, or repair |
| 67 | Handoff Config Preflight Summary | Backend Field Schema Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: handoff readiness includes read-only config preflight, blocks review package on legacy draft blockers, and `/platform-projects` shows top-level `配置预检` |
| 68 | Project List Config Preflight Fallback | Backend Field Schema Agent + Operator Workbench UI Agent + QA And Verification Agent | Done: project list returns built-in rows plus read-only config preflight when local draft config blocks normal list loading |
| 69 | Device Hierarchy Contract Notes | Backend Field Schema Agent + Frontend Field Graph Agent + QA And Verification Agent | Done: backend readiness and the field graph show the operator contract for module replacement as task-object accessory replacement and terminal replacement as main-device replacement plus accessory confirmation |
| 70 | Project List Config Preflight Details | Operator Workbench UI Agent + QA And Verification Agent | Done: `/platform-projects` shows top-level project-list preflight blocker details with store issues, blocked project names, issue text, project id, and issue count |

## Integration Checkpoints

Codex Integrator should pause for a review pass at these checkpoints:

- A workflow configuration change starts affecting project modules or dashboard status.
- A field schema change affects import/export, required fields, or construction capture.
- A database schema, permission rule, or core business rule change is proposed.
- A build regenerates Vue static assets.
- A task is ready for PR or patch packaging.

For low-risk UI and local API work, continue implementation after focused verification. For production data, deployment, database migration, OSS, or permission changes, ask the user before acting.

## Parallel Development Rules

- Agents may work in parallel only when their file ownership does not overlap.
- If two work packages need the same file, Codex Integrator serializes the work.
- `ProjectsView.vue`, project API route files, and shared platform catalog services are integration hotspots; edits there require coordination.
- Agents should prefer additive files and focused tests, then let Codex Integrator wire integration points.
- Generated Vue static assets may change after frontend builds; they must be reviewed as generated output, not manually edited.

## Review Gates

Before a work package is accepted:

- The implementation must match the product direction and not just expose abstract knobs.
- The UI must be understandable for a non-technical project operator.
- The backend must keep existing replacement-project behavior compatible.
- Tests or guard scripts must prove the new behavior.
- Migration and rollback notes must exist for risky changes.
- Sensitive paths must remain untracked.

## Current Workstream

The active milestone is configurable field schema plus import-template onboarding.

Reference plan:

- `docs/superpowers/plans/2026-07-01-pm-platform-flow-orchestrator-mvp.md`

The workflow editor MVP lets a user configure a project-specific process visually, because not every project needs every function and different project types have small process differences.

Initial workflow nodes:

- Project setup.
- Field schema configuration.
- Template import.
- Work order planning.
- Field construction collection.
- Review.
- Rework.
- Exception handling.
- Delivery archive.
- Delivery export.

The workflow editor should start practical and controlled: use a clear visual lane or canvas first, store a structured workflow definition, and expand into richer automation after the data model stabilizes.

Completed execution packages:

- Align field-graph template previews with the real backend template download and validation rules.
- The backend template service is the source of truth for initial work-order templates and external-completed takeover templates.
- The frontend field graph may keep a local fallback, but normal preview data should come from the backend preview API.
- This keeps downloadable Excel headers, validation expected headers, and visual configuration preview consistent.
- Connect external-completed takeover imports to the local platform work-order store.
- `initial_work_orders` means work still needs field construction; `external_completed` means the work already happened outside the platform and enters at the review stage.
- When external-completed import execution creates local work orders, platform-owned KPI fields are filled at execution time and the work orders are marked as submitted/pending review.
- Extend the review page into a platform review workbench entry with status filters, selected work-order details, field/photo evidence checks, review history, and approve/return/exception actions.
- Surface returned platform work orders in the construction page as actionable rework, with a returned-only filter and visible return reason.
- Split project-level platform KPIs into initial work orders, external completed takeover, pending review, returned rework, approved archive, and not-ready work.
- Promote the same platform KPI split into the project cockpit so operators can read operational stages from `/project-board?project_id=<project>`.
- Preserve required construction KPI fields on platform work orders: installer, install/completion/upload time, online duration, photo count, and old-device recovery status.
- Promote construction delivery KPI summaries into `/platform-projects` and `/project-board`, while keeping them visually separate from work-order flow stages.
- Explain import template choices and guided next actions in `/platform-projects`: `initial_work_orders` continues to construction collection, while `external_completed` continues to review and archive.
- Connect delivery KPI visibility with review quality: `/project-board` and `/platform-projects` now show approved archive, returned rework, pending review, pass rate, and return rate next to field evidence KPIs.
- Add module-level workflow toggles to the visual workflow editor: each project can enable or disable optional functional modules, see affected workflow nodes, and keep required nodes protected.
- Improve the field graph designer so project fields are configured through visible hierarchy drop zones, role buckets, selected-field details, and drag/drop parent reassignment.
- Connect field graph configuration to template actions and checklist guidance: field configuration now launches initial-work-order and external-completed template download/validation, and the construction checklist panel always keeps platform KPI fields visible.
- Connect construction-side collection to the configured checklist: `ConstructionView.vue` now derives site checklist items from configured construction fields, photo slots, and platform KPI fields, and shows them in both inline and drawer collection forms.
- Add a backend shared contract snapshot: `v2-api/app/services/platform/contracts.py` records template types, field schema names, construction payload keys, required KPI keys, review status keys, and review actions for future backend decomposition and PR/patch checks.
- Expose platform persistence status: `v2-api/app/services/platform/persistence.py` and `GET /projects/persistence/status` show current local JSON/file stores, redacted database URL, and safety guarantees without writing data.
- Add PostgreSQL persistence design: `v2-api/app/services/platform/postgres_design.py` describes `platform_project_configs` and `platform_project_config_events`, including indexes, migration notes, rollback notes, and approval gates.
- Add project config persistence contract preview: `v2-api/app/services/platform/config_persistence_contract.py` and `GET /projects/{project_id}/persistence/contract` preview the future persistence record and round-trip preservation for field schema and workflow definitions without connecting to PostgreSQL.
- Add persistence contract names to backend shared contract snapshot: `v2-api/app/services/platform/contracts.py` now exposes `persistence.project_config` so backend decomposition agents do not drift on route, target table, record key, round-trip, migration gate, or safety names.
- Add project readiness check: `v2-api/app/services/platform/readiness.py` and `GET /projects/{project_id}/readiness` report whether a project is ready for template import, construction collection, review, and delivery archive based on fields, photos, KPI fields, modules, and workflow nodes.
- Lock the team operating model: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md` now records the subagent dispatch packet, two-stage review gate, backend/frontend split contract, and next execution queue, while `scripts/verify_pm_platform_team_operating_model.py` guards the setting for future context recovery.
- Add project readiness summary list: `GET /projects/readiness/summary` returns lightweight per-project readiness rows, and `/platform-projects` shows `上线状态` plus an aggregate `上线检查` band.
- Add project readiness action todos: readiness summary now includes `action_counts` for not-ready projects, and `/platform-projects` shows `接入待办` action counts beside the aggregate `上线检查` band.
- Add project readiness action filter: `/platform-projects` now lets operators click a `接入待办` action, see `筛选中`, review only projects needing that action, and use `清除筛选` to return to the full project list.
- Add Project Persistence Readiness Frontend: the field configuration dialog consumes `GET /projects/persistence/status` and `GET /projects/{project_id}/persistence/contract` to show `持久化准备`, current storage, future PostgreSQL target tables, round-trip status, and safety gates without executing a migration.
- Add Platform Migration Readiness Gate: `GET /projects/persistence/migration-readiness` and the `持久化准备` panel show backup, dry-run, verification, rollback, approval, and cutover-flag blockers; `ready_for_migration` remains false until a separate approved migration package exists.
- Add Platform Handoff Readiness Summary: `GET /projects/handoff/readiness` and `/platform-projects` show a review-focused `交付就绪` band with `可评审包`, `production/V3/3.0.77`, `生产迁移未放行`, and `准备 PR 或 patch 交付`; this is a review surface, not a production release or migration approval.
- Add Platform LAN Tablet Access: `scripts/start-platform-local.ps1` supports explicit LAN listening for same-Wi-Fi tablet review through `-HostAddress 0.0.0.0`, while defaulting to `127.0.0.1` and keeping production data, OSS, PostgreSQL, tags, and deployment untouched.

- Add Device Hierarchy Contract: terminal replacement templates now include old terminal/device recovery and required scanned new terminal installation under `terminal_no`, while communication module and SIM card remain conditional accessory replacements; module replacement stays modeled as accessory-device replacement under the task object.
- Refine Device Hierarchy Semantics: module replacement now treats `module_asset_no` as `accessory_new_device` under the meter task object, while terminal replacement keeps `new_terminal_no` as the main `replacement_device` under the terminal task object.
- Add Line Loss Project Preset: project creation now includes a station-area line-loss investigation preset with one active power-supply-unit aggregate, station area as task object, master meter and user task details, and field-collection evidence for issue type and meter photos.
- Add Create Project Field Graph: the new-project draft dialog now reuses the graphical field relationship designer, so operators can see aggregate, task core, device/accessory/evidence, and template binding relationships before creating a project.
- Add Device Replacement Visual Hierarchy: the field graph now distinguishes main replacement devices, accessory replacement confirmations, accessory new devices, old-device recovery, and conditional accessory links; default module replacement drafts also mark the replacement module as required.
- Add Construction Device Hierarchy Sections: construction now groups fields into task core, main device replacement, device/accessory collection, accessory confirmation, conditional accessory collection, and supporting fields; the platform construction entry previews the same grouped sections even with no active task.
- Add Review Device Hierarchy Sections: platform review details now group externally completed work orders into device/accessory collection, accessory confirmation, conditional accessory review, and photo evidence sections; `required_when` is preserved from backend payloads through frontend mapping.
- Add Terminal Review Main Device Sample: local terminal replacement seeding can now create an idempotent external-completed review sample, and local platform startup includes it so `/task-hall?project_id=draft-project` shows a real `主设备更换` section for `new_terminal_no`.
- Add Project Board Device Hierarchy Map: `/project-board` now shows aggregate, task core, main-device replacement, accessory confirmation, conditional accessory follow-up, and photo evidence columns, so module replacement and terminal replacement do not collapse into a flat device list.
- Add Construction Conditional Preview: platform construction work-order cards now filter conditional accessory fields and photo slots per work order, so a terminal sample with `通讯模块是否更换=不更换` hides old/new communication module fields and the old-new module photo while keeping SIM replacement fields visible.
- Add Review Conditional Visibility: platform review panels now filter conditional accessory fields and photo slots per selected work order before hierarchy grouping, so terminal replacement confirms accessory changes before showing old/new accessory rows while module replacement remains an accessory-device change under the task object.
- Add Review Required Evidence Gate: platform review now shows grouped missing required field/photo evidence and backend approval rejects incomplete required evidence, while return and exception actions remain available.
- Add Construction Required Collection Gate: submitted construction collections now enforce active required construction fields and photo slots, including `required_when` accessory fields/photos triggered by replacement confirmation; cached drafts remain allowed.
- Add Construction Submit Gap Preview: construction collection forms now show a grouped `施工提交缺口` for missing required fields, photos, and KPI inputs, and platform final submit is disabled until the gap is cleared while draft save remains available.
- Add Field Graph Relationship Lines: the graphical field designer now labels parent-child and conditional lines, shows a legend for parallel core fields, task-object ownership, and condition triggers, and summarizes main-device, accessory-confirmation, and conditional collection counts.
- Add Field Graph Smart Drop: the graphical field designer now includes smart drop targets for task core, main-device replacement, accessory replacement confirmation, and conditional accessory collection; photos stay as evidence when dropped into conditional collection.
- Add Field Graph Tap Drop: smart drop targets now also work by selecting a custom field and clicking/tapping a target, with keyboard support and visible guidance for tablet operators.
- Add Main Old Device Hierarchy: field graph display now distinguishes terminal main-device-before fields from accessory old-device follow-up fields, so old terminal/device recovery does not collapse into accessory-device semantics.
- Add Delivery Archive Readiness Summary: project board now shows a read-only archive readiness panel that classifies approved archive, pending review, returned rework, evidence gap, not-ready, and exception work orders before any archive write path.
- Add Delivery Archive Manifest Preview: project board now previews the read-only delivery package manifest, including ready items, blocker sections, required field/photo evidence, and strict full-package export eligibility.
- Add Delivery Archive Evidence Details: delivery package preview now lists required field and photo evidence with always-required and conditional-trigger labels, so operators can see the exact evidence contract behind the package.
- Add Delivery Archive Blocker Details: delivery package preview now lists blocker work-order details with reason, work object, aggregate value, and handling detail, so operators can clear concrete blockers before archive export.
- Add Device Replacement Hierarchy Mode: field graph and readiness evidence now explicitly distinguish module replacement as task-object accessory replacement and terminal replacement as main-device replacement followed by accessory confirmation.
- Add Construction Hierarchy Intent Labels: construction collection now translates field roles into on-screen collection intent labels, so operators can tell whether an item is main-device, accessory, accessory-confirmation, conditional follow-up, photo evidence, or KPI data.
- Add Review Hierarchy Intent Labels: review workbench now translates the same field roles into review evidence intent labels, keeping field review, photo review, and KPI evidence aligned with construction collection.
- Add Template Validation Hierarchy Panel: external-completed template validation now surfaces `missing_conditional_field` warnings as a dedicated `层级证据缺口` panel before the generic issue table, so mid-project takeover imports can see missing conditional accessory evidence by row and field.
- Add Import Draft Hierarchy Gap Summary: import draft dry-run results now preserve `missing_conditional_field` warnings as `hierarchy_gap_count` and `hierarchy_gap_items`, and the import preview card continues to show `层级缺口` after validation.
- Add Review Hierarchy Gap Follow-up: external-completed import execution now preserves imported conditional accessory evidence gaps on created platform work orders, and review shows them as `导入层级缺口` before approval.
- Add Review Return Reason Suggestions: imported hierarchy gaps now generate `建议退回原因`, can be applied in `ReviewView`, prefill the `TaskHallView` return prompt, and protect blank returned review actions with a backend fallback reason.
- Add Construction Rework Gap Panel: returned platform work orders now carry structured `rework_evidence_gap_groups`; `/construction` shows a `退回补采清单` so terminal main-device replacement and accessory replacement gaps remain actionable in field rework.
- Add Rework Resubmission Audit Trail: returned platform work orders now append a `rework_submitted` event when construction resubmits, construction shows `返工已重新提交审阅`, and review history labels it as `返工重新提交`.
- Add Review Deep Link SPA Fallback: direct `/review/:groupId` browser links now return the Vue app shell, while device replacement hierarchy guards continue to distinguish module replacement under the task object from terminal replacement with accessory confirmation.
- Add Dashboard Metrics Schema Contract: project field schema now preserves structured dashboard metric definitions and the project board displays the configured metric口径 for progress, delivery, field collection, review, and KPI views.
- Add Dashboard Metrics Field Graph Editor: the visual field graph now exposes selectable metric口径 cards for progress, delivery, field collection, review quality, and KPI efficiency, and saves them through the existing project schema form.
- Add Single Aggregate Device Hierarchy Guard: backend schema normalization now enforces the one-active-aggregate contract and blocks terminal main-device replacement schemas unless accessory confirmation controls the accessory replacement fields.
- Add Field Graph Aggregate Guard: field graph configuration now shows a `聚合口径` readiness card and blocks extra custom aggregate fields before project create or schema save.
- Add Single Aggregate Readiness: `/projects/{project_id}/readiness` now includes `single_aggregate_field`, and the operator UI labels aggregate misuse as `聚合口径唯一`.
- Add Terminal Accessory Confirmation Gate: field graph details now explain main-device-before, main-device-after, task-object accessory, accessory confirmation, and conditional collection semantics; terminal replacement save validation blocks flattened accessory new-device fields before backend submission.
- Add Project Config Preflight: `GET /projects/persistence/config-preflight` reads the raw local draft store without loading or saving projects, reports legacy field/workflow blockers, and `/platform-projects` shows the read-only `配置预检` panel inside field configuration.

Current execution package:

- Keep the branch ready for PR/patch handoff or the next user-approved persistence slice.
- Use `v2-api/app/services/platform/contracts.py`, `GET /projects/persistence/status`, `v2-api/app/services/platform/postgres_design.py`, `GET /projects/{project_id}/persistence/contract`, and `GET /projects/{project_id}/readiness` as checkpoints before changing persistence, field schema, workflow, import template, construction collection, or review status behavior.
- Keep the package data-safe: no migration execution, no PostgreSQL write path, no production data edit, no official version bump, no tag, no deployment.
- Latest completed package: Replacement Hierarchy Template Apply; the field graph now offers clickable module-replacement and terminal-replacement hierarchy templates, and both new-project and draft-schema editors can apply them into the current field form.
- Latest replacement hierarchy template apply report:
  - `docs/reports/pm-platform-replacement-hierarchy-template-apply-2026-07-03.md`
- Latest completed package: Template Impact Preview; draft field graphs now generate local initial-import and system-external-completed template preview rows, preserve parent and condition hints, and list upload-time platform generated fields separately.
- Latest template impact preview report:
  - `docs/reports/pm-platform-template-impact-preview-2026-07-03.md`
- Latest completed package: Template Workbook Instructions; downloaded project templates now include an `instructions` worksheet explaining hierarchy, conditional collection, platform-fill rules, and the difference between module replacement under a task object and terminal replacement with accessory confirmation.
- Latest template workbook instructions report:
  - `docs/reports/pm-platform-template-workbook-instructions-2026-07-03.md`
- Latest completed package: Template Download Guidance; field graph template preview now shows `Excel说明页`, `template / fields / instructions`, and a download-before hierarchy hint for module/terminal replacement modes.
- Latest template download guidance report:
  - `docs/reports/pm-platform-template-download-guidance-2026-07-03.md`
- Latest completed package: Project Type Preset Guidance; create-project preset selection now shows the selected preset's main field, aggregate field, hierarchy mode, and the one-active-aggregate rule for terminal projects.
- Latest project type preset guidance report:
  - `docs/reports/pm-platform-project-type-preset-guidance-2026-07-03.md`
- Latest completed package: Single Aggregate Device Hierarchy Guard; backend project schema normalization now rejects extra aggregate fields and terminal replacement schemas missing accessory confirmation hierarchy.
- Latest single aggregate device hierarchy guard artifacts:
  - `docs/superpowers/plans/2026-07-03-single-aggregate-device-hierarchy-guard.md`
  - `docs/reports/pm-platform-single-aggregate-device-hierarchy-guard-2026-07-03.md`
- Latest completed package: Field Graph Aggregate Guard; the graphical field designer now surfaces the one-active-aggregate rule and save-time aggregate validation before backend submission.
- Latest field graph aggregate guard artifacts:
  - `docs/superpowers/plans/2026-07-03-field-graph-aggregate-guard.md`
  - `docs/reports/pm-platform-field-graph-aggregate-guard-2026-07-03.md`
- Latest completed package: Single Aggregate Readiness; backend readiness now includes `single_aggregate_field`, and frontend readiness panels map `fix_aggregate_field` for operators.
- Latest single aggregate readiness artifacts:
  - `docs/superpowers/plans/2026-07-03-single-aggregate-readiness.md`
  - `docs/reports/pm-platform-single-aggregate-readiness-2026-07-03.md`
- Latest completed package: Terminal Accessory Confirmation Gate; field graph selected-field hints now describe main-device and accessory hierarchy, and the project save gate blocks terminal accessory fields that skip replacement confirmation.
- Latest terminal accessory confirmation gate artifacts:
  - `docs/superpowers/plans/2026-07-03-terminal-accessory-confirmation-gate.md`
  - `docs/reports/pm-platform-terminal-accessory-confirmation-gate-2026-07-03.md`
- Latest completed package: Project Config Preflight; raw legacy draft stores can now be checked read-only for field schema, workflow, module selection, and store format blockers before normal project load/save/migration.
- Latest project config preflight artifacts:
  - `docs/superpowers/plans/2026-07-03-project-config-preflight.md`
  - `docs/reports/pm-platform-project-config-preflight-2026-07-03.md`
- Latest frontend readiness panel artifacts:
  - `docs/superpowers/plans/2026-07-02-project-readiness-panel-frontend.md`
  - `docs/reports/pm-platform-readiness-panel-frontend-2026-07-02.md`
- Latest readiness summary artifacts:
  - `docs/superpowers/plans/2026-07-02-project-readiness-summary-list.md`
  - `docs/reports/pm-platform-readiness-summary-list-2026-07-02.md`
- Latest readiness action filter artifacts:
  - `docs/superpowers/plans/2026-07-02-project-readiness-action-filter.md`
  - `docs/reports/pm-platform-readiness-action-filter-2026-07-02.md`
- Latest persistence readiness frontend artifacts:
  - `docs/superpowers/plans/2026-07-02-project-persistence-readiness-frontend.md`
  - `docs/reports/pm-platform-persistence-readiness-frontend-2026-07-02.md`
- Latest migration readiness gate artifacts:
  - `docs/superpowers/plans/2026-07-02-platform-migration-readiness-gate.md`
  - `docs/reports/pm-platform-migration-readiness-gate-2026-07-02.md`
- Latest handoff readiness artifacts:
  - `docs/superpowers/plans/2026-07-02-platform-handoff-readiness-summary.md`
  - `docs/reports/pm-platform-handoff-readiness-summary-2026-07-02.md`
- Latest LAN tablet access artifacts:
  - `docs/superpowers/plans/2026-07-02-platform-lan-tablet-access.md`
  - `docs/reports/pm-platform-lan-tablet-access-2026-07-02.md`
- Latest production sync readiness artifacts:
  - `docs/superpowers/plans/2026-07-02-platform-production-3.0.77-sync-readiness.md`
  - `docs/reports/pm-platform-production-3.0.77-sync-readiness-2026-07-02.md`
- Latest device hierarchy refinement artifacts:
  - `docs/reports/pm-platform-device-hierarchy-refinement-2026-07-03.md`
- Latest line-loss preset artifacts:
  - `docs/superpowers/plans/2026-07-03-line-loss-project-preset.md`
  - `docs/reports/pm-platform-line-loss-project-preset-2026-07-03.md`
- Latest create project field graph artifacts:
  - `docs/superpowers/plans/2026-07-03-create-project-field-graph.md`
  - `docs/reports/pm-platform-create-project-field-graph-2026-07-03.md`
- Latest device replacement visual hierarchy artifacts:
  - `docs/superpowers/plans/2026-07-03-device-replacement-visual-hierarchy.md`
  - `docs/reports/pm-platform-device-replacement-visual-hierarchy-2026-07-03.md`
- Latest construction device hierarchy artifacts:
  - `docs/superpowers/plans/2026-07-03-construction-device-hierarchy-sections.md`
  - `docs/reports/pm-platform-construction-device-hierarchy-sections-2026-07-03.md`
- Latest review device hierarchy artifacts:
  - `docs/superpowers/plans/2026-07-03-review-device-hierarchy-sections.md`
  - `docs/reports/pm-platform-review-device-hierarchy-sections-2026-07-03.md`
- Latest terminal review main-device sample artifacts:
  - `docs/superpowers/plans/2026-07-03-terminal-review-main-device-sample.md`
  - `docs/reports/pm-platform-terminal-review-main-device-sample-2026-07-03.md`
- Latest project board device hierarchy map artifacts:
  - `docs/superpowers/plans/2026-07-03-project-board-device-hierarchy-map.md`
  - `docs/reports/pm-platform-project-board-device-hierarchy-map-2026-07-03.md`
- Latest construction conditional preview artifacts:
  - `docs/superpowers/plans/2026-07-03-construction-conditional-preview.md`
  - `docs/reports/pm-platform-construction-conditional-preview-2026-07-03.md`
- Latest review conditional visibility artifacts:
  - `docs/superpowers/plans/2026-07-03-review-conditional-visibility.md`
  - `docs/reports/pm-platform-review-conditional-visibility-2026-07-03.md`
- Latest field graph relationship line artifacts:
  - `docs/superpowers/plans/2026-07-03-field-graph-relationship-lines.md`
  - `docs/reports/pm-platform-field-graph-relationship-lines-2026-07-03.md`
- Latest field graph smart drop artifacts:
  - `docs/superpowers/plans/2026-07-03-field-graph-smart-drop.md`
  - `docs/reports/pm-platform-field-graph-smart-drop-2026-07-03.md`
- Latest field graph tap drop artifacts:
  - `docs/superpowers/plans/2026-07-03-field-graph-tap-drop.md`
  - `docs/reports/pm-platform-field-graph-tap-drop-2026-07-03.md`
- Latest workflow selected node order controls artifacts:
  - `docs/superpowers/plans/2026-07-03-workflow-selected-node-order-controls.md`
  - `docs/reports/pm-platform-workflow-selected-node-order-controls-2026-07-03.md`
- Latest device replacement hierarchy drop artifacts:
  - `docs/superpowers/plans/2026-07-03-device-replacement-hierarchy-drops.md`
  - `docs/reports/pm-platform-device-replacement-hierarchy-drops-2026-07-03.md`
- Latest device hierarchy readiness gate artifacts:
  - `docs/superpowers/plans/2026-07-03-device-hierarchy-readiness-gate.md`
  - `docs/reports/pm-platform-device-hierarchy-readiness-gate-2026-07-03.md`
- Latest main old device hierarchy artifacts:
  - `docs/superpowers/plans/2026-07-03-main-old-device-hierarchy.md`
  - `docs/reports/pm-platform-main-old-device-hierarchy-2026-07-03.md`
- Latest construction required collection gate artifacts:
  - `docs/superpowers/plans/2026-07-03-construction-required-collection-gate.md`
  - `docs/reports/pm-platform-construction-required-collection-gate-2026-07-03.md`
- Latest construction submit gap preview artifacts:
  - `docs/superpowers/plans/2026-07-03-construction-submit-gap-preview.md`
  - `docs/reports/pm-platform-construction-submit-gap-preview-2026-07-03.md`
- Latest review required evidence gate artifacts:
  - `docs/superpowers/plans/2026-07-03-review-required-evidence-gate.md`
  - `docs/reports/pm-platform-review-required-evidence-gate-2026-07-03.md`
- Latest delivery archive readiness artifacts:
  - `docs/superpowers/plans/2026-07-03-delivery-archive-readiness.md`
  - `docs/reports/pm-platform-delivery-archive-readiness-2026-07-03.md`
- Latest delivery archive manifest preview artifacts:
  - `docs/superpowers/plans/2026-07-03-delivery-archive-manifest-preview.md`
  - `docs/reports/pm-platform-delivery-archive-manifest-preview-2026-07-03.md`
- Latest delivery archive evidence detail artifacts:
  - `docs/superpowers/plans/2026-07-03-delivery-archive-evidence-details.md`
  - `docs/reports/pm-platform-delivery-archive-evidence-details-2026-07-03.md`
- Latest delivery archive blocker detail artifacts:
  - `docs/superpowers/plans/2026-07-03-delivery-archive-blocker-details.md`
  - `docs/reports/pm-platform-delivery-archive-blocker-details-2026-07-03.md`
- Latest device replacement hierarchy mode artifacts:
  - `docs/superpowers/plans/2026-07-03-device-replacement-hierarchy-mode.md`
  - `docs/reports/pm-platform-device-replacement-hierarchy-mode-2026-07-03.md`
- Latest construction hierarchy intent label artifacts:
  - `docs/superpowers/plans/2026-07-03-construction-hierarchy-intent-labels.md`
  - `docs/reports/pm-platform-construction-hierarchy-intent-labels-2026-07-03.md`
- Latest review hierarchy intent label artifacts:
  - `docs/superpowers/plans/2026-07-03-review-hierarchy-intent-labels.md`
  - `docs/reports/pm-platform-review-hierarchy-intent-labels-2026-07-03.md`
- Latest template validation hierarchy panel artifacts:
  - `docs/superpowers/plans/2026-07-03-template-validation-hierarchy-panel.md`
  - `docs/reports/pm-platform-template-validation-hierarchy-panel-2026-07-03.md`
- Latest import draft hierarchy gap summary artifacts:
  - `docs/superpowers/plans/2026-07-03-import-draft-hierarchy-gap-summary.md`
  - `docs/reports/pm-platform-import-draft-hierarchy-gap-summary-2026-07-03.md`
- Latest review hierarchy gap follow-up artifacts:
  - `docs/superpowers/plans/2026-07-03-review-hierarchy-gap-followup.md`
  - `docs/reports/pm-platform-review-hierarchy-gap-followup-2026-07-03.md`
- Latest review return reason suggestion artifacts:
  - `docs/superpowers/plans/2026-07-03-review-return-reason-suggestions.md`
  - `docs/reports/pm-platform-review-return-reason-suggestions-2026-07-03.md`
- Latest construction rework gap panel artifacts:
  - `docs/superpowers/plans/2026-07-03-construction-rework-gap-panel.md`
  - `docs/reports/pm-platform-construction-rework-gap-panel-2026-07-03.md`
- Latest rework resubmission audit artifacts:
  - `docs/superpowers/plans/2026-07-03-rework-resubmission-audit-trail.md`
  - `docs/reports/pm-platform-rework-resubmission-audit-2026-07-03.md`
- Latest review deep link SPA fallback artifacts:
  - `docs/superpowers/plans/2026-07-03-review-deep-link-spa-fallback.md`
  - `docs/reports/pm-platform-review-deep-link-spa-fallback-2026-07-03.md`
- Latest dashboard metrics schema contract artifacts:
  - `docs/superpowers/plans/2026-07-03-dashboard-metrics-schema-contract.md`
  - `docs/reports/pm-platform-dashboard-metrics-schema-contract-2026-07-03.md`
- Latest dashboard metrics field graph editor artifacts:
  - `docs/superpowers/plans/2026-07-03-dashboard-metrics-field-graph-editor.md`
  - `docs/reports/pm-platform-dashboard-metrics-field-graph-editor-2026-07-03.md`
- Latest replacement hierarchy template apply artifacts:
  - `docs/reports/pm-platform-replacement-hierarchy-template-apply-2026-07-03.md`
- Latest template impact preview artifacts:
  - `docs/reports/pm-platform-template-impact-preview-2026-07-03.md`
- Latest template workbook instructions artifacts:
  - `docs/reports/pm-platform-template-workbook-instructions-2026-07-03.md`
- Latest template download guidance artifacts:
  - `docs/superpowers/plans/2026-07-03-template-download-guidance.md`
  - `docs/reports/pm-platform-template-download-guidance-2026-07-03.md`
- Latest project type preset guidance artifacts:
  - `docs/superpowers/plans/2026-07-03-project-type-preset-guidance.md`
  - `docs/reports/pm-platform-project-type-preset-guidance-2026-07-03.md`
- Latest device replacement confirmation precision artifacts:
  - `docs/superpowers/plans/2026-07-03-device-replacement-confirmation-precision.md`
  - `docs/reports/pm-platform-device-replacement-confirmation-precision-2026-07-03.md`
- Latest handoff config preflight summary artifacts:
  - `docs/superpowers/plans/2026-07-03-handoff-config-preflight-summary.md`
  - `docs/reports/pm-platform-handoff-config-preflight-summary-2026-07-03.md`
- Latest project list config preflight fallback artifacts:
  - `docs/superpowers/plans/2026-07-03-project-list-config-preflight-fallback.md`
  - `docs/reports/pm-platform-project-list-config-preflight-fallback-2026-07-03.md`

Next packages after this one:

1. If the user chooses PR: push `pm-platform/production-3.0.77-sync` and open a PR to `production/V3/3.0.77` using the refreshed PR body.
2. If the user chooses patch: export the branch as a patch package with the same baseline and safety notes.
3. After explicit user approval, create the Alembic migration for the first PostgreSQL persistence slice.
4. After the migration package exists, add persistence-backed read/write contract tests before enabling PostgreSQL reads in production.

Team execution rule for backend decomposition:

- Backend Field Schema Agent owns field hierarchy and capture rules.
- Backend Import And Template Agent owns template generation, preview, validation, import draft, import batch, and rollback records.
- Backend Construction And Review Agent owns work-order collection, KPI fields, review status, and evidence records.
- Codex Integrator serializes shared file edits in `v2-api/app/api/routes/projects.py`, `v2-api/app/services/platform/templates.py`, `v2-web/src/views/ProjectsView.vue`, and shared API types.
