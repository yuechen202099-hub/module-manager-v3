import { currentProjectId, projectScopedPath } from './services'

const currentProjectIdContract: () => string = currentProjectId
const projectScopedPathContract: (path: string, projectId?: string) => string = projectScopedPath

void currentProjectIdContract
void projectScopedPathContract
