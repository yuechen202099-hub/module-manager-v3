<template>
  <div class="legacy-layout-shell">
    <header class="legacy-layout-header">
      <div>
        <strong>模块更换项目管理器</strong>
        <span>V3.0.25</span>
      </div>
      <el-tag type="info" effect="plain">兼容布局</el-tag>
    </header>
    <main class="legacy-layout-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.legacy-layout-shell {
  min-height: 100vh;
  background: var(--color-bg, #f4f7fb);
  color: var(--color-text, #111827);
}

.legacy-layout-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background: var(--color-surface, #ffffff);
  border-bottom: 1px solid var(--color-border, #d8e0ea);
}

.legacy-layout-header div {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.legacy-layout-header span {
  color: var(--color-text-muted, #667085);
  font-size: 12px;
}

.legacy-layout-main {
  padding: 16px;
}
</style>
