import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError } from '@/services/api'
import {
  decodeSupplier,
  decodeSupplierList,
  SupplierApi,
  supplierApi,
  type Supplier,
} from '@/services/suppliers'
import { useAuthStore } from '@/stores/auth'
import SupplierDetailView from '@/views/SupplierDetailView.vue'
import SupplierListView from '@/views/SupplierListView.vue'

const supplierId = '51000000-0000-4000-8000-000000000001'
const sourceId = '52000000-0000-4000-8000-000000000001'
const userId = '53000000-0000-4000-8000-000000000001'
const correctionId = '54000000-0000-4000-8000-000000000001'
const traceId = '55000000-0000-4000-8000-000000000001'

const rawCandidate = {
  id: supplierId,
  standard_name: '示例供应商',
  tax_number: '91310000EXAMPLE01',
  source_type: 'contract',
  source_contract_id: sourceId,
  source_invoice_id: null,
  confirmation_status: 'unconfirmed',
  status: 'candidate',
  confirmed_by: null,
  confirmed_at: null,
  row_version: '7',
}
const candidate = decodeSupplier(rawCandidate)
const active: Supplier = {
  ...candidate,
  confirmationStatus: 'confirmed',
  status: 'active',
  confirmedBy: userId,
  confirmedAt: '2026-08-15T08:00:00Z',
  rowVersion: '8',
}

let wrapper: VueWrapper | undefined

function jsonResponse(data: unknown): Response {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      data,
      trace_id: traceId,
      timestamp: '2026-08-15T08:00:00Z',
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

function createTestPinia(canCorrect = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).setAuthenticatedSession(
    {
      id: userId,
      displayName: '供应商复核用户',
      roles: ['contract_admin'],
      permissions: canCorrect ? ['financial.read', 'suppliers.correct'] : ['financial.read'],
    },
    'test-token',
  )
  return pinia
}

async function listRouter(query = ''): Promise<Router> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/suppliers', name: 'suppliers', component: SupplierListView },
      { path: '/suppliers/:supplierId', name: 'supplier-detail', component: { template: '<div>供应商目标</div>' } },
    ],
  })
  await router.push(`/suppliers${query}`)
  await router.isReady()
  return router
}

async function detailRouter(): Promise<Router> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/suppliers', name: 'suppliers', component: { template: '<div />' } },
      { path: '/suppliers/:supplierId', name: 'supplier-detail', component: SupplierDetailView },
      { path: '/contracts/:contractId', name: 'contract-detail', component: { template: '<div />' } },
      { path: '/invoices/:invoiceId', name: 'invoice-detail', component: { template: '<div />' } },
    ],
  })
  await router.push(`/suppliers/${supplierId}`)
  await router.isReady()
  return router
}

