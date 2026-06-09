<template>
  <section>
    <h1 class="page-title">异常处理</h1>
    <div class="panel">
      <el-table :data="rows" height="480">
        <el-table-column prop="meter" label="表号" />
        <el-table-column prop="type" label="异常类型" />
        <el-table-column prop="message" label="说明" />
        <el-table-column prop="status" label="状态" width="120" />
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
const rows = [{ meter: '350000434170', type: '缺照片', message: '少于 4 张照片', status: '待处理' }]
</script>

