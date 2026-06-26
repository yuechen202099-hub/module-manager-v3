# Production SOP Index

This directory is the standard operating procedure entrypoint for the production maintenance line.

Current production baseline: `V3.0.38`.

Use these SOPs for every production-impacting change:

- `01-demand-intake-and-priority.md` - demand intake and priority classification
- `02-production-branch-versioning.md` - production branch and version rules
- `03-change-analysis-and-tdd.md` - investigation, impact analysis, and test-first work
- `04-subagent-review-template.md` - independent review requirements
- `05-release-package-and-hash.md` - release package, dependency, hash, and static asset gates
- `06-production-deploy-runbook.md` - production deployment runbook
- `07-rollback-and-incident-review.md` - rollback and incident review
- `08-business-acceptance-templates.md` - business acceptance templates

Release records live under `ops/releases/`.
Incident records live under `ops/incidents/`.
