#!/usr/bin/env node

const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const stateRepository = fs.readFileSync(path.join(root, 'v2-api', 'app', 'services', 'state_repository.py'), 'utf8')
const localSimulation = fs.readFileSync(path.join(root, 'v2-api', 'app', 'services', 'local_simulation.py'), 'utf8')
const projectBoard = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ProjectBoardView.vue'), 'utf8')
const postgresStart = stateRepository.indexOf('class PostgresStateRepository')
assert.notEqual(postgresStart, -1, 'PostgresStateRepository must exist')
const postgresRepository = stateRepository.slice(postgresStart)

const summaryMatch = postgresRepository.match(/def summary\(self\)([\s\S]*?)\n    def _task_by_legacy_id/)
assert.ok(summaryMatch, 'Postgres summary implementation must exist')
const summaryBlock = summaryMatch[1]

const postgresWorkloadMatch = postgresRepository.match(/def installer_daily_workload\(self, installer: str\)([\s\S]*?)\n    def list_team_states/)
assert.ok(postgresWorkloadMatch, 'Postgres installer_daily_workload implementation must exist')
const postgresWorkloadBlock = postgresWorkloadMatch[1]

const localWorkloadMatch = localSimulation.match(/def installer_daily_workload\(installer: str\)([\s\S]*?)\r?\n\r?\ndef refresh_summary/)
assert.ok(localWorkloadMatch, 'local installer_daily_workload implementation must exist')
const localWorkloadBlock = localWorkloadMatch[1]

const localSummaryMatch = localSimulation.match(/def summarize_installers_by_group\(groups: list\[dict\[str, Any\]\]\)([\s\S]*?)\r?\n\r?\ndef _date_key_from_value/)
assert.ok(localSummaryMatch, 'local summarize_installers_by_group implementation must exist')
const localSummaryBlock = localSummaryMatch[1]

assert.doesNotMatch(
  summaryBlock,
  /installer_items\s*=\s*sorted\([\s\S]*?\)\[:8\]/,
  'project board installer distribution must not truncate to the historical top 8 installers',
)
assert.match(
  summaryBlock,
  /installer_total\s*=\s*sum\(len\(group_ids\) for _, group_ids in installer_items\)/,
  'installer share denominator should include every installer returned by the distribution',
)
assert.doesNotMatch(
  localSummaryBlock,
  /sorted\(counts\.items\(\), key=lambda item: \(-item\[1\], item\[0\]\)\)\[:8\]/,
  'local project board installer distribution must not truncate to the historical top 8 installers',
)
assert.match(
  postgresWorkloadBlock,
  /aliases\s*=\s*local_simulation\.installer_actor_aliases\(target\)/,
  'Postgres daily workload must resolve installer account/name aliases',
)
assert.match(
  postgresWorkloadBlock,
  /Photo\.creator\.in_\(tuple\(aliases\)\)/,
  'Postgres daily workload must match photos by all installer aliases, not only one exact display string',
)
assert.match(
  localWorkloadBlock,
  /aliases\s*=\s*installer_actor_aliases\(target\)/,
  'local daily workload must resolve installer account/name aliases',
)
assert.match(
  localWorkloadBlock,
  /str\(photo\.get\("creator"\) or ""\)\.strip\(\) in aliases/,
  'local daily workload must match photos by all installer aliases',
)
assert.match(
  projectBoard,
  /const installerWorkloadFetchConcurrency = 3/,
  'project board scoped workload loading should cap concurrent daily-workload requests',
)
assert.match(
  projectBoard,
  /async function loadInstallerWorkloadsInBatches\(installers: string\[\]\)/,
  'project board should load installer workloads in bounded batches',
)
assert.doesNotMatch(
  projectBoard,
  /Promise\.all\(missing\.map\(\(installer\) => fetchInstallerWorkload\(installer\)\)\)/,
  'project board must not request all installer daily workloads concurrently',
)

console.log('installer workload completion visibility checks passed')
