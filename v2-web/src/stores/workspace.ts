import { defineStore } from 'pinia'

import * as services from '@/api/services'
import type { MaterialGroup, Project, ReviewPhoto, ReviewTask, TaskStatus } from '@/api/types'

type WorkspaceState = {
  loading: boolean
  projects: Project[]
  tasks: ReviewTask[]
  groups: MaterialGroup[]
  activeGroup: MaterialGroup | null
  activePhotos: ReviewPhoto[]
}

export const useWorkspaceStore = defineStore('workspace', {
  state: (): WorkspaceState => ({
    loading: false,
    projects: [],
    tasks: [],
    groups: [],
    activeGroup: null,
    activePhotos: [],
  }),
  getters: {
    activeProject: (state) => state.projects[0] || null,
    dashboardStats: (state) => {
      const project = state.projects[0]
      return {
        totalGroups: project?.totalGroups || 0,
        completedGroups: project?.completedGroups || 0,
        exceptionGroups: project?.exceptionGroups || 0,
        activeTasks: state.tasks.filter((task) => task.status === 'in_review').length,
      }
    },
  },
  actions: {
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
