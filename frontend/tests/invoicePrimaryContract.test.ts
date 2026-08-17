import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiClient, ApiError } from '@/services/api'
import { decodeContractListItem, type ContractListItem } from '@/services/contracts'
import {
  InvoicePrimaryContractApi,
  decodeContractInvoiceCandidates,
  decodeContractInvoiceHistory,
  decodeContractInvoiceMutation,
  decodeInvoicePrimaryContract,
  invoicePrimaryContractApi,
  type InvoicePrimaryContractData,
} from '@/services/invoicePrimaryContract'
import ContractInvoiceLinkView from '@/views/ContractInvoiceLinkView.vue'
import { useAuthStore } from '@/stores/auth'
import type { PermissionCode } from '@/services/auth'

const invoiceId = '40000000-0000-4000-8000-000000000001'
const contractId = '30000000-0000-4000-8000-000000000020'
const rawContract = {
  id: contractId,
  contract_no: 'HT-2026-0020',
  name: '企业软件服务合同',
  party_b_name: '服务供应方',
  amount: '1200000.00',
  currency: 'CNY',
  effective_date: '2026-01-01',
  expiry_date: '2026-12-31',
  confirmation_status: 'confirmed',
  status: 'active',
}
const contract: ContractListItem = decodeContractListItem(rawContract)
const relationId = '50000000-0000-4000-8000-000000000001'
const rawMatchReasons = {
  tax_no: { status: 'matched', code: 'tax_no_matched' },
  name: { status: 'mismatched', code: 'name_mismatched' },
  date: { status: 'unavailable', code: 'date_unavailable' },
}
const rawSuggestedRelation = {
  id: relationId,
  contract_id: contractId,
  status: 'suggested',
  match_reasons: rawMatchReasons,
  suggested_at: '2026-08-12T00:00:00Z',
  confirmed_at: null,
  cancelled_at: null,
  cancel_reason: null,
  row_version: '1',
}

let wrapper: VueWrapper | undefined

