<script setup lang="ts">
import { Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const rows = [
  {
    type: '总清单',
    source: '资料信息.xlsx',
    purpose: '安装地址、原始表号、短表号匹配',
    rule: '短表号匹配键移除前 2 位',
    status: '已导入',
  },
  {
    type: '阶段清单',
    source: '模块领用清单_模拟.xlsx',
    purpose: '阶段、终端、任务切片',
    rule: '仅用于任务划分，不覆盖总清单地址',
    status: '待复核',
  },
  {
    type: '扫码照片',
    source: '批量扫码_*.xlsx',
    purpose: '照片与资料组匹配',
    rule: '长条码匹配键移除前 11 位和最后 1 位',
    status: '待导入',
  },
]
</script>

<template>
  <div class="page-stack">
    <div class="toolbar">
      <div>
        <h2>清单管理</h2>
      </div>
      <ElButton type="primary" :icon="Upload" @click="ElMessage.info('导入任务接口待接入')">上传清单</ElButton>
    </div>

    <section class="panel">
      <div class="panel-body">
        <ElTable :data="rows" stripe>
          <ElTableColumn prop="type" label="类型" width="120" />
          <ElTableColumn prop="source" label="来源文件" min-width="190" />
          <ElTableColumn prop="purpose" label="用途" min-width="220" />
          <ElTableColumn prop="rule" label="关键规则" min-width="260" />
          <ElTableColumn prop="status" label="状态" width="120">
            <template #default="{ row }">
              <ElTag :type="row.status === '已导入' ? 'success' : row.status === '待复核' ? 'warning' : 'info'">
                {{ row.status }}
              </ElTag>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
    </section>
  </div>
</template>
