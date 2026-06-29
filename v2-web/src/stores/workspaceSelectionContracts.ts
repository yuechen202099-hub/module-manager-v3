import type { Project } from '@/api/types'
import { useWorkspaceStore } from './workspace'

type WorkspaceStore = ReturnType<typeof useWorkspaceStore>

declare const workspace: WorkspaceStore

const activeProjectIdContract: string = workspace.activeProjectId
const activeProjectContract: Project | null = workspace.activeProject
const selectProjectContract: (projectId: string) => void = workspace.selectProject

void activeProjectIdContract
void activeProjectContract
void selectProjectContract