beforeEach(() => {
  vi.spyOn(invoicePrimaryContractApi, 'listCandidates').mockResolvedValue({
    invoiceId,
    invoiceRowVersion: '1',
    items: [],
  })
  vi.spyOn(invoicePrimaryContractApi, 'getHistory').mockResolvedValue({
    invoiceId,
    items: [],
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

function jsonResponse(data: unknown): Response {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      data,
      trace_id: '90000000-0000-4000-8000-000000000010',
      timestamp: '2026-08-12T00:00:00Z',
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

async function mountPage(path: string): Promise<{
  page: VueWrapper
  router: ReturnType<typeof createRouter>
}>
async function mountPage(path: string, permissions: PermissionCode[]): Promise<{
  page: VueWrapper
  router: ReturnType<typeof createRouter>
}>
async function mountPage(path: string, permissions: PermissionCode[] = []): Promise<{
  page: VueWrapper
  router: ReturnType<typeof createRouter>
}> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/invoices/:invoiceId/contract-links',
        name: 'contract-invoice-links',
        component: ContractInvoiceLinkView,
      },
      { path: '/invoices/:invoiceId', name: 'invoice-detail', component: { template: '<div />' } },
      { path: '/contracts/:contractId', name: 'contract-detail', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  const pinia = createPinia()
  if (permissions.length) {
    setActivePinia(pinia)
    useAuthStore(pinia).setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000001',
        displayName: '合同关联测试用户',
        roles: ['finance_reviewer'],
        permissions,
      },
      'test-token',
    )
  }
  wrapper = mount(ContractInvoiceLinkView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { page: wrapper, router }
}

describe('InvoicePrimaryContractApi', () => {
  it('请求 canonical UUID 主合同且无 query', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ primary_contract: rawContract }),
    )
    const api = new InvoicePrimaryContractApi(new ApiClient({ fetcher }))

    await expect(api.get(invoiceId)).resolves.toEqual({ primaryContract: contract })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/invoices/${invoiceId}/primary-contract`,
    )
  })

  it('接受 null 空态并拒绝多余字段或非法嵌套合同', () => {
    expect(decodeInvoicePrimaryContract({ primary_contract: null })).toEqual({
      primaryContract: null,
    })
    expect(() =>
      decodeInvoicePrimaryContract({ primary_contract: null, extra: true }),
    ).toThrow()
    expect(() =>
      decodeInvoicePrimaryContract({
        primary_contract: { ...rawContract, amount: '00.10' },
      }),
    ).toThrow()
    expect(() =>
      decodeInvoicePrimaryContract({
        primary_contract: { ...rawContract, effective_date: '2026-02-31' },
      }),
    ).toThrow()
    expect(() =>
      decodeInvoicePrimaryContract({
        primary_contract: { ...rawContract, relation_status: 'confirmed_primary' },
      }),
    ).toThrow()
  })

  it('非法 invoice UUID 不发送请求', async () => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new InvoicePrimaryContractApi(new ApiClient({ fetcher }))

    await expect(api.get('INV-001')).rejects.toThrow('canonical lowercase UUID')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('严格解码候选、关系生命周期、历史与 mutation', () => {
    const candidateData = decodeContractInvoiceCandidates({
      invoice_id: invoiceId,
      invoice_row_version: '1',
      items: [{ contract: rawContract, match_reasons: rawMatchReasons }],
    })
    expect(candidateData.items[0]?.matchReasons).toEqual({
      taxNo: { status: 'matched', code: 'tax_no_matched' },
      name: { status: 'mismatched', code: 'name_mismatched' },
      date: { status: 'unavailable', code: 'date_unavailable' },
    })
    expect(
      decodeContractInvoiceHistory({ invoice_id: invoiceId, items: [rawSuggestedRelation] }),
    ).toMatchObject({ invoiceId, items: [{ id: relationId, status: 'suggested' }] })
    expect(
      decodeContractInvoiceMutation({
        invoice_id: invoiceId,
        invoice_row_version: '2',
        relation: rawSuggestedRelation,
        previous_primary_relation_id: null,
      }),
    ).toMatchObject({ invoiceId, invoiceRowVersion: '2' })
  })

  it('拒绝匹配 code 漂移和不一致关系生命周期', () => {
    expect(() =>
      decodeContractInvoiceCandidates({
        invoice_id: invoiceId,
        invoice_row_version: '1',
        items: [
          {
            contract: rawContract,
            match_reasons: {
              ...rawMatchReasons,
              tax_no: { status: 'matched', code: 'tax_no_mismatched' },
            },
          },
        ],
      }),
    ).toThrow(TypeError)
    expect(() =>
      decodeContractInvoiceHistory({
        invoice_id: invoiceId,
        items: [{ ...rawSuggestedRelation, confirmed_at: '2026-08-12T00:01:00Z' }],
      }),
    ).toThrow(TypeError)
  })

  it('发送建议、确认与取消的精确版本字段和幂等键', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        invoice_id: invoiceId,
        invoice_row_version: '2',
        relation: rawSuggestedRelation,
        previous_primary_relation_id: null,
      }),
    )
    const api = new InvoicePrimaryContractApi(new ApiClient({ fetcher }))
    await api.suggest(
      invoiceId,
      { contractId, invoiceRowVersion: '1', reason: '人工建议' },
      'contract-link.unit-001',
    )
    const firstBody = JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))
    expect(firstBody).toEqual({
      contract_id: contractId,
      invoice_row_version: '1',
      reason: '人工建议',
    })
    expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'contract-link.unit-001',
    )
  })
})

describe('ContractInvoiceLinkView', () => {
  it('展示真实主合同与 canonical 详情链接且没有 Demo/写操作', async () => {
    vi.spyOn(invoicePrimaryContractApi, 'get').mockResolvedValue({ primaryContract: contract })
    const { page } = await mountPage(`/invoices/${invoiceId}/contract-links`)

    expect(page.get('h1').text()).toContain('发票主合同')
    expect(page.text()).toContain('企业软件服务合同')
    expect(page.text()).toContain('1,200,000.00 CNY')
    expect(page.get(`a[href="/contracts/${contractId}"]`).text()).toBe('查看合同详情')
    expect(page.text()).not.toContain('当前演示数据集')
    expect(page.text()).not.toContain('税务身份匹配')
    expect(page.text()).not.toContain('日期范围匹配')
    expect(page.text()).not.toContain('HT-2025-0417')
    expect(page.findAll('button')).toHaveLength(0)
  })

  it('没有主合同时展示 200 空态', async () => {
    vi.spyOn(invoicePrimaryContractApi, 'get').mockResolvedValue({ primaryContract: null })
    const { page } = await mountPage(`/invoices/${invoiceId}/contract-links`)

    expect(page.text()).toContain('当前没有已确认主合同')
    expect(page.text()).toContain('不表示发票不存在')
  })

  it('非法 UUID 不请求；404 安全显示 Trace 并可重试', async () => {
    const get = vi.spyOn(invoicePrimaryContractApi, 'get')
    let mounted = await mountPage('/invoices/INV-001/contract-links')
    expect(mounted.page.text()).toContain('发票标识无效，未向服务器发送请求。')
    expect(get).not.toHaveBeenCalled()
    mounted.page.unmount()
    wrapper = undefined

    get
      .mockRejectedValueOnce(
        new ApiError({
          code: 'RESOURCE_NOT_FOUND',
          message: 'raw',
          status: 404,
          traceId: '90000000-0000-4000-8000-000000000010',
        }),
      )
      .mockResolvedValueOnce({ primaryContract: null })
    mounted = await mountPage(`/invoices/${invoiceId}/contract-links`)
    expect(mounted.page.text()).toContain('发票不存在，或当前账号无权访问。')
    expect(mounted.page.text()).toContain('90000000-0000-4000-8000-000000000010')
    await mounted.page.get('[data-testid="retry-primary-contract"]').trigger('click')
    await flushPromises()
    expect(mounted.page.text()).toContain('当前没有已确认主合同')
  })

  it.each([
    [401, '登录状态已失效，请重新登录。'],
    [403, '当前账号无权读取此发票的主合同。'],
    [500, '主合同加载失败，请稍后重试。'],
  ])('%i 错误仅展示安全文案和 ApiError Trace', async (status, safeMessage) => {
    vi.spyOn(invoicePrimaryContractApi, 'get').mockRejectedValue(
      new ApiError({
        code: 'SYNTHETIC_ERROR',
        message: '不可信服务端原始消息',
        status,
        traceId: '90000000-0000-4000-8000-000000000010',
      }),
    )

    const { page } = await mountPage(`/invoices/${invoiceId}/contract-links`)
    expect(page.text()).toContain(safeMessage)
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    expect(page.text()).not.toContain('不可信服务端原始消息')
  })

  it('非 ApiError 通用失败不展示原始消息或 Trace', async () => {
    vi.spyOn(invoicePrimaryContractApi, 'get').mockRejectedValue(
      new Error('本地敏感失败细节'),
    )

    const { page } = await mountPage(`/invoices/${invoiceId}/contract-links`)
    expect(page.text()).toContain('主合同加载失败，请稍后重试。')
    expect(page.text()).not.toContain('本地敏感失败细节')
    expect(page.text()).not.toContain('Trace ID')
  })

  it('卸载中止请求并忽略路由切换后的迟到旧响应', async () => {
    let firstSignal: AbortSignal | undefined
    let resolveOld: ((value: InvoicePrimaryContractData) => void) | undefined
    const nextInvoiceId = '40000000-0000-4000-8000-000000000002'
    vi.spyOn(invoicePrimaryContractApi, 'get').mockImplementation((id, signal) => {
      if (id === invoiceId) {
        firstSignal = signal
        return new Promise<InvoicePrimaryContractData>((resolve) => {
          resolveOld = resolve
        })
      }
      return Promise.resolve({ primaryContract: null })
    })
    const mounted = await mountPage(`/invoices/${invoiceId}/contract-links`)
    expect(mounted.page.text()).toContain('正在加载发票主合同…')

    await mounted.router.push(`/invoices/${nextInvoiceId}/contract-links`)
    await flushPromises()
    expect(firstSignal?.aborted).toBe(true)
    expect(mounted.page.text()).toContain('当前没有已确认主合同')
    resolveOld?.({ primaryContract: contract })
    await flushPromises()
    expect(mounted.page.text()).not.toContain('企业软件服务合同')

    mounted.page.unmount()
    wrapper = undefined
    expect(firstSignal?.aborted).toBe(true)
  })

  it('有效 UUID 加载中切非法路由时退出 loading', async () => {
    vi.spyOn(invoicePrimaryContractApi, 'get').mockImplementation(
      () => new Promise<InvoicePrimaryContractData>(() => undefined),
    )
    const mounted = await mountPage(`/invoices/${invoiceId}/contract-links`)
    expect(mounted.page.text()).toContain('正在加载发票主合同…')

    await mounted.router.push('/invoices/not-a-uuid/contract-links')
    await flushPromises()
    expect(mounted.page.text()).toContain('发票标识无效，未向服务器发送请求。')
    expect(mounted.page.text()).not.toContain('正在加载发票主合同…')
  })

  it('建议未知失败后复用同一幂等键，成功后读取建议历史', async () => {
    const candidateData = decodeContractInvoiceCandidates({
      invoice_id: invoiceId,
      invoice_row_version: '1',
      items: [{ contract: rawContract, match_reasons: rawMatchReasons }],
    })
    const suggestedHistory = decodeContractInvoiceHistory({
      invoice_id: invoiceId,
      items: [rawSuggestedRelation],
    })
    vi.spyOn(invoicePrimaryContractApi, 'get').mockResolvedValue({ primaryContract: null })
    vi.mocked(invoicePrimaryContractApi.listCandidates)
      .mockResolvedValueOnce(candidateData)
      .mockResolvedValueOnce({ ...candidateData, invoiceRowVersion: '2' })
    vi.mocked(invoicePrimaryContractApi.getHistory)
      .mockResolvedValueOnce({ invoiceId, items: [] })
      .mockResolvedValueOnce(suggestedHistory)
    const suggest = vi
      .spyOn(invoicePrimaryContractApi, 'suggest')
      .mockRejectedValueOnce(
        new ApiError({ code: 'NETWORK_ERROR', message: 'raw', status: 0, traceId: '' }),
      )
      .mockResolvedValueOnce(
        decodeContractInvoiceMutation({
          invoice_id: invoiceId,
          invoice_row_version: '2',
          relation: rawSuggestedRelation,
          previous_primary_relation_id: null,
        }),
      )
    const { page } = await mountPage(
      `/invoices/${invoiceId}/contract-links`,
      ['financial.read', 'links.suggest'],
    )
    await page.get('#contract-link-reason').setValue('依据税号和日期提交建议')
    const button = page.get(`[data-testid="suggest-contract-${contractId}"]`)

    await button.trigger('click')
    await flushPromises()
    expect(page.text()).toContain('合同关联操作失败')
    await button.trigger('click')
    await flushPromises()

    expect(suggest).toHaveBeenCalledTimes(2)
    expect(suggest.mock.calls[1]?.[2]).toBe(suggest.mock.calls[0]?.[2])
    expect(page.text()).toContain(relationId)
    expect(page.text()).toContain('待确认建议')
  })

  it('确认与取消始终使用最新发票和关系行版本', async () => {
    const candidateData = decodeContractInvoiceCandidates({
      invoice_id: invoiceId,
      invoice_row_version: '2',
      items: [{ contract: rawContract, match_reasons: rawMatchReasons }],
    })
    const confirmedRaw = {
      ...rawSuggestedRelation,
      status: 'confirmed_primary',
      confirmed_at: '2026-08-12T00:01:00Z',
      row_version: '2',
    }
    const cancelledRaw = {
      ...confirmedRaw,
      status: 'cancelled',
      cancelled_at: '2026-08-12T00:02:00Z',
      cancel_reason: '复核后取消当前主合同',
      row_version: '3',
    }
    const suggestedHistory = decodeContractInvoiceHistory({
      invoice_id: invoiceId,
      items: [rawSuggestedRelation],
    })
    const confirmedHistory = decodeContractInvoiceHistory({
      invoice_id: invoiceId,
      items: [confirmedRaw],
    })
    const cancelledHistory = decodeContractInvoiceHistory({
      invoice_id: invoiceId,
      items: [cancelledRaw],
    })
    vi.spyOn(invoicePrimaryContractApi, 'get')
      .mockResolvedValueOnce({ primaryContract: null })
      .mockResolvedValueOnce({ primaryContract: contract })
      .mockResolvedValueOnce({ primaryContract: null })
    vi.mocked(invoicePrimaryContractApi.listCandidates)
      .mockResolvedValueOnce(candidateData)
      .mockResolvedValueOnce({ ...candidateData, invoiceRowVersion: '3' })
      .mockResolvedValueOnce({ ...candidateData, invoiceRowVersion: '4' })
    vi.mocked(invoicePrimaryContractApi.getHistory)
      .mockResolvedValueOnce(suggestedHistory)
      .mockResolvedValueOnce(confirmedHistory)
      .mockResolvedValueOnce(cancelledHistory)
    const setPrimary = vi.spyOn(invoicePrimaryContractApi, 'setPrimary').mockResolvedValue(
      decodeContractInvoiceMutation({
        invoice_id: invoiceId,
        invoice_row_version: '3',
        relation: confirmedRaw,
        previous_primary_relation_id: null,
      }),
    )
    const cancel = vi.spyOn(invoicePrimaryContractApi, 'cancelPrimary').mockResolvedValue(
      decodeContractInvoiceMutation({
        invoice_id: invoiceId,
        invoice_row_version: '4',
        relation: cancelledRaw,
        previous_primary_relation_id: null,
      }),
    )
    const { page } = await mountPage(
      `/invoices/${invoiceId}/contract-links`,
      ['financial.read', 'links.manage_primary'],
    )
    await page.get('#contract-link-reason').setValue('财务复核确认主合同')
    await page.get(`[data-testid="confirm-suggestion-${relationId}"]`).trigger('click')
    await flushPromises()
    expect(setPrimary.mock.calls[0]?.[1]).toMatchObject({
      invoiceRowVersion: '2',
      relationRowVersion: '1',
    })

    await page.get('#contract-link-reason').setValue('复核后取消当前主合同')
    await page.get('[data-testid="cancel-primary-contract"]').trigger('click')
    await flushPromises()
    expect(cancel.mock.calls[0]?.[1]).toEqual({
      invoiceRowVersion: '3',
      relationRowVersion: '2',
      reason: '复核后取消当前主合同',
    })
    expect(page.text()).toContain('当前没有已确认主合同')
  })
})
