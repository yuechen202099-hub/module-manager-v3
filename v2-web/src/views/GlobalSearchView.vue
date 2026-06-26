<script setup lang="ts">
import { CopyDocument, FolderOpened, Refresh, Search, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { searchGroups } from '@/api/services'
import type { MaterialGroup } from '@/api/types'

const router = useRouter()

const query = ref('')
const terminal = ref('')
const loading = ref(false)
const searched = ref(false)
const total = ref(0)
const terminals = ref<string[]>([])
const groups = ref<MaterialGroup[]>([])
const errorMessage = ref('')

const trimmedQuery = computed(() => query.value.trim())
const canSearch = computed(() => Boolean(trimmedQuery.value || terminal.value))

const statusLabels: Record<string, string> = {
  pending: '待审阅',
  unreviewed: '待审阅',
  incomplete: '需补充',
  exception: '异常',
  approved: '已通过',
  complete: '已完成',
  locked: '已锁定',
  released: '已释放',
  published: '已发布',
}

async function runSearch() {
  if (!canSearch.value) {
    ElMessage.warning('请输入表号、模块号、采集器号或选择终端')
    return
  }
  loading.value = true
  searched.value = true
  errorMessage.value = ''
  try {
    const result = await searchGroups({
      query: trimmedQuery.value,
      terminal: terminal.value,
      limit: 80,
      offset: 0,
    })
    total.value = result.total
    terminals.value = result.terminals
    groups.value = result.items
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '搜索失败'
    groups.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function resetSearch() {
  query.value = ''
  terminal.value = ''
  searched.value = false
  errorMessage.value = ''
  groups.value = []
  total.value = 0
}

function statusLabel(status: string) {
  return statusLabels[status] || status || '未知'
}

function taskIdOf(group: MaterialGroup) {
  return String(group.taskId || '').trim()
}

function openReview(group: MaterialGroup) {
  void router.push({
    path: '/task-hall',
    query: {
      taskId: taskIdOf(group),
      groupId: group.id,
    },
  })
}

function openConstruction(group: MaterialGroup) {
  void router.push({
    path: '/construction',
    query: {
      taskId: taskIdOf(group),
      groupId: group.id,
    },
  })
}

async function copyValue(value: string, label: string) {
  const text = String(value || '').trim()
  if (!text) {
    ElMessage.warning(`${label}为空`)
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制${label}`)
  } catch {
    const input = document.createElement('textarea')
    input.value = text
    input.setAttribute('readonly', 'readonly')
    input.style.position = 'fixed'
    input.style.left = '-9999px'
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    document.body.removeChild(input)
    ElMessage.success(`已复制${label}`)
  }
}
</script>

<template>
  <section class="global-search-page">
    <div class="panel search-panel">
      <div class="search-heading">
        <div>
          <p class="eyebrow">资料组定位</p>
          <h2>全局搜索</h2>
        </div>
        <el-tag type="warning" effect="plain">管理员</el-tag>
      </div>

      <div class="search-bar">
        <el-input
          v-model="query"
          clearable
          size="large"
          placeholder="输入表号、模块号、采集器号、地址"
          :prefix-icon="Search"
          @keyup.enter="runSearch"
        />
        <el-select v-model="terminal" clearable filterable size="large" placeholder="终端">
          <el-option v-for="item in terminals" :key="item" :label="item" :value="item" />
        </el-select>
        <el-button type="primary" size="large" :icon="Search" :loading="loading" @click="runSearch">搜索</el-button>
        <el-button size="large" :icon="Refresh" @click="resetSearch">重置</el-button>
      </div>
    </div>

    <div class="panel result-panel">
      <div class="result-heading">
        <div>
          <h3>搜索结果</h3>
          <span v-if="searched">共 {{ total }} 条</span>
          <span v-else>等待输入条件</span>
        </div>
      </div>

      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />

      <el-empty v-if="!loading && searched && !groups.length && !errorMessage" description="没有找到资料组" />
      <el-empty v-else-if="!loading && !searched" description="输入条件后开始定位资料组" />

      <el-table v-else v-loading="loading" :data="groups" height="calc(100vh - 330px)" class="result-table">
        <el-table-column label="表号" min-width="150">
          <template #default="{ row }">
            <button class="plain-link" @click="copyValue(row.meterNo, '表号')">{{ row.meterNo || '-' }}</button>
          </template>
        </el-table-column>
        <el-table-column prop="terminal" label="终端" min-width="120" />
        <el-table-column label="任务" width="90">
          <template #default="{ row }">#{{ row.taskId || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="照片" width="82">
          <template #default="{ row }">{{ row.photoCount }}</template>
        </el-table-column>
        <el-table-column prop="reviewer" label="审阅员" min-width="110" />
        <el-table-column prop="address" label="地址" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="查看审阅" placement="top">
                <el-button :icon="View" circle @click="openReview(row)" />
              </el-tooltip>
              <el-tooltip content="打开施工" placement="top">
                <el-button :icon="FolderOpened" circle @click="openConstruction(row)" />
              </el-tooltip>
              <el-tooltip content="复制资料组 ID" placement="top">
                <el-button :icon="CopyDocument" circle @click="copyValue(row.id, '资料组 ID')" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>

<style scoped>
.global-search-page {
  display: grid;
  gap: 12px;
}

.search-panel,
.result-panel {
  padding: 18px;
}

.search-heading,
.result-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.search-heading h2,
.result-heading h3 {
  margin: 4px 0 0;
  color: var(--v2-text-strong);
  letter-spacing: 0;
}

.result-heading span {
  display: inline-block;
  margin-top: 4px;
  color: var(--v2-text-muted);
  font-size: 12px;
}

.search-bar {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(160px, 220px) auto auto;
  gap: 10px;
  margin-top: 14px;
  align-items: center;
}

.result-panel {
  display: grid;
  gap: 12px;
}

.result-table {
  width: 100%;
}

.plain-link {
  appearance: none;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--v2-accent);
  font: inherit;
  cursor: pointer;
}

.plain-link:hover {
  text-decoration: underline;
}

.row-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 860px) {
  .search-heading,
  .result-heading {
    align-items: flex-start;
  }

  .search-bar {
    grid-template-columns: 1fr;
  }
}
</style>
