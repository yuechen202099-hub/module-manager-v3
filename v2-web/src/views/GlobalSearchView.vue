<script setup lang="ts">
import { CopyDocument, EditPen } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import DataCenterFilters from '@/components/data-center/DataCenterFilters.vue'
import DataCenterReviewDialog from '@/components/data-center/DataCenterReviewDialog.vue'
import { DATA_CENTER_PAGE_SIZES, useDataCenterQuery } from '@/composables/useDataCenterQuery'
import type { DataCenterPageSize, DataCenterRow } from '@/api/types'

const {
  query,
  rows,
  total,
  loading,
  errorMessage,
  activeRow,
  setFilters,
  setPage,
  setPageSize,
  openReview,
  closeReview,
  refresh,
} = useDataCenterQuery()

function statusType(value: string) {
  if (['archived', 'passed', 'manual', 'manual_confirmed', 'complete', 'completed'].includes(value)) return 'success'
  if (['pending', 'in_progress', 'unreadable'].includes(value)) return 'warning'
  if (['mismatched', 'failed', 'open', 'incomplete'].includes(value)) return 'danger'
  return 'info'
}

const constructionLabels: Record<string, string> = {
  unconstructed: '未施工',
  in_progress: '施工中',
  completed: '已施工',
}

const archiveLabels: Record<string, string> = {
  unarchived: '未归档',
  pending: '待归档',
  archived: '已归档',
}

const barcodeLabels: Record<string, string> = {
  passed: '通过',
  manual: '人工',
  manual_confirmed: '人工确认',
  mismatched: '不一致',
  failed: '失败',
  unreadable: '不可读',
  ineligible: '不适用',
}

const classificationLabels: Record<string, string> = {
  complete: '完整',
  incomplete: '缺失',
}

function labelOf(labels: Record<string, string>, value: string) {
  return labels[value] || value || '-'
}

async function copyValue(value: string | number | undefined, label: string) {
  const text = String(value || '').trim()
  if (!text) {
    ElMessage.warning(`${label}为空`)
    return
  }
  await navigator.clipboard.writeText(text)
  ElMessage.success(`已复制${label}`)
}

async function promptScanKeyword() {
  try {
    const result = await ElMessageBox.prompt('输入扫码内容', '扫码', {
      confirmButtonText: '搜索',
      cancelButtonText: '取消',
      inputValue: query.keyword,
    })
    void setFilters({ keyword: String(result.value || '') })
  } catch {
    // canceled
  }
}

function handleReview(row: DataCenterRow) {
  void openReview(row)
}

function handlePageSize(size: number) {
  void setPageSize(size as DataCenterPageSize)
}
</script>

<template>
  <section class="global-search-page">
    <div class="panel search-panel">
      <div class="search-heading">
        <div>
          <p class="eyebrow">管理员后台</p>
          <h2>数据中台</h2>
        </div>
        <el-tag type="warning" effect="plain">管理员</el-tag>
      </div>
      <DataCenterFilters
        :model-value="query"
        :loading="loading"
        @update="setFilters"
        @reset="setFilters({
          dataType: 'all',
          constructionStatus: 'all',
          terminalStatus: 'all',
          archiveStatus: 'all',
          barcodeStatus: 'all',
          barcodeEligibility: 'all',
          classificationStatus: 'all',
          exceptionStatus: '',
          installer: '',
          installerSource: 'all',
          hasPhotos: false,
          dateFrom: '',
          dateTo: '',
          activityDateFrom: '',
          activityDateTo: '',
          terminal: '',
          keyword: '',
          sort: 'updated_desc',
        })"
        @scan="promptScanKeyword"
      />
    </div>

    <div class="panel result-panel">
      <div class="result-heading">
        <div>
          <h3>资料组字段</h3>
          <span>共 {{ total }} 条</span>
        </div>
      </div>

      <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false" />
      <el-empty v-if="!loading && !rows.length && !errorMessage" description="暂无数据" />

      <el-table
        v-else
        v-loading="loading"
        :data="rows"
        row-key="id"
        height="calc(100vh - 330px)"
        class="result-table"
      >
        <el-table-column prop="kind" label="类型" width="86">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.kind === 'unmatched' ? 'warning' : 'info'">
              {{ row.kind === 'unmatched' ? '未匹配' : '资料组' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="ID" min-width="160" show-overflow-tooltip />
        <el-table-column label="表号" min-width="150">
          <template #default="{ row }">
            <button class="plain-link" @click="copyValue(row.meterNo, '表号')">{{ row.meterNo || '-' }}</button>
          </template>
        </el-table-column>
        <el-table-column prop="meterMatchKey" label="匹配键" min-width="130" show-overflow-tooltip />
        <el-table-column prop="terminal" label="终端" min-width="130" />
        <el-table-column prop="installer" label="安装人员" min-width="120" show-overflow-tooltip />
        <el-table-column label="施工" width="96">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.constructionStatus)">
              {{ labelOf(constructionLabels, row.constructionStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="归档" width="96">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.archiveStatus)">
              {{ labelOf(archiveLabels, row.archiveStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="扫码" width="106">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.barcodeStatus)">
              {{ labelOf(barcodeLabels, row.barcodeStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="96">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="statusType(row.classificationStatus)">
              {{ labelOf(classificationLabels, row.classificationStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="photoCount" label="照片" width="76" />
        <el-table-column prop="collector" label="采集器" min-width="140" show-overflow-tooltip />
        <el-table-column prop="moduleAssetNo" label="模块" min-width="140" show-overflow-tooltip />
        <el-table-column prop="address" label="地址" min-width="280" show-overflow-tooltip />
        <el-table-column label="操作" width="118" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="复制ID" placement="top">
                <el-button :icon="CopyDocument" circle @click="copyValue(row.id, 'ID')" />
              </el-tooltip>
              <el-tooltip content="审阅" placement="top">
                <el-button type="primary" :icon="EditPen" circle @click="handleReview(row)" />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- page-sizes="[20, 50, 100]" -->
      <el-pagination
        v-model:current-page="query.page"
        class="result-pagination"
        layout="sizes, prev, pager, next, total"
        :page-size="query.pageSize"
        :page-sizes="DATA_CENTER_PAGE_SIZES"
        :total="total"
        @current-change="setPage"
        @size-change="handlePageSize"
      />
    </div>

    <DataCenterReviewDialog
      :model-value="query.review"
      :row="activeRow"
      @update:model-value="($event) => (!$event ? closeReview() : undefined)"
      @updated="refresh"
      @matched="refresh"
    />
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
  margin-bottom: 14px;
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

.result-panel {
  display: grid;
  gap: 12px;
}

.result-table {
  width: 100%;
}

.result-pagination {
  justify-self: end;
  max-width: 100%;
  overflow-x: auto;
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
</style>
