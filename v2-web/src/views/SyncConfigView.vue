<template>
  <section class="native-sync-page">
    <div class="panel sync-hero">
      <p class="eyebrow">导入配置</p>
    </div>

    <div class="panel sync-actions">
      <el-button type="primary" @click="$router.push('/project-board')">去项目看板导入表格</el-button>
      <el-button @click="$router.push('/claim-tasks')">查看终端任务</el-button>
    </div>
  </section>
</template>

<style scoped>
.native-sync-page {
  display: grid;
  gap: 12px;
}

.sync-hero,
.sync-rules,
.sync-actions {
  padding: 18px;
}

.sync-rules ul {
  margin: 10px 0 0;
  padding-left: 20px;
  color: var(--v2-text-muted);
  line-height: 1.75;
}

.sync-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.sync-step {
  display: grid;
  align-content: start;
  gap: 8px;
  min-height: 118px;
  padding: 12px;
  border: 1px solid var(--v2-border-soft);
  border-radius: var(--v2-radius-md);
  background: var(--v2-bg-subtle);
}

.sync-step b {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border-radius: 8px;
  background: var(--v2-text-strong);
  color: #fff;
  font-size: 12px;
}

.sync-step strong {
  color: var(--v2-text-strong);
}

.sync-step span {
  color: var(--v2-text-muted);
  font-size: 12px;
  line-height: 1.55;
}

.sync-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

@media (max-width: 760px) {
  .sync-steps {
    grid-template-columns: 1fr;
  }
}
</style>
