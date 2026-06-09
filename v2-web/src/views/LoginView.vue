<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const form = reactive({
  username: 'reviewer',
  password: '123456',
})

async function submit() {
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    await router.push(String(route.query.redirect || '/dashboard'))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-title">
        <strong>模块更换项目管理器 V2.0</strong>
        <span>资料审阅协同工作台</span>
      </div>

      <ElForm label-position="top" @submit.prevent="submit">
        <ElFormItem label="账号">
          <ElInput v-model="form.username" :prefix-icon="User" autocomplete="username" />
        </ElFormItem>
        <ElFormItem label="密码">
          <ElInput v-model="form.password" :prefix-icon="Lock" autocomplete="current-password" show-password />
        </ElFormItem>
        <ElButton type="primary" native-type="submit" :loading="loading" class="login-button">
          登录
        </ElButton>
      </ElForm>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
  background: #eef2f7;
}

.login-panel {
  width: min(420px, calc(100vw - 32px));
  padding: 28px;
  border: 1px solid #dfe5ef;
  border-radius: 8px;
  background: #ffffff;
}

.login-title {
  margin-bottom: 24px;
}

.login-title strong,
.login-title span {
  display: block;
}

.login-title strong {
  font-size: 22px;
}

.login-title span {
  margin-top: 6px;
  color: #667085;
}

.login-button {
  width: 100%;
}
</style>
