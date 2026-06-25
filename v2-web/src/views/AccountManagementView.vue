<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { deleteUserAccount, fetchUserAccounts, saveUserAccount } from '@/api/services'
import type { UserAccount, UserLoginHistoryItem, UserRole } from '@/api/types'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const accountUsers = ref<UserAccount[]>([])
const loadingAccounts = ref(false)
const savingAccount = ref(false)
const historyVisible = ref(false)
const historyTarget = ref<UserAccount | null>(null)

const accountForm = reactive({
  username: '',
  name: '',
  password: '',
  teamId: auth.user?.teamId || 'default-team',
  role: 'reviewer' as UserRole,
  status: 'active',
  editing: false,
})

const accountRoles: Array<{ value: UserRole; label: string }> = [
  { value: 'admin', label: '管理员' },
  { value: 'reviewer', label: '审阅员' },
  { value: 'constructor', label: '施工员' },
]

const accountStatuses = [
  { value: 'active', label: '启用' },
  { value: 'disabled', label: '停用' },
]

const accountStats = computed(() => {
  const active = accountUsers.value.filter((user) => user.status !== 'disabled').length
  const ipWarnings = accountUsers.value.filter((user) => hasIpWarning(user)).length
  const loginRows = accountUsers.value.reduce((sum, user) => sum + (user.loginHistory?.length || 0), 0)
  return { total: accountUsers.value.length, active, ipWarnings, loginRows }
})

const historyRows = computed(() => historyTarget.value?.loginHistory || [])
const historyTitle = computed(() => {
  const user = historyTarget.value
  if (!user) return '登录记录'
  return `${user.name || user.username} 最近登录记录`
})

function roleLabel(role: string) {
  return accountRoles.find((item) => item.value === role)?.label || role
}

function rolesLabel(user: UserAccount) {
  return (user.roles || []).map((role) => roleLabel(role)).join(' / ') || '审阅员'
}

function primaryRole(user: UserAccount): UserRole {
  const role = user.roles.find((item) => accountRoles.some((option) => option.value === item))
  return role || 'reviewer'
}

