import { defineStore } from 'pinia'

import * as services from '@/api/services'
import type { MaterialGroup, Project, ProjectCreatePayload, ReviewPhoto, ReviewTask, TaskStatus } from '@/api/types'

type WorkspaceState = {
  loading: boolean
  activeProjectId: string
  projects: Project[]
  tasks: ReviewTask[]
  groups: MaterialGroup[]
  activeGroup: MaterialGroup | null
  activePhotos: ReviewPhoto[]
}

const activeProjectStorageKey = 'module_manager_active_project_id'

function readActiveProjectId() {
  if (typeof localStorage === 'undefined') return ''
  return localStorage.getItem(activeProjectStorageKey) || ''
}

function writeActiveProjectId(projectId: string) {
  if (typeof localStorage === 'undefined') return
  if (projectId) {
    localStorage.setItem(activeProjectStorageKey, projectId)
    return
  }
  localStorage.removeItem(activeProjectStorageKey)
}

type RouteProjectIdValue = string | null | Array<string | null> | undefined

function normalizeRouteProjectId(value: RouteProjectIdValue) {
  const rawValue = Array.isArray(value) ? value[0] : value
  return String(rawValue || '').trim()
}

export const useWorkspaceStore = defineStore('workspace', {
  state: (): WorkspaceState => ({
    loading: false,
    activeProjectId: readActiveProjectId(),
    projects: [],
    tasks: [],
    groups: [],
    activeGroup: null,
    activePhotos: [],
  }),
  getters: {
    activeProject: (state) =>
      state.projects.find((project) => project.id === state.activeProjectId) || state.projects[0] || null,
    dashboardStats: (state) => {
      const project = state.projects.find((item) => item.id === state.activeProjectId) || state.projects[0]
      return {
        totalGroups: project?.totalGroups || 0,
        completedGroups: project?.completedGroups || 0,
        exceptionGroups: project?.exceptionGroups || 0,
        activeTasks: state.tasks.filter((task) => task.status === 'in_review').length,
      }
    },
  },
  actions: {
    ensureActiveProject() {
      const fallbackProjectId = this.projects[0]?.id || ''
      const nextProjectId = this.projects.some((project) => project.id === this.activeProjectId)
        ? this.activeProjectId
        : fallbackProjectId
      if (nextProjectId !== this.activeProjectId) {
        this.activeProjectId = nextProjectId
        writeActiveProjectId(nextProjectId)
      }
    },
    selectProject(projectId: string) {
      if (!projectId) return
      if (this.projects.length && !this.projects.some((project) => project.id === projectId)) return
      this.activeProjectId = projectId
      writeActiveProjectId(projectId)
    },
    selectRouteProject(projectId: RouteProjectIdValue) {
      const normalizedProjectId = normalizeRouteProjectId(projectId)
      if (normalizedProjectId) this.selectProject(normalizedProjectId)
    },
    async loadProjects() {
      this.projects = await services.fetchProjects()
      this.ensureActiveProject()
    },
    async createProjectDraft(payload: ProjectCreatePayload) {
      const project = await services.createProject(payload)
      await this.loadProjects()
      this.selectProject(project.id)
      return project
    },
    async bootstrap() {
      this.loading = true
      try {
        const [projects, tasks, groups] = await Promise.all([
          services.fetchProjects(),
          services.fetchTasks(),
          services.fetchTaskGroups(),
        ])
        this.projects = projects
        this.tasks = tasks
        this.groups = groups
        this.ensureActiveProject()
      } finally {
        this.loading = false
      }
    },
    async claimTask(taskId: string) {
      const claimed = await services.claimTask(taskId)
      this.tasks = this.tasks.map((task) => (task.id === taskId ? claimed : task))
    },
    async loadReviewGroup(groupId: string) {
      this.loading = true
      try {
        const result = await services.fetchGroup(groupId)
        this.activeGroup = result.group
        this.activePhotos = result.photos
      } finally {
        this.loading = false
      }
    },
    async saveReview(status: TaskStatus) {
      if (!this.activeGroup) return
      const updated = await services.saveReview(this.activeGroup.id, status)
      this.activeGroup = updated
      this.groups = this.groups.map((group) => (group.id === updated.id ? updated : group))
    },
  },
})
