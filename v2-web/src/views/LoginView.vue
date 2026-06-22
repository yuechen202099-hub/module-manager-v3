<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchAuthConfig } from '@/api/services'
import type { AuthDemoAccount } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(false)
const configLoading = ref(false)
const demoAccounts = ref<AuthDemoAccount[]>([])
const accountConfigEnabled = ref(false)
const form = reactive({
  username: '',
  teamId: localStorage.getItem('module_manager_team_id') || 'default-team',
  password: '',
})

const configMessage = computed(() => {
  if (configLoading.value) return '正在读取登录配置'
  if (demoAccounts.value.length) return '可使用本地演示账号快速进入'
  return accountConfigEnabled.value ? '请输入管理员创建的正式账号' : '正式登录：请输入管理员分配的账号'
})

function fillAccount(account: AuthDemoAccount) {
  form.username = account.username
  form.teamId = account.team_id || localStorage.getItem('module_manager_team_id') || 'demo-team'
  form.password = account.password || ''
}

async function loadConfig() {
  configLoading.value = true
  try {
    const config = await fetchAuthConfig()
    demoAccounts.value = config.demo_auth_enabled ? config.demo_accounts : []
    accountConfigEnabled.value = Boolean(config.account_config_enabled)
    if (!form.username && demoAccounts.value[0]) {
      fillAccount(demoAccounts.value[0])
    }
  } catch {
    demoAccounts.value = []
    accountConfigEnabled.value = false
  } finally {
    configLoading.value = false
  }
}

async function submit() {
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password, form.teamId.trim() || 'default-team')
    const fallback = auth.user?.role === 'constructor' ? '/construction' : '/project-board'
    await router.push(String(route.query.redirect || fallback))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadConfig()
})
</script>

<template>
  <main class="login-page">
    <section class="login-card">
      <div class="login-intro">
        <span class="login-mark">V2.5.6</span>
        <div>
          <strong>模块更换项目管理器</strong>
          <p>工程审阅、施工采集、异常闭环</p>
        </div>
        <dl class="login-proof">
          <div>
            <dt>角色</dt>
            <dd>管理员 / 审阅员 / 施工员</dd>
          </div>
          <div>
            <dt>数据</dt>
            <dd>总清单、扫码表格、照片索引</dd>
          </div>
          <div>
            <dt>流程</dt>
            <dd>领取、采集、审阅、导出</dd>
          </div>
        </dl>
      </div>

      <div class="login-panel">
        <div class="login-title">
          <h1>登录工作台</h1>
          <span>使用管理员、审阅员或施工员账号进入对应页面。</span>
        </div>

        <ElForm label-position="top" @submit.prevent="submit">
          <ElFormItem label="账号">
            <ElInput v-model="form.username" :prefix-icon="User" autocomplete="username" placeholder="请输入账号" />
          </ElFormItem>
          <ElFormItem label="团队标识">
            <ElInput v-model="form.teamId" autocomplete="organization" placeholder="例如 default-team" />
          </ElFormItem>
          <ElFormItem label="密码">
            <ElInput
              v-model="form.password"
              :prefix-icon="Lock"
              autocomplete="current-password"
              placeholder="请输入密码"
              show-password
              @keydown.enter.prevent="submit"
            />
          </ElFormItem>
          <ElButton type="primary" native-type="submit" :loading="loading" class="login-button">
            登录
          </ElButton>
        </ElForm>

        <section class="login-presets" aria-label="登录配置">
          <div class="preset-heading">
            <strong>登录配置</strong>
            <span>{{ configMessage }}</span>
          </div>
          <div v-if="demoAccounts.length" class="preset-list">
            <button
              v-for="account in demoAccounts"
              :key="account.username"
              class="preset-account"
              type="button"
              @click="fillAccount(account)"
            >
              <span>{{ account.label || account.role }}</span>
              <strong>{{ account.username }}</strong>
              <em>{{ account.team_id || 'demo-team' }}</em>
            </button>
          </div>
          <div v-else class="preset-empty">
            <strong>正式登录</strong>
            <span>演示账号未开放</span>
          </div>
        </section>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: linear-gradient(180deg, #ffffff 0, #f3f6f9 100%);
}

.login-card {
  display: grid;
  grid-template-columns: minmax(320px, 0.92fr) minmax(360px, 440px);
  width: min(920px, calc(100vw - 32px));
  border: 1px solid var(--v2-border-soft);
  border-radius: var(--v2-radius-panel);
  background: #fff;
  box-shadow: var(--v2-shadow-panel);
  overflow: hidden;
}

.login-intro {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 26px;
  min-height: 420px;
  padding: 30px;
  border-right: 1px solid var(--v2-border-soft);
  background:
    linear-gradient(180deg, var(--v2-bg-subtle), #fff),
    #fff;
}

.login-intro > div {
  display: grid;
  gap: 6px;
}

.login-panel {
  padding: 30px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 26px;
}

.login-mark {
  width: 46px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  color: #fff;
  background: var(--v2-primary);
  font-weight: 800;
  font-size: 13px;
}

.login-brand strong,
.login-brand p,
.login-intro strong,
.login-intro p,
.login-title h1,
.login-title span {
  display: block;
  margin: 0;
}

.login-brand strong,
.login-intro strong {
  color: var(--v2-text-strong);
  font-size: 22px;
  line-height: 1.2;
}

.login-brand p,
.login-intro p,
.login-title span {
  margin-top: 4px;
  color: var(--v2-text-muted);
  font-size: 13px;
}

.login-proof {
  display: grid;
  gap: 10px;
  margin: 0;
}

.login-proof div {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr);
  gap: 10px;
  padding: 10px 0;
  border-top: 1px solid var(--v2-border-soft);
}

.login-proof dt,
.login-proof dd {
  margin: 0;
  font-size: 13px;
}

.login-proof dt {
  color: var(--v2-text-muted);
  font-weight: 760;
}

.login-proof dd {
  color: var(--v2-text);
}

.login-title {
  margin-bottom: 22px;
}

.login-title h1 {
  font-size: 24px;
  line-height: 1.25;
}

.login-button {
  width: 100%;
  margin-top: 4px;
}

.login-presets {
  display: grid;
  gap: 10px;
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--v2-border-soft);
}

.preset-heading,
.preset-empty,
.preset-account {
  border: 1px solid var(--v2-border-soft);
  border-radius: 10px;
  background: var(--v2-bg-subtle);
}

.preset-heading {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
}

.preset-heading strong,
.preset-empty strong,
.preset-account strong {
  color: var(--v2-text-strong);
}

.preset-heading span,
.preset-empty span,
.preset-account span,
.preset-account em {
  color: var(--v2-text-muted);
  font-size: 12px;
  font-style: normal;
}

.preset-list {
  display: grid;
  gap: 8px;
}

.preset-account {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 10px 12px;
  text-align: left;
  cursor: pointer;
}

.preset-account:hover {
  border-color: var(--v2-primary);
  background: #fff;
}

.preset-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
}

@media (max-width: 760px) {
  .login-card {
    grid-template-columns: 1fr;
  }

  .login-intro {
    min-height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--v2-border-soft);
  }

  .preset-account {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}
</style>
