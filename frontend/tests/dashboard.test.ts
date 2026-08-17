import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/services/api'
import { DashboardApi, dashboardApi, decodeDashboard } from '@/services/dashboard'
import { useAuthStore } from '@/stores/auth'
import DashboardView from '@/views/DashboardView.vue'

const taskId = '71000000-0000-4000-8000-000000000001'
const executionId = '72000000-0000-4000-8000-000000000001'
const fileId = '73000000-0000-4000-8000-000000000001'
const jobId = '74000000-0000-4000-8000-000000000001'
const userId = '75000000-0000-4000-8000-000000000001'
const traceId = '76000000-0000-4000-8000-000000000001'

const rawDashboard = {
  item_limit: 5,
  audit_tasks: {
    open_count: 1,
    pending_review_count: 1,
    items: [{
      id: taskId,
      task_no: 'AUDIT-001',
      name: '月度财务审核',
      status: 'open',
      current_execution_id: executionId,
      updated_at: '2026-08-15T08:00:00Z',
    }],
  },
  files: {
    active_processing_count: 0,
    failed_processing_count: 0,
    items: [{
      file_id: fileId,
      original_name: 'invoice.docx',
      status: 'stored',
      security_scan_status: 'clean',
      intended_business_type: 'invoice',
      job_id: jobId,
      job_status: 'succeeded',
      created_at: '2026-08-15T07:00:00Z',
    }],
  },
  failed_jobs: null,
}
const financeDashboard = decodeDashboard(rawDashboard)

let wrapper: VueWrapper | undefined

function piniaFor(permissions: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).setAuthenticatedSession(
    { id: userId, displayName: '财务复核人', roles: ['finance_reviewer'], permissions: permissions as never[] },
    'test-token',
  )
  return pinia
}

async function routerForDashboard() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/dashboard', name: 'dashboard', component: DashboardView },
    { path: '/knowledge-bases', name: 'knowledge-bases', component: { template: '<div />' } },
    { path: '/qa', name: 'qa', component: { template: '<div />' } },
    { path: '/audit-tasks/:taskId', name: 'audit-task-detail', component: { template: '<div />' } },
    { path: '/files/:fileId', name: 'file-detail', component: { template: '<div />' } },
  ] })
  await router.push('/dashboard')
  await router.isReady()
  return router
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('DashboardApi', () => {
  it('严格解码有界权限 section 且拒绝错误 Job 泄漏字段', () => {
    expect(financeDashboard.auditTasks?.openCount).toBe(1)
    expect(financeDashboard.files?.items[0]?.jobStatus).toBe('succeeded')
    expect(() => decodeDashboard({ ...rawDashboard, item_limit: 0 })).toThrow('item_limit')
    expect(() => decodeDashboard({ ...rawDashboard, secret: true })).toThrow('unexpected')
  })

  it('只请求冻结的有界工作台路径', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ code: 'OK', message: 'success', data: rawDashboard, trace_id: traceId, timestamp: '2026-08-15T08:00:00Z' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const api = new DashboardApi(new ApiClient({ fetcher }))
    await api.get(5)
    expect(String(fetcher.mock.calls[0]?.[0])).toBe('/api/v1/dashboard?item_limit=5')
  })
})

describe('DashboardView', () => {
  it('展示真实审核与文件摘要并提供资源入口', async () => {
    vi.spyOn(dashboardApi, 'get').mockResolvedValue(financeDashboard)
    const router = await routerForDashboard()
    wrapper = mount(DashboardView, { global: { plugins: [router, piniaFor(['audits.read', 'files.read'])] } })
    await flushPromises()
    expect(wrapper.text()).toContain('月度财务审核')
    expect(wrapper.text()).toContain('invoice.docx')
    expect(wrapper.text()).toContain('真实权限摘要')
    expect(wrapper.text()).not.toContain('演示数据')
    expect(wrapper.get(`a[href="/audit-tasks/${taskId}"]`).text()).toBe('查看')
    expect(wrapper.get(`a[href="/files/${fileId}"]`).text()).toBe('查看')
  })

  it('后端返回超出当前权限的 section 时失败关闭', async () => {
    vi.spyOn(dashboardApi, 'get').mockResolvedValue(financeDashboard)
    const router = await routerForDashboard()
    wrapper = mount(DashboardView, { global: { plugins: [router, piniaFor([])] } })
    await flushPromises()
    expect(wrapper.text()).toContain('工作台摘要加载失败')
    expect(wrapper.text()).not.toContain('月度财务审核')
  })
})
