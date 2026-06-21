<script setup lang="ts">
const importChecks = [
  '供应商后台不提供稳定 API，后台同步主流程已停用。',
  '正式数据进入系统统一改为表格导入，由项目看板承载导入入口。',
  '总清单仍是安装地址唯一来源，扫码表格只补充扫码、采集器、模块和照片 URL。',
]

const importSteps = [
  {
    title: '导出表格',
    detail: '从供应商系统导出扫码表格，保留表号、采集器、模块、照片 URL 和安装人员。',
  },
  {
    title: '项目看板导入',
    detail: '在项目看板上传总清单和扫码表格，系统按表号、终端和照片指纹匹配资料组。',
  },
  {
    title: '领取并分类',
    detail: '任务按终端领取，审阅员在审阅工作台用快捷键完成照片分类和归档。',
  },
]
</script>

<template>
  <section class="native-sync-page">
    <div class="panel sync-hero">
      <p class="eyebrow">导入配置</p>
      <h2>后台同步已停用</h2>
      <p class="muted">
        该页面只保留历史说明。V2.3.1 静态基准已取消后台爬取同步，正式流程统一走项目看板的总清单和扫码表格导入。
      </p>
    </div>

    <div class="panel sync-rules">
      <h3>当前规则</h3>
      <ul>
        <li v-for="item in importChecks" :key="item">{{ item }}</li>
      </ul>
    </div>

    <div class="panel sync-rules">
      <h3>表格导入流程</h3>
      <div class="sync-steps">
        <article v-for="(step, index) in importSteps" :key="step.title" class="sync-step">
          <b>{{ index + 1 }}</b>
          <strong>{{ step.title }}</strong>
          <span>{{ step.detail }}</span>
        </article>
      </div>
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
