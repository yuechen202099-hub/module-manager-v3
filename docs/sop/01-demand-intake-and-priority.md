# Demand Intake And Priority SOP

## Purpose

Make every request traceable before it enters the production maintenance line.

## Priority Levels

| Level | Definition | Response |
| --- | --- | --- |
| P0 | Production is blocked or data is wrong: login failure,施工端无法作业,上传阻断,异常工单/00000000类错单,核心数据错配或丢失 | Freeze unrelated work, protect evidence, fix or roll back immediately |
| P1 | Important production workflow degraded but workaround exists | Same-day fix or scheduled hotfix |
| P2 | Normal bug or small production feature | Patch release, version `+0.01` |
| P3 | Documentation, cleanup, internal improvement | No app version bump unless runtime behavior changes |

## Intake Checklist

- [ ] Request source and time recorded.
- [ ] Affected role identified: admin, reviewer, constructor, server admin, or developer group.
- [ ] Affected workflow identified: login, construction, review, KPI, dashboard, group backoffice, import/export, deployment.
- [ ] Production version confirmed before analysis.
- [ ] Development version content explicitly excluded unless user asks for it.
- [ ] Data risk classified: no data change, read-only data check, data repair, migration, OSS/filesystem action.
- [ ] Priority assigned.

## P0 Entry Rule

If the request mentions production施工 impact, wrong work orders, data corruption, missing uploads, inability to log in, or broken core pages, treat it as P0 until proven otherwise.

## Output Required Before Work

For P0/P1, state:

- current production version if known,
- suspected blast radius,
- immediate containment plan,
- verification plan,
- whether server/data backup is required before touching production.
