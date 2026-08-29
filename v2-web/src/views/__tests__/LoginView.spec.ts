import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LoginView from '@/views/LoginView.vue'

const serviceMocks = vi.hoisted(() => ({
  fetchAuthConfig: vi.fn(),
}))
const authMock = vi.hoisted(() => ({
  login: vi.fn(),
  user: null,
}))

vi.mock('@/api/services', () => serviceMocks)
vi.mock('@/stores/auth', () => ({ useAuthStore: () => authMock }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn() }),
}))

describe('login view', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    serviceMocks.fetchAuthConfig.mockResolvedValue({
      account_config_enabled: true,
      demo_auth_enabled: false,
      demo_accounts: [],
    })
  })

  it('presents only the current administrator and constructor roles', async () => {
    const wrapper = mount(LoginView, {
      global: {
        stubs: {
          ElButton: true,
          ElForm: true,
          ElFormItem: true,
          ElInput: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('管理员 / 施工员')
    expect(wrapper.text()).toContain('采集、审阅、翻拍、导出')
    expect(wrapper.text()).toContain('使用管理员或施工员账号进入对应页面。')
    expect(wrapper.text()).not.toContain('审阅员')
    expect(wrapper.text()).not.toContain('领取、采集')

    wrapper.unmount()
  })
})
