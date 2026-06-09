<template>
  <el-container class="app-shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">V2</div>
        <div>
          <div class="brand-title">模块更换项目管理器</div>
          <div class="brand-subtitle">多人审阅版</div>
        </div>
      </div>
      <el-menu router :default-active="$route.path" class="nav-menu">
        <el-menu-item index="/dashboard">项目看板</el-menu-item>
        <el-menu-item index="/catalog">清单管理</el-menu-item>
        <el-menu-item index="/tasks">任务大厅</el-menu-item>
        <el-menu-item index="/review">资料审阅</el-menu-item>
        <el-menu-item index="/exceptions">异常处理</el-menu-item>
        <el-menu-item index="/exports">完整数据</el-menu-item>
        <el-menu-item index="/settings">系统设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div>
          <strong>V2.0 云端协作</strong>
          <span class="muted">4 人同步审阅，进度实时保存</span>
        </div>
        <el-button type="primary" plain>发布任务</el-button>
      </el-header>
      <el-main class="main-panel">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

