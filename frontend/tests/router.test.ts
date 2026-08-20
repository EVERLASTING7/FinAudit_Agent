import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppRouter } from '@/router'
import { useAuthStore } from '@/stores/auth'

const formalRoutes = [
  ['/login', 'login'],
  ['/dashboard', 'dashboard'],
  ['/files', 'files'],
  ['/files/file-1', 'file-detail'],
  ['/contracts', 'contracts'],
  ['/contracts/contract-1', 'contract-detail'],
  ['/contracts/contract-1/primary-invoices', 'contract-primary-invoices'],
  ['/invoices', 'invoices'],
  ['/invoices/invoice-1', 'invoice-detail'],
  [
    '/invoices/40000000-0000-4000-8000-000000000001/contract-links',
    'contract-invoice-links',
  ],
  ['/knowledge-bases', 'knowledge-bases'],
  ['/knowledge-bases/kb-1', 'knowledge-base-detail'],
  ['/qa', 'qa'],
  ['/audit-tasks', 'audit-tasks'],
  ['/audit-tasks/task-1', 'audit-task-detail'],
  ['/audit-reports/report-1', 'audit-report-detail'],
  ['/users', 'users'],
  ['/operation-logs', 'operation-logs'],
] as const

beforeEach(() => {
  sessionStorage.clear()
  setActivePinia(createPinia())
})

describe('正式路由', () => {
  it.each(formalRoutes)('解析 %s', (path, expectedName) => {
    const router = createAppRouter(createMemoryHistory())
    expect(router.resolve(path).name).toBe(expectedName)
  })

  it('拦截未登录的深层链接并保留站内返回地址', async () => {
    vi.spyOn(useAuthStore(), 'restoreSession').mockResolvedValue()
    const router = createAppRouter(createMemoryHistory())

    await router.push('/contracts/contract-1')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/contracts/contract-1')
  })

  it('首个受保护导航等待会话恢复完成', async () => {
    const auth = useAuthStore()
    let finishRestore: (() => void) | undefined
    vi.spyOn(auth, 'restoreSession').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishRestore = resolve
        }),
    )
    const router = createAppRouter(createMemoryHistory())

    const navigation = router.push('/files')
    await vi.waitFor(() => expect(finishRestore).toBeTypeOf('function'))
    expect(router.currentRoute.value.fullPath).not.toBe('/files')

    auth.setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000005',
        displayName: '文件查看用户',
        roles: ['read_only'],
        permissions: ['files.read'],
      },
      'test-access-token',
    )
    finishRestore?.()
    await navigation

    expect(router.currentRoute.value.fullPath).toBe('/files')
  })

  it('拒绝缺少页面权限的用户管理深层链接', async () => {
    const auth = useAuthStore()
    auth.setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000003',
        displayName: '审核员',
        roles: ['audit_reviewer'],
        permissions: ['audits.read'],
      },
      'test-access-token',
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/users')

    expect(router.currentRoute.value.name).toBe('forbidden')
  })

  it('系统管理员可进入获准的文件纠错详情但不能枚举文件列表', async () => {
    const auth = useAuthStore()
    auth.setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000007',
        displayName: '系统管理员',
        roles: ['system_admin'],
        permissions: ['system.configure'],
      },
      'test-access-token',
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/files/41000000-0000-4000-8000-000000000001')
    expect(router.currentRoute.value.name).toBe('file-detail')

    await router.push('/files')
    expect(router.currentRoute.value.name).toBe('forbidden')
  })

  it('已登录用户访问登录页时回到工作台', async () => {
    const auth = useAuthStore()
    auth.setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000004',
        displayName: '审核员',
        roles: ['audit_reviewer'],
        permissions: ['audits.read'],
      },
      'test-access-token',
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/login')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('无 invoiceId 的旧关联入口安全回到发票列表', async () => {
    const auth = useAuthStore()
    auth.setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000006',
        displayName: '财务只读用户',
        roles: ['read_only'],
        permissions: ['financial.read'],
      },
      'test-access-token',
    )
    const router = createAppRouter(createMemoryHistory())

    await router.push('/contract-invoice-links?invoiceId=invoice-i001')

    expect(router.currentRoute.value.name).toBe('invoices')
  })
})
