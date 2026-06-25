<template>
  <section>
    <div class="toolbar">
      <h1 class="page-title">清单管理</h1>
      <div>
        <el-button>导入总清单</el-button>
        <el-button>导入阶段清单</el-button>
      </div>
    </div>
    <div class="panel">
      <el-alert title="安装地址只允许来自总清单，阶段清单只用于阶段、终端和任务划分。" type="info" show-icon />
      <el-table :data="rows" style="margin-top: 12px" height="420">
        <el-table-column prop="meter" label="表号" />
        <el-table-column prop="address" label="安装地址" />
        <el-table-column prop="stage" label="阶段" width="120" />
        <el-table-column prop="status" label="匹配状态" width="120" />
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
const rows = [
  { meter: '350000434169', address: '聚丰园路188弄70号601室', stage: '一阶段', status: '已匹配' },
]
</script>