function formatDateTime(value = '') {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function shortDevice(value = '') {
  const trimmed = value.trim()
  if (!trimmed) return '-'
  return trimmed.length > 44 ? `${trimmed.slice(0, 44)}...` : trimmed
}

function commonUserLabel(item: UserLoginHistoryItem | undefined) {
  if (!item?.ipCommonUser) return '样本不足'
  const name = item.ipCommonUserName || item.ipCommonUser
  const count = Number(item.ipCommonUserCount || 0)
  return count ? `${name} ${count}/${item.ipLoginCount || count}` : name
}

function latestHistory(user: UserAccount) {
  return user.loginHistory?.[0]
}

function hasIpWarning(user: UserAccount) {
  const latest = latestHistory(user)
  return Boolean(latest?.ipCommonUser && latest.ipCommonUser !== user.username)
}

function ipRiskTone(user: UserAccount) {
  if (hasIpWarning(user)) return 'warning'
  return latestHistory(user)?.ipCommonUser ? 'success' : 'info'
}

function ipRiskText(user: UserAccount) {
  const latest = latestHistory(user)
  if (!latest?.ip) return '无记录'
  if (hasIpWarning(user)) return `常用人：${commonUserLabel(latest)}`
  return '本人常用'
}

function resetAccountForm() {
  accountForm.username = ''
  accountForm.name = ''
  accountForm.password = ''
  accountForm.teamId = auth.user?.teamId || 'default-team'
  accountForm.role = 'reviewer'
  accountForm.status = 'active'
  accountForm.editing = false
}

async function loadAccounts() {
  if (loadingAccounts.value) return
  loadingAccounts.value = true
  try {
    accountUsers.value = await fetchUserAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号列表加载失败')
  } finally {
    loadingAccounts.value = false
  }
}

function editAccount(user: UserAccount) {
  accountForm.username = user.username
  accountForm.name = user.name || user.username
  accountForm.password = ''
  accountForm.teamId = user.teamId || auth.user?.teamId || 'default-team'
  accountForm.role = primaryRole(user)
  accountForm.status = user.status || 'active'
  accountForm.editing = true
}

async function submitAccount() {
  const username = accountForm.username.trim()
  if (!username) {
    ElMessage.warning('请填写账号')
    return
  }
  if (!accountForm.name.trim()) {
    ElMessage.warning('请填写姓名，姓名将作为安装人员和 KPI 的统一口径')
    return
  }
  if (!accountForm.editing && !accountForm.password.trim()) {
    ElMessage.warning('新账号必须填写初始密码')
    return
  }
  savingAccount.value = true
  try {
    await saveUserAccount({
      username,
      password: accountForm.password.trim() || undefined,
      name: accountForm.name.trim(),
      roles: [accountForm.role],
      teamId: accountForm.teamId.trim() || auth.user?.teamId || 'default-team',
      status: accountForm.status,
    })
    ElMessage.success('账号已保存')
    resetAccountForm()
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号保存失败')
  } finally {
    savingAccount.value = false
  }
}

async function removeAccount(user: UserAccount) {
  if (user.username === auth.user?.username) {
    ElMessage.warning('不能删除当前登录账号')
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除账号 ${user.username}？删除后该账号将无法登录。`, '删除账号', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteUserAccount(user.username)
    ElMessage.success('账号已删除')
    await loadAccounts()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '账号删除失败')
  }
}

function openHistory(user: UserAccount) {
  historyTarget.value = user
  historyVisible.value = true
}

onMounted(() => {
  void loadAccounts()
})
</script>

<template>
  <section class="account-management-page">
    <div class="account-hero panel">
      <div>
        <p class="eyebrow">账号管理</p>
        <h2>账号、角色与登录审计</h2>
        <p class="muted">统一维护账号入口，记录最近 30 次登录，并按 IP 识别常用人员。</p>
      </div>
      <ElButton :icon="Refresh" :loading="loadingAccounts" @click="loadAccounts">刷新</ElButton>
    </div>

    <div class="account-metrics">
      <article class="metric">
        <span class="metric-label">账号总数</span>
        <strong class="metric-value">{{ accountStats.total }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">启用账号</span>
        <strong class="metric-value">{{ accountStats.active }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">IP 异常提示</span>
        <strong class="metric-value">{{ accountStats.ipWarnings }}</strong>
      </article>
      <article class="metric">
        <span class="metric-label">已记录登录</span>
        <strong class="metric-value">{{ accountStats.loginRows }}</strong>
      </article>
    </div>

    <section class="panel account-form-panel">
      <div class="panel-heading">
        <div>
          <h3>{{ accountForm.editing ? '编辑账号' : '新增账号' }}</h3>
          <p class="muted">姓名作为安装人员、施工统计与 KPI 的统一人员口径。</p>
        </div>
      </div>
      <div class="account-form-grid">
        <label class="account-field">
          <span>账号</span>
          <el-input v-model="accountForm.username" :disabled="accountForm.editing" placeholder="例如 reviewer-a" autocomplete="off" />
        </label>
        <label class="account-field">
          <span>姓名</span>
          <el-input v-model="accountForm.name" placeholder="人员姓名" autocomplete="off" />
        </label>
        <label class="account-field">
          <span>密码</span>
          <el-input v-model="accountForm.password" type="password" show-password placeholder="新账号必填，更新可留空" autocomplete="new-password" />
        </label>
        <label class="account-field">
          <span>团队</span>
          <el-input v-model="accountForm.teamId" placeholder="例如 default-team" autocomplete="off" />
        </label>
        <label class="account-field">
          <span>角色</span>
          <el-select v-model="accountForm.role" placeholder="选择角色">
            <el-option v-for="role in accountRoles" :key="role.value" :label="role.label" :value="role.value" />
          </el-select>
        </label>
        <label class="account-field">
          <span>状态</span>
          <el-select v-model="accountForm.status" placeholder="选择状态">
            <el-option v-for="status in accountStatuses" :key="status.value" :label="status.label" :value="status.value" />
          </el-select>
        </label>
        <div class="account-actions">
          <el-button type="primary" :loading="savingAccount" @click="submitAccount">保存账号</el-button>
          <el-button @click="resetAccountForm">清空</el-button>
        </div>
      </div>
    </section>

    <section class="panel account-list-panel">
      <div class="panel-heading">
        <div>
          <h3>账号清单</h3>
          <p class="muted">IP 常用人仅作风险提示，用于发现可能的代做工单。</p>
        </div>
      </div>
      <el-table v-loading="loadingAccounts" :data="accountUsers" height="520" size="small">
        <el-table-column prop="username" label="账号" min-width="130" />
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column prop="teamId" label="团队" min-width="130" />
        <el-table-column label="角色" min-width="130">
          <template #default="{ row }">{{ rolesLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <el-tag :type="row.status === 'disabled' ? 'danger' : 'success'" effect="plain">
              {{ row.status === 'disabled' ? '停用' : '启用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.lastLoginAt) }}</template>
        </el-table-column>
        <el-table-column prop="lastLoginIp" label="最近 IP" min-width="130" />
        <el-table-column label="IP 常用人" min-width="180">
          <template #default="{ row }">
            <el-tag :type="ipRiskTone(row)" effect="plain">{{ ipRiskText(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="登录设备" min-width="220">
          <template #default="{ row }">
            <el-tooltip :content="row.lastLoginDevice || '-'" placement="top" :disabled="!row.lastLoginDevice">
              <span class="device-cell">{{ shortDevice(row.lastLoginDevice) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openHistory(row)">记录</el-button>
            <el-button size="small" @click="editAccount(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="removeAccount(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <ElDialog v-model="historyVisible" :title="historyTitle" width="860px">
      <el-table :data="historyRows" height="420" size="small">
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">{{ formatDateTime(row.at) }}</template>
        </el-table-column>
        <el-table-column prop="ip" label="登录 IP" min-width="140" />
        <el-table-column label="该 IP 常用人" min-width="180">
          <template #default="{ row }">
            <el-tag :type="row.ipCommonUser && row.ipCommonUser !== historyTarget?.username ? 'warning' : 'success'" effect="plain">
              {{ commonUserLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备" min-width="300">
          <template #default="{ row }">
            <el-tooltip :content="row.device || '-'" placement="top" :disabled="!row.device">
              <span class="device-cell">{{ shortDevice(row.device) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>
    </ElDialog>
  </section>
</template>

<style scoped>
.account-management-page {
  display: grid;
  gap: 14px;
}

.account-hero,
.account-metrics,
.account-form-grid,
.account-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.account-hero {
  padding: 20px;
}

.account-hero h2 {
  margin: 4px 0 6px;
  color: var(--v2-text-strong);
  font-size: 28px;
  letter-spacing: 0;
}

.account-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.account-form-panel,
.account-list-panel {
  min-width: 0;
}

.account-form-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr)) auto;
  align-items: end;
  padding: 14px;
}

.account-field {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.account-field > span {
  color: var(--v2-text-muted);
  font-size: 12px;
  font-weight: 760;
}

.account-actions {
  justify-content: flex-end;
}

.device-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  color: var(--v2-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1280px) {
  .account-form-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .account-hero {
    align-items: flex-start;
    flex-direction: column;
  }

  .account-metrics,
  .account-form-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .account-actions {
    justify-content: stretch;
  }

  .account-actions :deep(.el-button) {
    flex: 1;
  }
}
</style>
