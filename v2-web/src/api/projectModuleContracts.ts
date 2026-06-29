import { fetchProjectModuleSections, fetchProjectsWithModules } from './services'
import type { Project } from './types'

type ProjectModuleSections = Awaited<ReturnType<typeof fetchProjectModuleSections>>

const projectListContract: () => Promise<Project[]> = fetchProjectsWithModules
const projectModulesContract: Project['modules'] = []

function assertProjectModuleShape(sections: ProjectModuleSections) {
  sections.progress.stage
  sections.delivery.completedItems
  sections.field.photoRowsLinked
  sections.review.pendingGroups
  sections.risks.deliveryBlockers
  sections.tasks.archived
}

void projectListContract
void projectModulesContract
void assertProjectModuleShape
