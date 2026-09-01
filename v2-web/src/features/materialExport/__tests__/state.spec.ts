import { describe, expect, it } from 'vitest'
import type { ReviewTask } from '../../../api/types'
import { sortExportTasks } from '../state'

function task(terminal: string, priority: boolean, completion: number): ReviewTask {
  return {
    id: terminal,
    projectId: 'project-a',
    name: terminal,
    stage: terminal,
    status: 'pending',
    terminal,
    totalGroups: 100,
    claimedGroups: completion,
    completedGroups: 0,
    renovationCount: 100,
    constructionUploadedCount: completion,
    constructionPriority: priority,
  }
}

describe('material export task state', () => {
  it('sorts priority then completion descending then terminal', () => {
    const ordered = sortExportTasks([task('B', false, 80), task('A', true, 20), task('C', true, 90)])
    expect(ordered.map((item) => item.terminal)).toEqual(['C', 'A', 'B'])
  })
})
