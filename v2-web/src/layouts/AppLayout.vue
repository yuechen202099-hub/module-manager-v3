<script setup lang="ts">
import { DataBoard, Files, FolderOpened, List, SwitchButton, Tickets } from '@element-plus/icons-vue'
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()

const pageTitle = computed(() => String(route.meta.title || '模块更换项目管理器 V2.0'))

onMounted(() => {
  if (!workspace.projects.length) {
    void workspace.bootstrap()
  }
})

function logout() {
  auth.logout()
  void router.push({ name: 'login' })
}
</script>

<template>
  <ElContainer class="app-shell">
    <ElAside class="app-sidebar" width="232px">
      <div class="brand">
        <div class="brand-mark">V2</div>
        <div>
          <strong>模块更换</strong>
          <span>项目管理器</span>
        </div>
      </div>

      <ElMenu :default-active="route.path" router class="side-menu">
        <ElMenuItem index="/dashboard">
          <ElIcon><DataBoard /></ElIcon>
          <span>项目看板</span>
        </ElMenuItem>
        <ElMenuItem index="/projects">
          <ElIcon><FolderOpened /></ElIcon>
          <span>项目管理</span>
        </ElMenuItem>
        <ElMenuItem index="/checklists">
          <ElIcon><Files /></ElIcon>
          <span>清单管理</span>
        </ElMenuItem>
        <ElMenuItem index="/tasks">
          <ElIcon><Tickets /></ElIcon>
          <span>任务大厅</span>
        </ElMenuItem>
        <ElMenuItem index="/review/g-001">
          <ElIcon><List /></ElIcon>
          <span>资料审阅</span>
        </ElMenuItem>
      </ElMenu>
    </ElAside>

    <ElContainer>
      <ElHeader class="app-header">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ workspace.activeProject?.name || '等待项目数据' }}</p>
        </div>
        <div class="header-actions">
          <ElTag type="primary" effect="plain">{{ auth.user?.role === 'admin' ? '管理员' : '审阅员' }}</ElTag>
          <span>{{ auth.displayName }}</span>
          <ElTooltip content="退出登录" placement="bottom">
            <ElButton :icon="SwitchButton" circle @click="logout" />
          </ElTooltip>
        </div>
      </ElHeader>

      <ElMain class="app-main">
        <RouterView />
      </ElMain>
    </ElContainer>
  </ElContainer>
</template>