beforeEach(() => {
  vi.spyOn(supplierApi, 'list').mockResolvedValue({
    items: [candidate],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(supplierApi, 'getDetail').mockResolvedValue(candidate)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('SupplierApi', () => {
  it('严格解码供应商状态、来源引用和分页形状', () => {
    expect(candidate).toMatchObject({ standardName: '示例供应商', sourceContractId: sourceId })
    expect(() => decodeSupplier({ ...rawCandidate, status: 'active' })).toThrow('inconsistent')
    expect(() => decodeSupplier({ ...rawCandidate, unknown: true })).toThrow('unexpected')
    expect(() =>
      decodeSupplierList({ items: [rawCandidate], page_size: 20, next_cursor: 'eyJ2IjoxfQ' }),
    ).toThrow('page shape')
  })

  it('读取、解析来源和更新候选使用冻结路径与幂等键', async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input)
      if (path.endsWith('/source-candidates')) {
        return jsonResponse({ supplier: rawCandidate, source_row_version: '3', created: true, reused: false })
      }
      if (path.endsWith(supplierId) && fetcher.mock.calls.at(-1)?.[1]?.method === 'PATCH') {
        return jsonResponse({
          supplier: { ...rawCandidate, confirmation_status: 'confirmed', status: 'active', confirmed_by: userId, confirmed_at: '2026-08-15T08:00:00Z', row_version: '8' },
          candidate_id: supplierId,
          candidate_row_version: '8',
          source_row_version: '4',
          correction_id: correctionId,
          reused: false,
        })
      }
      return path.includes('?')
        ? jsonResponse({ items: [rawCandidate], page_size: 20, next_cursor: null })
        : jsonResponse(rawCandidate)
    })
    const api = new SupplierApi(new ApiClient({ fetcher }))

    await api.list(20)
    await api.getDetail(supplierId)
    await api.resolveSource(
      { sourceType: 'contract', sourceId, rowVersion: '3' },
      'supplier-resolve.12345678',
    )
    await api.updateCandidate(
      supplierId,
      { rowVersion: '7', reason: '人工核对', decision: 'confirmed' },
      'supplier-update.12345678',
    )

    expect(String(fetcher.mock.calls[0]?.[0])).toBe('/api/v1/suppliers?page_size=20')
    expect(String(fetcher.mock.calls[1]?.[0])).toBe(`/api/v1/suppliers/${supplierId}`)
    expect(new Headers(fetcher.mock.calls[2]?.[1]?.headers).get('Idempotency-Key')).toBe('supplier-resolve.12345678')
    expect(new Headers(fetcher.mock.calls[3]?.[1]?.headers).get('Idempotency-Key')).toBe('supplier-update.12345678')
  })
})

describe('SupplierListView', () => {
  it('展示真实列表，并从合同详情带入来源后解析候选', async () => {
    const resolve = vi.spyOn(supplierApi, 'resolveSource').mockResolvedValue({
      supplier: candidate,
      sourceRowVersion: '3',
      created: true,
      reused: false,
    })
    const router = await listRouter(`?source_type=contract&source_id=${sourceId}&row_version=3`)
    wrapper = mount(SupplierListView, { global: { plugins: [createTestPinia(), router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('示例供应商')
    expect(wrapper.get<HTMLInputElement>('#supplier-source-id').element.value).toBe(sourceId)
    await wrapper.get('[data-testid="resolve-supplier-source"]').trigger('submit')
    await flushPromises()

    expect(resolve).toHaveBeenCalledWith(
      { sourceType: 'contract', sourceId, rowVersion: '3' },
      expect.stringMatching(/^supplier-resolve\./),
      expect.any(AbortSignal),
    )
    expect(router.currentRoute.value.name).toBe('supplier-detail')
  })

  it('没有修正权限时只展示供应商事实，不展示解析表单', async () => {
    const router = await listRouter()
    wrapper = mount(SupplierListView, { global: { plugins: [createTestPinia(false), router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('示例供应商')
    expect(wrapper.find('[data-testid="resolve-supplier-source"]').exists()).toBe(false)
  })
})

describe('SupplierDetailView', () => {
  it('未知失败重试复用幂等键，并确认候选为活动供应商', async () => {
    const update = vi
      .spyOn(supplierApi, 'updateCandidate')
      .mockRejectedValueOnce(new ApiError({ code: 'NETWORK_ERROR', message: 'raw', status: 0, traceId: '' }))
      .mockResolvedValueOnce({
        supplier: active,
        candidateId: supplierId,
        candidateRowVersion: '8',
        sourceRowVersion: '4',
        correctionId,
        reused: false,
      })
    const router = await detailRouter()
    wrapper = mount(SupplierDetailView, { global: { plugins: [createTestPinia(), router] } })
    await flushPromises()
    await wrapper.get('#supplier-reason').setValue('已核对税务身份与来源原文')

    await wrapper.get('[data-testid="confirm-supplier"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('供应商操作失败')
    await wrapper.get('[data-testid="confirm-supplier"]').trigger('click')
    await flushPromises()

    expect(update).toHaveBeenCalledTimes(2)
    expect(update.mock.calls[1]?.[2]).toBe(update.mock.calls[0]?.[2])
    expect(wrapper.text()).toContain('供应商候选已确认并激活')
    expect(wrapper.text()).toContain('该供应商已完成人工处理')
  })
})
