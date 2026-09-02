<script setup lang="ts">
import { Camera, Refresh, Search } from '@element-plus/icons-vue'

import type {
  DataCenterDataType,
  DataCenterInstallerSource,
} from '@/api/types'
import type { DataCenterRouteQuery } from '@/composables/useDataCenterQuery'

const props = defineProps<{
  modelValue: DataCenterRouteQuery
  loading?: boolean
}>()

const emit = defineEmits<{
  (event: 'update', value: Partial<DataCenterRouteQuery>): void
  (event: 'reset'): void
  (event: 'scan'): void
}>()

const dataTypes: Array<{ label: string; value: DataCenterDataType }> = [
  { label: '全部', value: 'all' },
  { label: '资料组', value: 'group' },
  { label: '未匹配', value: 'unmatched' },
]

const constructionOptions = [
  { label: '施工', value: 'all' },
  { label: '未施工', value: 'unconstructed' },
  { label: '施工中', value: 'in_progress' },
  { label: '已施工', value: 'completed' },
]

const archiveOptions = [
  { label: '归档', value: 'all' },
  { label: '未归档', value: 'unarchived' },
  { label: '已归档', value: 'archived' },
]

const classificationOptions = [
  { label: '分类', value: 'all' },
  { label: '完整', value: 'complete' },
  { label: '缺失', value: 'incomplete' },
]

const exceptionOptions = [
  { label: '异常', value: '' },
  { label: '有异常', value: 'open' },
  { label: '无异常', value: 'none' },
]

const installerSourceOptions: Array<{ label: string; value: DataCenterInstallerSource }> = [
  { label: '人员来源', value: 'all' },
  { label: '施工照片', value: 'photo' },
]

const sortOptions = [
  { label: '最近更新', value: 'updated_desc' },
  { label: '最早更新', value: 'updated_asc' },
  { label: '终端升序', value: 'terminal_asc' },
]

function update<K extends keyof DataCenterRouteQuery>(key: K, value: DataCenterRouteQuery[K]) {
  emit('update', { [key]: value } as Partial<DataCenterRouteQuery>)
}
</script>

<template>
  <div class="data-center-filters">
    <el-input
      :model-value="props.modelValue.keyword"
      clearable
      placeholder="表号、模块、采集器、地址"
      :prefix-icon="Search"
      @update:model-value="update('keyword', String($event || ''))"
      @keyup.enter="emit('update', { keyword: props.modelValue.keyword })"
    />
    <el-input
      :model-value="props.modelValue.terminal"
      clearable
      placeholder="终端"
      @update:model-value="update('terminal', String($event || ''))"
    />
    <el-select :model-value="props.modelValue.dataType" @update:model-value="update('dataType', $event as DataCenterDataType)">
      <el-option v-for="item in dataTypes" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-select :model-value="props.modelValue.constructionStatus" @update:model-value="update('constructionStatus', String($event || 'all'))">
      <el-option v-for="item in constructionOptions" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-select :model-value="props.modelValue.archiveStatus" @update:model-value="update('archiveStatus', String($event || 'all'))">
      <el-option v-for="item in archiveOptions" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-select :model-value="props.modelValue.classificationStatus" @update:model-value="update('classificationStatus', String($event || 'all'))">
      <el-option v-for="item in classificationOptions" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-select :model-value="props.modelValue.exceptionStatus" @update:model-value="update('exceptionStatus', String($event || ''))">
      <el-option v-for="item in exceptionOptions" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-input
      :model-value="props.modelValue.installer"
      clearable
      placeholder="安装人员"
      @update:model-value="update('installer', String($event || ''))"
    />
    <el-select :model-value="props.modelValue.installerSource" @update:model-value="update('installerSource', ($event || 'all') as DataCenterInstallerSource)">
      <el-option v-for="item in installerSourceOptions" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <el-date-picker
      :model-value="props.modelValue.dateFrom"
      type="date"
      value-format="YYYY-MM-DD"
      placeholder="起始"
      @update:model-value="update('dateFrom', String($event || ''))"
    />
    <el-date-picker
      :model-value="props.modelValue.dateTo"
      type="date"
      value-format="YYYY-MM-DD"
      placeholder="截止"
      @update:model-value="update('dateTo', String($event || ''))"
    />
    <el-select :model-value="props.modelValue.sort" @update:model-value="update('sort', String($event || 'updated_desc'))">
      <el-option v-for="item in sortOptions" :key="item.value" :label="item.label" :value="item.value" />
    </el-select>
    <div class="data-center-filter-actions">
      <el-button :icon="Camera" @click="emit('scan')">扫码</el-button>
      <el-button :icon="Refresh" :loading="props.loading" @click="emit('reset')">重置</el-button>
    </div>
  </div>
</template>

<style scoped>
.data-center-filters {
  display: grid;
  grid-template-columns: minmax(220px, 1.3fr) repeat(5, minmax(104px, 0.7fr)) minmax(120px, 0.7fr) repeat(3, minmax(116px, 0.7fr)) auto;
  gap: 8px;
  align-items: center;
}

.data-center-filter-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 1180px) {
  .data-center-filters {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .data-center-filter-actions {
    grid-column: 1 / -1;
  }
}

@media (max-width: 760px) {
  .data-center-filters {
    grid-template-columns: 1fr;
  }
}
</style>
