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
          <span class="login-mark">V3.0.1</span>
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
  padding: clamp(18px, 4vw, 52px);
  overflow-x: hidden;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(245, 247, 251, 0.98) 58%, #edf4fb 100%),
    var(--v2-bg-app);
}

.login-card {
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(360px, 448px);
  width: min(1080px, 100%);
  overflow: hidden;
  border: 1px solid rgba(215, 223, 235, 0.86);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: 0 30px 80px rgba(16, 24, 40, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(24px) saturate(160%);
  -webkit-backdrop-filter: blur(24px) saturate(160%);
}

.login-intro {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 36px;
  min-height: 520px;
  padding: clamp(28px, 5vw, 56px);
  border-right: 1px solid rgba(230, 235, 242, 0.92);
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.86), rgba(244, 249, 255, 0.78)),
    #ffffff;
}

.login-intro > div {
  display: grid;
  max-width: 560px;
  gap: 12px;
}

.login-panel {
  display: grid;
  align-content: center;
  padding: clamp(26px, 4vw, 44px);
  background: rgba(255, 255, 255, 0.9);
}

.login-mark {
  width: fit-content;
  min-width: 118px;
  height: 34px;
  display: inline-grid;
  place-items: center;
  padding: 0 12px;
  border-radius: 999px;
  color: #fff;
  background: linear-gradient(135deg, #101828, #1d2939);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 12px 28px rgba(16, 24, 40, 0.16);
  font-family: var(--v2-font-mono);
  font-weight: 820;
  font-size: 11px;
}

.login-intro strong,
.login-intro p,
.login-title h1,
.login-title span {
  display: block;
  margin: 0;
}

.login-intro strong {
  color: var(--v2-text-strong);
  font-size: clamp(30px, 4vw, 48px);
  font-weight: 860;
  letter-spacing: 0;
  line-height: 1.08;
}

.login-intro p,
.login-title span {
  margin-top: 4px;
  color: var(--v2-text-muted);
  font-size: 14px;
  line-height: 1.7;
}

.login-proof {
  display: grid;
  gap: 10px;
  margin: 0;
}

.login-proof div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 12px;
  padding: 14px 0;
  border-top: 1px solid rgba(215, 223, 235, 0.82);
}

.login-proof dt,
.login-proof dd {
  min-width: 0;
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
}

.login-proof dt {
  color: var(--v2-text-muted);
  font-weight: 800;
}

.login-proof dd {
  overflow: hidden;
  color: var(--v2-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.login-title {
  margin-bottom: 24px;
}

.login-title h1 {
  color: var(--v2-text-strong);
  font-size: 28px;
  font-weight: 850;
  line-height: 1.2;
}

.login-button {
  width: 100%;
  min-height: 42px;
  margin-top: 6px;
}

.login-presets {
  display: grid;
  gap: 10px;
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid rgba(215, 223, 235, 0.82);
}

.preset-heading,
.preset-empty,
.preset-account {
  border: 1px solid rgba(215, 223, 235, 0.86);
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.86);
}

.preset-heading {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
}

.preset-heading strong,
.preset-empty strong,
.preset-account strong {
  min-width: 0;
  overflow: hidden;
  color: var(--v2-text-strong);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-heading span,
.preset-empty span,
.preset-account span,
.preset-account em {
  min-width: 0;
  overflow: hidden;
  color: var(--v2-text-muted);
  font-size: 12px;
  font-style: normal;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  min-height: 46px;
  padding: 11px 13px;
  color: var(--v2-text);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--v2-transition-fast), background var(--v2-transition-fast), box-shadow var(--v2-transition-fast), transform var(--v2-transition-fast);
}

.preset-account:hover {
  border-color: var(--v2-primary-border);
  background: #fff;
  box-shadow: var(--v2-shadow-raised);
}

.preset-account:active {
  transform: translateY(1px);
}

.preset-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 13px;
}

@media (max-width: 760px) {
  .login-page {
    place-items: start center;
    padding: 14px;
  }

  .login-card {
    grid-template-columns: 1fr;
    border-radius: 14px;
  }

  .login-intro {
    min-height: auto;
    gap: 24px;
    border-right: 0;
    border-bottom: 1px solid rgba(230, 235, 242, 0.92);
  }

  .login-intro strong {
    font-size: 28px;
  }

  .login-proof div {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .login-proof dd {
    white-space: normal;
  }

  .preset-account {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}
</style>
