import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter } from '@/router'
import { ApiError } from '@/services/api'
import { authApi, type AuthSession } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'

const session: AuthSession = {
  accessToken: 'access-token',
  tokenType: 'Bearer',
  expiresIn: 900,
  user: {
    id: '90000000-0000-4000-8000-000000000020',
    displayName: '财务审核员',
    roles: ['finance_reviewer'],
    permissions: ['files.read'],
  },
}

let wrapper: VueWrapper | undefined

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  document.body.innerHTML = ''
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
})

async function mountLogin(path = '/login'): Promise<{
  auth: ReturnType<typeof useAuthStore>
  router: ReturnType<typeof createAppRouter>
}> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore(pinia)
  vi.spyOn(auth, 'restoreSession').mockResolvedValue()
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  wrapper = mount(LoginView, {
    attachTo: document.body,
    global: { plugins: [pinia, router] },
  })
  return { auth, router }
}

describe('真实登录页面', () => {
  it('原样提交冻结 Login DTO，并在成功后进入受权限保护的返回页', async () => {
    vi.spyOn(authApi, 'login').mockResolvedValue(session)
    const { auth, router } = await mountLogin('/login?redirect=/files')

    await wrapper?.get('#username').setValue(' reviewer ')
    await wrapper?.get('#password').setValue('secret')
    await wrapper?.get('#remember-me').setValue(true)
    await wrapper?.get('form').trigger('submit')
    await flushPromises()

    expect(authApi.login).toHaveBeenCalledWith({
      username: ' reviewer ',
      password: 'secret',
      rememberMe: true,
    })
    expect(auth.user).toEqual(session.user)
    expect(auth.accessToken).toBe(session.accessToken)
    await vi.waitFor(() => expect(router.currentRoute.value.fullPath).toBe('/files'), {
      timeout: 3_000,
    })
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
  })

  it('强制换密 Token 仅停留在组件内存，204 后回到登录表单', async () => {
    const passwordChangeToken = 'component-only-password-change-token'
    vi.spyOn(authApi, 'login').mockRejectedValue(
      new ApiError({
        code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
        message: '首次登录必须修改密码。',
        status: 403,
        traceId: '90000000-0000-4000-8000-000000000021',
        data: { passwordChangeToken, expiresIn: 300 },
      }),
    )
    vi.spyOn(authApi, 'changePassword').mockResolvedValue()
    await mountLogin()

    await wrapper?.get('#username').setValue('reviewer')
    await wrapper?.get('#password').setValue('initial-secret')
    await wrapper?.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper?.get('#login-title').text()).toBe('修改初始密码')
    expect(wrapper?.get('#new-password').attributes('minlength')).toBe('6')
    expect(wrapper?.get('#confirm-password').attributes('minlength')).toBe('6')
    expect(wrapper?.text()).toContain('密码至少 6 个字符')
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)

    await wrapper?.get('#new-password').setValue('new-secret')
    await wrapper?.get('#confirm-password').setValue('new-secret')
    await wrapper?.get('form').trigger('submit')
    await flushPromises()

    expect(authApi.changePassword).toHaveBeenCalledWith(passwordChangeToken, 'new-secret')
    expect(wrapper?.get('#login-title').text()).toBe('登录')
    expect(wrapper?.get('[role="status"]').text()).toContain('请使用新密码重新登录')
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
  })

  it('服务器退出失败时明确展示本地退出与远端未确认状态，并允许重试', async () => {
    vi.spyOn(authApi, 'logout')
      .mockRejectedValueOnce(new Error('synthetic logout failure'))
      .mockResolvedValueOnce()
    const { auth } = await mountLogin()

    await expect(auth.signOut()).resolves.toBe(false)
    await flushPromises()

    expect(auth.remoteLogoutUnconfirmed).toBe(true)
    expect(wrapper?.get('[role="alert"]').text()).toContain('服务器端会话撤销尚未确认')
    expect(wrapper?.get('[role="alert"]').text()).toContain('Refresh 会话可能仍有效')

    await wrapper?.get('button[type="button"]').trigger('click')
    await flushPromises()

    expect(authApi.logout).toHaveBeenCalledTimes(2)
    expect(auth.remoteLogoutUnconfirmed).toBe(false)
    expect(wrapper?.find('[role="alert"]').exists()).toBe(false)
  })
})
