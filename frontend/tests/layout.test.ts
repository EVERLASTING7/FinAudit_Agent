import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import App from '@/App.vue'
import { createAppRouter } from '@/router'
import { dashboardApi } from '@/services/dashboard'
import { fileApi } from '@/services/files'
import { useAuthStore } from '@/stores/auth'

let wrapper: VueWrapper | undefined

beforeEach(() => {
  sessionStorage.clear()
  document.body.innerHTML = ''
  vi.spyOn(dashboardApi, 'get').mockRejectedValue(new Error('layout test blocks API requests'))
  vi.spyOn(fileApi, 'list').mockRejectedValue(new Error('layout test blocks API requests'))
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

async function mountAuthenticatedLayout(path = '/dashboard'): Promise<{
  auth: ReturnType<typeof useAuthStore>
  layout: VueWrapper
  router: ReturnType<typeof createAppRouter>
}> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore(pinia)
  auth.setAuthenticatedSession(
    {
      id: '90000000-0000-4000-8000-000000000002',
      displayName: '测试审核员',
      roles: ['finance_reviewer'],
      permissions: ['files.read'],
    },
    'test-access-token',
  )

  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()

  wrapper = mount(App, {
    attachTo: document.body,
    global: { plugins: [pinia, router] },
  })

  return { auth, layout: wrapper, router }
}

describe('应用布局可访问性', () => {
  it('将跳到主内容链接作为首个可聚焦交互', async () => {
    const { layout } = await mountAuthenticatedLayout()
    const focusable = layout.findAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    const skipLink = layout.get<HTMLAnchorElement>('a.skip-link')

    expect(focusable[0]?.element).toBe(skipLink.element)
    expect(skipLink.attributes('href')).toBe('#main-content')
    expect(skipLink.text()).toBe('跳到主内容')

    skipLink.element.focus()
    expect(document.activeElement).toBe(skipLink.element)
  })

  it('保留唯一主内容目标及现有导航、退出和路由内容结构', async () => {
    const { layout } = await mountAuthenticatedLayout()
    const mainTargets = layout.findAll('#main-content')

    expect(mainTargets).toHaveLength(1)
    expect(mainTargets[0]?.element.tagName).toBe('MAIN')
    expect(mainTargets[0]?.attributes('tabindex')).toBe('-1')
    expect(
      layout
        .get('nav[aria-label="主导航"]')
        .findAll('a')
        .map((link) => link.text()),
    ).toEqual(['工作台', '文件管理'])
    expect(layout.get('button[type="button"]').text()).toBe('退出登录')
    expect(mainTargets[0]?.get('nav[aria-label="面包屑"]').element.tagName).toBe('NAV')
    expect(mainTargets[0]?.get('.page h1').text()).toBe('工作台')
  })

  it('会话失效后返回登录页并保留当前站内路径', async () => {
    const { auth, router } = await mountAuthenticatedLayout('/files')

    auth.clearSession()

    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('login'))
    expect(router.currentRoute.value.query.redirect).toBe('/files')
  })
})
