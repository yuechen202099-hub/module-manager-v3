<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import {
  allocateCollectorPool,
  fetchCollectorTransferProjects,
  fetchCollectorTransferRuns,
} from '@/api/services'
import type { CollectorTransferRun, Project } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const projects = ref<Project[]>([])
const projectId = ref('')
const runs = ref<CollectorTransferRun[]>([])
const runId = ref('')
const loading = ref(false)

const isAdmin = computed(() => {
  const roles = new Set([auth.user?.role, ...(auth.user?.roles || [])].filter(Boolean))
  return roles.has('admin')
})
const selectedRun = computed(() => runs.value.find((run) => run.id === runId.value) || null)

onMounted(() => {
  void loadProjects()
})

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await fetchCollectorTransferProjects()
    projectId.value = projects.value[0]?.id || ''
    await loadRuns()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批次列表加载失败')
  } finally {
    loading.value = false
  }
}

async function loadRuns() {
  if (!projectId.value) {
    runs.value = []
    runId.value = ''
    return
  }
  const loadedRuns = await fetchCollectorTransferRuns(projectId.value)
  runs.value = loadedRuns
  runId.value = loadedRuns.some((run) => run.id === runId.value) ? runId.value : loadedRuns[0]?.id || ''
}

async function changeProject() {
  loading.value = true
  try {
    await loadRuns()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '盘点批次加载失败')
  } finally {
    loading.value = false
  }
}

async function allocatePool() {
  if (!isAdmin.value || !runId.value) return
  loading.value = true
  try {
    const result = await allocateCollectorPool(runId.value)
    ElMessage.success(`本地替换池已完成一次性分配：${result.assignment_count} 条`)
    await loadRuns()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '替换池随机分配失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="collector-batches" :aria-busy="loading">
    <header>
      <p>管理员操作</p>
      <h1>替换池批次管理</h1>
      <span>在盘点与补拍完成后，为选定批次执行一次性随机分配。</span>
    </header>

    <section v-if="isAdmin" class="batch-card">
      <label>项目
        <select v-model="projectId" aria-label="批次管理项目" :disabled="loading" @change="changeProject">
          <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option>
        </select>
      </label>
      <label>盘点批次
        <select v-model="runId" aria-label="批次管理盘点批次" :disabled="loading || !runs.length">
          <option v-for="run in runs" :key="run.id" :value="run.id">{{ run.name }}</option>
        </select>
      </label>
      <p v-if="selectedRun" class="summary">{{ selectedRun.assignment_count }} 已分配 / {{ selectedRun.collector_requirement_count }} 个需求</p>
      <p v-else class="summary">请选择已有盘点批次后执行分配。</p>
      <button data-testid="allocate-pool" type="button" :disabled="loading || !runId" @click="allocatePool">执行随机分配</button>
    </section>
    <p v-else class="forbidden">仅管理员可以执行替换池分配。</p>
  </main>
</template>

<style scoped>
.collector-batches { min-height: 100%; padding: 32px; background: #f4f6f2; color: #17211b; }
header, .batch-card { max-width: 760px; margin: 0 auto; }
header p { margin: 0; color: #4f6d52; font-size: 13px; font-weight: 700; }
h1 { margin: 6px 0; font-size: 24px; }
header span { color: #5d665f; }
.batch-card { display: grid; gap: 16px; margin-top: 24px; padding: 24px; border: 1px solid #d8e0d7; border-radius: 12px; background: #fff; }
label { display: grid; gap: 7px; color: #445148; font-weight: 700; }
select { min-height: 40px; border: 1px solid #bfcbbf; border-radius: 7px; padding: 0 10px; background: #fff; }
.summary { margin: 0; color: #526056; }
button { min-height: 42px; border: 0; border-radius: 7px; background: #1f5c38; color: #fff; font-weight: 700; cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .5; }
.forbidden { max-width: 760px; margin: 24px auto; color: #9e3f3f; }
@media (max-width: 700px) { .collector-batches { padding: 20px 16px; } }
</style>
