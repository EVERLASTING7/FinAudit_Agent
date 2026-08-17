import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { ApiClient, ApiError } from '@/services/api'
import {
  ContractPrimaryInvoiceApi,
  contractPrimaryInvoiceApi,
  decodeContractPrimaryInvoiceList,
  type ContractPrimaryInvoiceListData,
} from '@/services/contractPrimaryInvoices'
import ContractPrimaryInvoiceListView from '@/views/ContractPrimaryInvoiceListView.vue'

const contractId = '30000000-0000-4000-8000-000000000020'
const nextContractId = '30000000-0000-4000-8000-000000000021'
const traceId = '90000000-0000-4000-8000-000000000010'
const rawItem = {
  id: '40000000-0000-4000-8000-000000000001',
  invoice_code: 'INV-CODE',
  invoice_number: 'INV-0001',
  invoice_date: '2026-08-01',
  seller_name: '销售方企业',
  total_amount: '120.00',
  currency: 'CNY',
  confirmation_status: 'confirmed',
  duplicate_status: 'unique',
  status: 'confirmed',
}
const validCursor = btoa(JSON.stringify({ id: rawItem.id, v: 1 }))
  .replace(/\+/g, '-')
  .replace(/\//g, '_')
  .replace(/=+$/, '')
function encodeCursorPayload(payload: string): string {
  return btoa(payload).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
const firstPage = decodeContractPrimaryInvoiceList({
  items: Array.from({ length: 20 }, (_value, index) => ({
    ...rawItem,
    id: `40000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
  })),
  page_size: 20,
  next_cursor: validCursor,
})
const emptyPage: ContractPrimaryInvoiceListData = {
  items: [],
  pageSize: 20,
  nextCursor: null,
}

let wrapper: VueWrapper | undefined

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
      trace_id: traceId,
      timestamp: '2026-08-12T00:00:00Z',
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

async function mountPage(path = `/contracts/${contractId}/primary-invoices`): Promise<{
  page: VueWrapper
  router: Router
}> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/contracts/:contractId/primary-invoices',
        component: ContractPrimaryInvoiceListView,
      },
      { path: '/contracts/:contractId', name: 'contract-detail', component: { template: '<div />' } },
      { path: '/invoices/:invoiceId', name: 'invoice-detail', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(ContractPrimaryInvoiceListView, { global: { plugins: [router] } })
  await flushPromises()
  return { page: wrapper, router }
}

describe('ContractPrimaryInvoiceApi', () => {
  it('请求合同范围端点并复用严格发票摘要 DTO', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ items: [rawItem], page_size: 20, next_cursor: null }),
    )
    const api = new ContractPrimaryInvoiceApi(new ApiClient({ fetcher }))

    await expect(api.list(contractId, 20, validCursor)).resolves.toMatchObject({
      items: [{ id: rawItem.id, invoiceNumber: 'INV-0001', totalAmount: '120.00' }],
      pageSize: 20,
    })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/contracts/${contractId}/primary-invoices?page_size=20&cursor=${validCursor}`,
    )
  })

  it.each([
    ['额外关系字段', { relation_id: '40000000-0000-4000-8000-000000000099' }],
    ['关系状态冗余', { relation_status: 'confirmed_primary' }],
    ['匹配依据', { match_reasons_json: {} }],
    ['非法日期', { invoice_date: '2026-02-31' }],
    ['非法金额', { total_amount: '00.10' }],
    ['未知状态', { status: 'active' }],
  ])('拒绝列表项的%s', (_label, change) => {
    expect(() =>
      decodeContractPrimaryInvoiceList({
        items: [{ ...rawItem, ...change }],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })

  it('拒绝重复或非严格 ID 升序、短页带 cursor 和额外顶层字段', () => {
    const larger = { ...rawItem, id: '40000000-0000-4000-8000-000000000002' }
    expect(() =>
      decodeContractPrimaryInvoiceList({
        items: [larger, rawItem],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
    expect(() =>
      decodeContractPrimaryInvoiceList({
        items: [rawItem, rawItem],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
    expect(() =>
      decodeContractPrimaryInvoiceList({
        items: [rawItem],
        page_size: 20,
        next_cursor: validCursor,
      }),
    ).toThrow()
    expect(() =>
      decodeContractPrimaryInvoiceList({
        items: [],
        page_size: 20,
        next_cursor: null,
        total: 0,
      }),
    ).toThrow()
  })

  it.each([
    ['missing id', encodeCursorPayload('{"v":1}')],
    ['extra key', encodeCursorPayload(`{"extra":null,"id":"${rawItem.id}","v":1}`)],
    ['padding', `${validCursor}=`],
    ['noncanonical JSON', encodeCursorPayload(`{ "v": 1, "id": "${rawItem.id}" }`)],
    ['noncanonical key order', encodeCursorPayload(`{"v":1,"id":"${rawItem.id}"}`)],
    ['noncanonical UUID', encodeCursorPayload('{"id":"40000000-0000-4000-8000-00000000000A","v":1}')],
  ])('请求和响应均拒绝%s cursor', async (_label, cursor) => {
    expect(() =>
      decodeContractPrimaryInvoiceList({
        items: [],
        page_size: 20,
        next_cursor: cursor,
      }),
    ).toThrow()

    const fetcher = vi.fn<typeof fetch>()
    const api = new ContractPrimaryInvoiceApi(new ApiClient({ fetcher }))
    await expect(api.list(contractId, 20, cursor)).rejects.toThrow('canonical base64url')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('非法 UUID、page_size、cursor 不发请求，响应 page_size 必须匹配', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ items: [], page_size: 10, next_cursor: null }),
    )
    const api = new ContractPrimaryInvoiceApi(new ApiClient({ fetcher }))

    await expect(api.list('CON-001')).rejects.toThrow('canonical lowercase UUID')
    await expect(api.list(contractId, 0)).rejects.toThrow()
    await expect(api.list(contractId, 20, 'bad=cursor')).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
    await expect(api.list(contractId)).rejects.toThrow('does not match request')
  })
})

describe('ContractPrimaryInvoiceListView', () => {
  it('展示真实摘要并链接 canonical 发票详情，不展示候选或写操作', async () => {
    vi.spyOn(contractPrimaryInvoiceApi, 'list').mockResolvedValue({
      ...emptyPage,
      items: [firstPage.items[0]!],
    })

    const { page } = await mountPage()

    expect(page.text()).toContain('INV-0001')
    expect(page.text()).toContain('UUID 顺序不代表业务时间')
    expect(page.get(`a[href="/invoices/${rawItem.id}"]`).text()).toBe('查看')
    expect(page.text()).not.toContain('匹配分数')
    expect(page.findAll('button').some((button) => button.text() === '确认主合同')).toBe(false)
    expect(page.findAll('button').some((button) => button.text() === '取消关系')).toBe(false)
  })

  it('展示父合同范围空态', async () => {
    vi.spyOn(contractPrimaryInvoiceApi, 'list').mockResolvedValue(emptyPage)
    const { page } = await mountPage()
    expect(page.text()).toContain('当前合同没有作为已确认主合同的发票。')
  })

  it('cursor 翻页失败后重试保持 cursor，并可返回上一页', async () => {
    vi.spyOn(contractPrimaryInvoiceApi, 'list')
      .mockResolvedValueOnce(firstPage)
      .mockRejectedValueOnce(new Error('raw synthetic'))
      .mockResolvedValueOnce(emptyPage)
      .mockResolvedValueOnce(firstPage)
    const { page } = await mountPage()

    await page.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('当前主合同发票加载失败，请稍后重试。')
    expect(page.text()).not.toContain('raw synthetic')
    await page.get('[data-testid="retry-contract-primary-invoices"]').trigger('click')
    await flushPromises()
    expect(contractPrimaryInvoiceApi.list).toHaveBeenNthCalledWith(
      3,
      contractId,
      20,
      validCursor,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('第 2 页')
    await page.get('button[aria-label="上一页"]').trigger('click')
    await flushPromises()
    expect(contractPrimaryInvoiceApi.list).toHaveBeenNthCalledWith(
      4,
      contractId,
      20,
      undefined,
      expect.any(AbortSignal),
    )
  })

  it.each([
    [401, '登录状态已失效，请重新登录。'],
    [403, '当前账号无权读取此合同的当前主合同发票。'],
    [404, '合同不存在，或当前账号无权访问。'],
    [500, '当前主合同发票加载失败，请稍后重试。'],
  ])('%i 安全展示且仅显示 ApiError Trace', async (status, expected) => {
    vi.spyOn(contractPrimaryInvoiceApi, 'list').mockRejectedValue(
      new ApiError({ code: 'SYNTHETIC', message: 'raw backend secret', status, traceId }),
    )
    const { page } = await mountPage()
    expect(page.text()).toContain(expected)
    expect(page.text()).toContain(traceId)
    expect(page.text()).not.toContain('raw backend secret')
  })

  it('路由切换中止旧请求并忽略无视 Abort 的迟到响应', async () => {
    let oldSignal: AbortSignal | undefined
    let resolveOld: ((value: ContractPrimaryInvoiceListData) => void) | undefined
    vi.spyOn(contractPrimaryInvoiceApi, 'list').mockImplementation(
      (id, _pageSize, _cursor, signal) => {
        if (id === contractId) {
          oldSignal = signal
          return new Promise<ContractPrimaryInvoiceListData>((resolve) => {
            resolveOld = resolve
          })
        }
        return Promise.resolve({
          ...emptyPage,
          items: [{ ...firstPage.items[0]!, invoiceNumber: 'NEXT-INVOICE' }],
        })
      },
    )
    const { page, router } = await mountPage()
    await router.push(`/contracts/${nextContractId}/primary-invoices`)
    await flushPromises()
    resolveOld?.({ ...emptyPage, items: [firstPage.items[0]!] })
    await flushPromises()

    expect(oldSignal?.aborted).toBe(true)
    expect(page.text()).toContain('NEXT-INVOICE')
    expect(page.text()).not.toContain('INV-0001')
  })

  it('有效路由切非法标识时清除 loading、Abort 且不发新请求', async () => {
    let signal: AbortSignal | undefined
    const list = vi.spyOn(contractPrimaryInvoiceApi, 'list').mockImplementation(
      (_id, _pageSize, _cursor, requestSignal) => {
        signal = requestSignal
        return new Promise<ContractPrimaryInvoiceListData>(() => undefined)
      },
    )
    const { page, router } = await mountPage()
    await router.push('/contracts/CON-001/primary-invoices')
    await flushPromises()

    expect(signal?.aborted).toBe(true)
    expect(page.text()).toContain('合同标识无效，未向服务器发送请求。')
    expect(page.text()).not.toContain('正在加载当前主合同发票…')
    expect(list).toHaveBeenCalledTimes(1)
  })

  it('卸载时中止请求', async () => {
    let signal: AbortSignal | undefined
    vi.spyOn(contractPrimaryInvoiceApi, 'list').mockImplementation(
      (_id, _pageSize, _cursor, requestSignal) => {
        signal = requestSignal
        return new Promise<ContractPrimaryInvoiceListData>(() => undefined)
      },
    )
    const { page } = await mountPage()
    page.unmount()
    wrapper = undefined
    expect(signal?.aborted).toBe(true)
  })
})
