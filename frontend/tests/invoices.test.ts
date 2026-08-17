import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiClient, ApiError } from '@/services/api'
import {
  InvoiceApi,
  decodeInvoiceDetail,
  decodeInvoiceDuplicateCandidateList,
  decodeInvoiceEvidenceResponse,
  decodeInvoiceExactDuplicatePair,
  decodeInvoiceList,
  decodeInvoiceMutation,
  invoiceApi,
  type InvoiceDetail,
  type InvoiceDuplicateCandidateListData,
  type InvoiceExactDuplicatePairData,
  type InvoiceListData,
} from '@/services/invoices'
import InvoiceDetailView from '@/views/InvoiceDetailView.vue'
import InvoiceListView from '@/views/InvoiceListView.vue'

const invoiceId = '40000000-0000-4000-8000-000000000001'
const itemId = '40000000-0000-4000-8000-000000000002'
const rawInvoice = {
  id: invoiceId,
  invoice_code: '031002600311',
  invoice_number: '66720193',
  invoice_type: '增值税电子普通发票',
  is_red_invoice: false,
  invoice_date: '2026-07-31',
  buyer_name: '购买方公司',
  buyer_tax_no: 'BUYER-TAX-NO',
  seller_name: '销售方公司',
  seller_tax_no: 'SELLER-TAX-NO',
  amount_excluding_tax: '100.00',
  tax_amount: '6.00',
  total_amount: '106.00',
  currency: 'CNY',
  confirmation_status: 'confirmed',
  duplicate_status: 'unique',
  status: 'confirmed',
  row_version: '2',
  items: [
    {
      id: itemId,
      line_no: 1,
      item_name: '审计服务',
      specification: null,
      unit: '项',
      quantity: '1',
      unit_price: '100.00',
      amount_excluding_tax: '100.00',
      tax_rate: '0.06',
      tax_amount: '6.00',
      total_amount: '106.00',
      row_version: '1',
    },
  ],
}

const invoice = decodeInvoiceDetail(rawInvoice)
const rawListItem = {
  id: invoiceId,
  invoice_code: rawInvoice.invoice_code,
  invoice_number: rawInvoice.invoice_number,
  invoice_date: rawInvoice.invoice_date,
  seller_name: rawInvoice.seller_name,
  total_amount: rawInvoice.total_amount,
  currency: rawInvoice.currency,
  confirmation_status: rawInvoice.confirmation_status,
  duplicate_status: rawInvoice.duplicate_status,
  status: rawInvoice.status,
}
const rawListItems = Array.from({ length: 20 }, (_value, index) => {
  const sequence = 20 - index
  return {
    ...rawListItem,
    id: `40000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
    invoice_number: sequence === 1 ? rawListItem.invoice_number : `LIST-${sequence}`,
  }
})
const invoiceList = decodeInvoiceList({
  items: rawListItems,
  page_size: 20,
  next_cursor: 'eyJ2IjoxfQ',
})
const duplicateCandidateId = '40000000-0000-4000-8000-000000000021'
const rawDuplicateCandidate = {
  ...rawListItem,
  id: duplicateCandidateId,
}

function encodeIdCursor(id: string): string {
  return btoa(JSON.stringify({ id, v: 1 }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
}

function encodeCursorText(text: string): string {
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

const duplicateCandidateCursor = encodeIdCursor(duplicateCandidateId)
const readyDuplicateCandidatePage = decodeInvoiceDuplicateCandidateList({
  basis_status: 'ready',
  items: [rawDuplicateCandidate],
  page_size: 20,
  next_cursor: null,
})
const rawExactDuplicatePair = {
  source: rawListItem,
  candidate: rawDuplicateCandidate,
  exact_identity: {
    invoice_code: rawInvoice.invoice_code,
    invoice_number: rawInvoice.invoice_number,
    seller_tax_no: rawInvoice.seller_tax_no,
  },
}
const exactDuplicatePair = decodeInvoiceExactDuplicatePair(rawExactDuplicatePair)
const blockId = '42000000-0000-4000-8000-000000000001'
const parseVersionId = '42000000-0000-4000-8000-000000000002'
const rawEvidence = {
  block_id: blockId,
  parse_version_id: parseVersionId,
  page_no: 1,
  quote_text: '发票号码：66720193',
  bbox: { x: 1, y: 2 },
  confidence: '0.98',
}
let wrapper: VueWrapper | undefined

beforeEach(() => {
  vi.spyOn(invoiceApi, 'listDuplicateCandidates').mockResolvedValue({
    basisStatus: 'ready',
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(invoiceApi, 'getExactDuplicatePair').mockResolvedValue(exactDuplicatePair)
  vi.spyOn(invoiceApi, 'getEvidence').mockResolvedValue({
    invoiceId,
    rowVersion: '2',
    fieldEvidence: [],
    itemEvidence: {},
  })
  vi.spyOn(invoiceApi, 'getHistory').mockResolvedValue({ invoiceId, items: [] })
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

async function mountDetail(path: string): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/invoices/:invoiceId', name: 'invoice-detail', component: InvoiceDetailView },
      {
        path: '/invoices/:invoiceId/contract-links',
        name: 'contract-invoice-links',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(InvoiceDetailView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

function mockDuplicateCandidates(
  value: InvoiceDuplicateCandidateListData = readyDuplicateCandidatePage,
): void {
  vi.spyOn(invoiceApi, 'listDuplicateCandidates').mockResolvedValue(value)
}

async function mountList(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/invoices', name: 'invoices', component: InvoiceListView },
      {
        path: '/invoices/:invoiceId',
        name: 'invoice-detail',
        component: { template: '<div />' },
      },
      { path: '/files', name: 'files', component: { template: '<div />' } },
    ],
  })
  await router.push('/invoices')
  await router.isReady()
  wrapper = mount(InvoiceListView, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return wrapper
}

describe('InvoiceApi', () => {
  it('GET 使用 canonical UUID 路径并严格解码 decimal string', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => jsonResponse(rawInvoice))
    const api = new InvoiceApi(new ApiClient({ fetcher }))

    await expect(api.getDetail(invoiceId)).resolves.toEqual(invoice)
    expect(fetcher).toHaveBeenCalledOnce()
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(`/api/v1/invoices/${invoiceId}`)
  })

  it('非 canonical UUID 不发请求', async () => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new InvoiceApi(new ApiClient({ fetcher }))

    await expect(api.getDetail('INVOICE-001')).rejects.toThrow('canonical lowercase UUID')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('严格解码证据与 mutation，并拒绝重复字段证据', () => {
    const evidence = decodeInvoiceEvidenceResponse({
      invoice_id: invoiceId,
      row_version: '2',
      field_evidence: [{ field_code: 'invoice_number', evidence: rawEvidence }],
      item_evidence: { '1': [rawEvidence] },
    })
    expect(evidence).toMatchObject({
      invoiceId,
      rowVersion: '2',
      fieldEvidence: [{ fieldCode: 'invoice_number' }],
    })
    expect(decodeInvoiceMutation({ invoice: rawInvoice, duplicate_candidate_id: null })).toEqual({
      invoice,
      duplicateCandidateId: null,
    })
    expect(() =>
      decodeInvoiceEvidenceResponse({
        invoice_id: invoiceId,
        row_version: '2',
        field_evidence: [
          { field_code: 'invoice_number', evidence: rawEvidence },
          { field_code: 'invoice_number', evidence: rawEvidence },
        ],
        item_evidence: {},
      }),
    ).toThrow(TypeError)
  })

  it('完整事实替换原样携带字段与明细证据', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ invoice: rawInvoice, duplicate_candidate_id: null }),
    )
    const api = new InvoiceApi(new ApiClient({ fetcher }))
    const evidence = {
      blockId,
      parseVersionId,
      pageNo: 1,
      quoteText: '发票号码：66720193',
      bbox: { x: 1, y: 2 },
      confidence: '0.98',
    }
    await api.replaceFacts(
      invoiceId,
      {
        rowVersion: '2',
        reason: '人工复核并完整替换',
        facts: {
          invoiceCode: invoice.invoiceCode,
          invoiceNumber: invoice.invoiceNumber,
          invoiceType: invoice.invoiceType,
          isRedInvoice: invoice.isRedInvoice,
          invoiceDate: invoice.invoiceDate,
          buyerName: invoice.buyerName,
          buyerTaxNo: invoice.buyerTaxNo,
          sellerName: invoice.sellerName,
          sellerTaxNo: invoice.sellerTaxNo,
          amountExcludingTax: invoice.amountExcludingTax,
          taxAmount: invoice.taxAmount,
          totalAmount: invoice.totalAmount,
          currency: invoice.currency,
        },
        fieldEvidence: [{ fieldCode: 'invoice_number', evidence }],
        items: invoice.items.map((item) => ({
          lineNo: item.lineNo,
          itemName: item.itemName,
          specification: item.specification,
          unit: item.unit,
          quantity: item.quantity,
          unitPrice: item.unitPrice,
          amountExcludingTax: item.amountExcludingTax,
          taxRate: item.taxRate,
          taxAmount: item.taxAmount,
          totalAmount: item.totalAmount,
          evidence: [evidence],
        })),
      },
      'invoice-facts.unit-001',
    )
    const body = JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))
    expect(body.field_evidence[0].evidence).toEqual(rawEvidence)
    expect(body.items[0].evidence[0]).toEqual(rawEvidence)
    expect(body.facts.is_red_invoice).toBe(false)
    expect(body.row_version).toBe('2')
  })

  it('确认、查重和重复处置绑定 row_version、候选与幂等键', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ invoice: rawInvoice, duplicate_candidate_id: duplicateCandidateId }),
    )
    const api = new InvoiceApi(new ApiClient({ fetcher }))
    await api.decideDuplicate(
      invoiceId,
      {
        rowVersion: '2',
        candidateId: duplicateCandidateId,
        decision: 'exception_approved',
        reason: '人工确认允许例外',
      },
      'invoice-duplicate.unit-001',
    )
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      row_version: '2',
      candidate_id: duplicateCandidateId,
      decision: 'exception_approved',
      reason: '人工确认允许例外',
    })
    expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'invoice-duplicate.unit-001',
    )
  })

  it.each([
    ['前导零金额', { total_amount: '00.10' }],
    ['浮点金额', { total_amount: 106 }],
    ['不存在的日期', { invoice_date: '2026-02-31' }],
    ['Backend 不支持的公历零年', { invoice_date: '0000-01-01' }],
    ['非大写三字母币种', { currency: 'cny' }],
    ['未知状态', { status: 'active' }],
    ['number 版本值', { row_version: 2 }],
    ['多余字段', { unsupported: true }],
  ])('拒绝%s', (_label, change) => {
    expect(() => decodeInvoiceDetail({ ...rawInvoice, ...change })).toThrow()
  })

  it('接受 Backend date 支持的四位早期公历年份', () => {
    expect(decodeInvoiceDetail({ ...rawInvoice, invoice_date: '0099-01-01' }).invoiceDate).toBe(
      '0099-01-01',
    )
  })

  it('以字符串保留超过 JavaScript 安全整数范围的版本值', () => {
    expect(
      decodeInvoiceDetail({ ...rawInvoice, row_version: '9007199254740993' }).rowVersion,
    ).toBe('9007199254740993')
  })

  it('拒绝重复或非升序的明细事实', () => {
    const second = { ...rawInvoice.items[0], id: '40000000-0000-4000-8000-000000000003' }
    expect(() => decodeInvoiceDetail({ ...rawInvoice, items: [rawInvoice.items[0], second] })).toThrow()
    expect(() =>
      decodeInvoiceDetail({
        ...rawInvoice,
        items: [{ ...rawInvoice.items[0], line_no: 2 }, { ...second, line_no: 1 }],
      }),
    ).toThrow()
  })

  it('列表只发送 page_size/可选 opaque cursor 并严格解码结果', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ items: [rawListItem], page_size: 50, next_cursor: null }),
    )
    const api = new InvoiceApi(new ApiClient({ fetcher }))

    const data = await api.list(50, 'eyJ2IjoxfQ')

    expect(data).toMatchObject({ pageSize: 50, nextCursor: null })
    expect(data.items[0]).toMatchObject({ id: invoiceId, totalAmount: '106.00' })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      '/api/v1/invoices?page_size=50&cursor=eyJ2IjoxfQ',
    )
  })

  it.each([0, 101, 1.5])('拒绝非法 page_size=%s 且不发请求', async (pageSize) => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new InvoiceApi(new ApiClient({ fetcher }))

    await expect(api.list(pageSize)).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
  })

  it.each(['', 'has padding=', '含中文', 'a'.repeat(257)])(
    '拒绝非法 opaque cursor 且不发请求',
    async (cursor) => {
      const fetcher = vi.fn<typeof fetch>()
      const api = new InvoiceApi(new ApiClient({ fetcher }))

      await expect(api.list(20, cursor)).rejects.toThrow('canonical base64url')
      expect(fetcher).not.toHaveBeenCalled()
    },
  )

  it('拒绝多余字段、超量结果和不稳定列表顺序', () => {
    expect(() =>
      decodeInvoiceList({
        items: [rawListItem],
        page_size: 20,
        next_cursor: null,
        total: 1,
      }),
    ).toThrow()
    expect(() =>
      decodeInvoiceList({
        items: [rawListItem, rawListItem],
        page_size: 1,
        next_cursor: 'eyJ2IjoxfQ',
      }),
    ).toThrow()
    expect(() =>
      decodeInvoiceList({
        items: [
          { ...rawListItem, id: '40000000-0000-4000-8000-000000000003', invoice_date: null },
          { ...rawListItem, id: '40000000-0000-4000-8000-000000000004' },
        ],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })

  it.each([
    ['未填满页', [rawListItem]],
    ['空页', []],
  ])('拒绝%s却返回 next_cursor', (_label, items) => {
    expect(() =>
      decodeInvoiceList({
        items,
        page_size: 20,
        next_cursor: 'eyJ2IjoxfQ',
      }),
    ).toThrow('cursor requires a full page')
  })

  it('拒绝响应 page_size 与请求不一致', async () => {
    const api = new InvoiceApi(
      new ApiClient({
        fetcher: async () =>
          jsonResponse({ items: [], page_size: 20, next_cursor: null }),
      }),
    )

    await expect(api.list(50)).rejects.toThrow('page size does not match')
  })

  it('严格解码三种重复候选 basis 状态并保留 archived 候选', () => {
    expect(readyDuplicateCandidatePage).toMatchObject({
      basisStatus: 'ready',
      items: [{ id: duplicateCandidateId }],
      pageSize: 20,
      nextCursor: null,
    })
    expect(
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: [{ ...rawDuplicateCandidate, status: 'archived' }],
        page_size: 20,
        next_cursor: null,
      }).items[0]?.status,
    ).toBe('archived')
    for (const basisStatus of ['incomplete_identity', 'source_voided']) {
      expect(
        decodeInvoiceDuplicateCandidateList({
          basis_status: basisStatus,
          items: [],
          page_size: 20,
          next_cursor: null,
        }).basisStatus,
      ).toBe(basisStatus)
    }
  })

  it('重复候选响应拒绝未知字段、非空 inactive basis、voided、重复和非升序项', () => {
    const largerCandidate = {
      ...rawDuplicateCandidate,
      id: '40000000-0000-4000-8000-000000000022',
    }
    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: [rawDuplicateCandidate],
        page_size: 20,
        next_cursor: null,
        total: 1,
      }),
    ).toThrow()
    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'incomplete_identity',
        items: [rawDuplicateCandidate],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow('empty page')
    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: [{ ...rawDuplicateCandidate, status: 'voided' }],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow('voided')
    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: [largerCandidate, rawDuplicateCandidate],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow('order')
    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: [rawDuplicateCandidate, rawDuplicateCandidate],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow('order')
  })

  it('重复候选请求与响应都严格校验 canonical {id,v} cursor 和页不变量', async () => {
    const fullItems = Array.from({ length: 20 }, (_value, index) => ({
      ...rawDuplicateCandidate,
      id: `40000000-0000-4000-8000-${String(index + 22).padStart(12, '0')}`,
    }))
    const lastId = fullItems.at(-1)!.id
    const nextCursor = encodeIdCursor(lastId)
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        basis_status: 'ready',
        items: fullItems,
        page_size: 20,
        next_cursor: nextCursor,
      }),
    )
    const api = new InvoiceApi(new ApiClient({ fetcher }))

    await expect(api.listDuplicateCandidates(invoiceId, 20, duplicateCandidateCursor)).resolves.toMatchObject({
      basisStatus: 'ready',
      nextCursor,
    })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/invoices/${invoiceId}/duplicate-candidates?page_size=20&cursor=${duplicateCandidateCursor}`,
    )

    const invalidCursors = [
      `${duplicateCandidateCursor}=`,
      encodeCursorText(`{ "id": "${duplicateCandidateId}", "v": 1 }`),
      encodeCursorText(`{"v":1,"id":"${duplicateCandidateId}"}`),
      encodeCursorText(`{"extra":null,"id":"${duplicateCandidateId}","v":1}`),
      encodeCursorText('{"id":"40000000-0000-4000-8000-00000000002A","v":1}'),
    ]
    for (const cursor of invalidCursors) {
      expect(() =>
        decodeInvoiceDuplicateCandidateList({
          basis_status: 'ready',
          items: [],
          page_size: 20,
          next_cursor: cursor,
        }),
      ).toThrow()
      const invalidFetcher = vi.fn<typeof fetch>()
      const invalidApi = new InvoiceApi(new ApiClient({ fetcher: invalidFetcher }))
      await expect(
        invalidApi.listDuplicateCandidates(invoiceId, 20, cursor),
      ).rejects.toThrow('canonical base64url JSON')
      expect(invalidFetcher).not.toHaveBeenCalled()
    }

    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: [rawDuplicateCandidate],
        page_size: 20,
        next_cursor: duplicateCandidateCursor,
      }),
    ).toThrow('page size')
    expect(() =>
      decodeInvoiceDuplicateCandidateList({
        basis_status: 'ready',
        items: fullItems,
        page_size: 20,
        next_cursor: encodeIdCursor(fullItems[18]!.id),
      }),
    ).toThrow('last item')
  })

  it('重复候选 API 拒绝非法输入、响应 page_size 与源发票或 cursor 边界漂移', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        basis_status: 'ready',
        items: [rawDuplicateCandidate],
        page_size: 10,
        next_cursor: null,
      }),
    )
    const api = new InvoiceApi(new ApiClient({ fetcher }))
    await expect(api.listDuplicateCandidates('INV-001')).rejects.toThrow('canonical lowercase UUID')
    await expect(api.listDuplicateCandidates(invoiceId, 0)).rejects.toThrow('page size')
    expect(fetcher).not.toHaveBeenCalled()
    await expect(api.listDuplicateCandidates(invoiceId)).rejects.toThrow('does not match request')

    const sourceApi = new InvoiceApi(
      new ApiClient({
        fetcher: async () =>
          jsonResponse({
            basis_status: 'ready',
            items: [{ ...rawDuplicateCandidate, id: invoiceId }],
            page_size: 20,
            next_cursor: null,
          }),
      }),
    )
    await expect(sourceApi.listDuplicateCandidates(invoiceId)).rejects.toThrow('cursor boundary')

    const afterCursorApi = new InvoiceApi(
      new ApiClient({
        fetcher: async () =>
          jsonResponse({
            basis_status: 'ready',
            items: [{ ...rawDuplicateCandidate, id: '40000000-0000-4000-8000-000000000020' }],
            page_size: 20,
            next_cursor: null,
          }),
      }),
    )
    await expect(
      afterCursorApi.listDuplicateCandidates(invoiceId, 20, duplicateCandidateCursor),
    ).rejects.toThrow('cursor boundary')
  })

  it('严格解码精确重复 pair，并保留 DB 非 NULL 的空串与空白原值', () => {
    expect(exactDuplicatePair).toMatchObject({
      source: { id: invoiceId },
      candidate: { id: duplicateCandidateId },
      exactIdentity: {
        invoiceCode: rawInvoice.invoice_code,
        invoiceNumber: rawInvoice.invoice_number,
        sellerTaxNo: rawInvoice.seller_tax_no,
      },
    })
    expect(
      decodeInvoiceExactDuplicatePair({
        source: { ...rawListItem, invoice_code: '', invoice_number: ' ' },
        candidate: { ...rawDuplicateCandidate, invoice_code: '', invoice_number: ' ' },
        exact_identity: { invoice_code: '', invoice_number: ' ', seller_tax_no: '' },
      }).exactIdentity,
    ).toEqual({ invoiceCode: '', invoiceNumber: ' ', sellerTaxNo: '' })
  })

  it.each([
    ['未知字段', { ...rawExactDuplicatePair, evidence: [] }],
    ['身份字段为 null', { ...rawExactDuplicatePair, exact_identity: { ...rawExactDuplicatePair.exact_identity, seller_tax_no: null } }],
    ['源摘要不匹配', { ...rawExactDuplicatePair, source: { ...rawListItem, invoice_code: 'DRIFT' } }],
    ['候选摘要不匹配', { ...rawExactDuplicatePair, candidate: { ...rawDuplicateCandidate, invoice_number: 'DRIFT' } }],
    ['自比较', { ...rawExactDuplicatePair, candidate: { ...rawDuplicateCandidate, id: invoiceId } }],
    ['源已作废', { ...rawExactDuplicatePair, source: { ...rawListItem, status: 'voided' } }],
    ['候选已作废', { ...rawExactDuplicatePair, candidate: { ...rawDuplicateCandidate, status: 'voided' } }],
  ])('精确重复 pair 拒绝%s', (_label, value) => {
    expect(() => decodeInvoiceExactDuplicatePair(value)).toThrow()
  })

  it('精确重复 pair 使用两个 canonical UUID 的无 query 路径，并绑定响应方向', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => jsonResponse(rawExactDuplicatePair))
    const api = new InvoiceApi(new ApiClient({ fetcher }))

    await expect(api.getExactDuplicatePair(invoiceId, duplicateCandidateId)).resolves.toEqual(
      exactDuplicatePair,
    )
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/invoices/${invoiceId}/duplicate-candidates/${duplicateCandidateId}`,
    )

    const sameIdFetcher = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          code: 'RESOURCE_NOT_FOUND',
          message: 'not found',
          data: null,
          trace_id: '90000000-0000-4000-8000-000000000010',
          timestamp: '2026-08-12T00:00:00Z',
        }),
        { status: 404, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const sameIdApi = new InvoiceApi(new ApiClient({ fetcher: sameIdFetcher }))
    await expect(sameIdApi.getExactDuplicatePair(invoiceId, invoiceId)).rejects.toMatchObject({
      status: 404,
      code: 'RESOURCE_NOT_FOUND',
    })
    expect(String(sameIdFetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/invoices/${invoiceId}/duplicate-candidates/${invoiceId}`,
    )

    const invalidFetcher = vi.fn<typeof fetch>()
    const invalidApi = new InvoiceApi(new ApiClient({ fetcher: invalidFetcher }))
    await expect(invalidApi.getExactDuplicatePair('INV-001', duplicateCandidateId)).rejects.toThrow(
      'canonical lowercase UUIDs',
    )
    await expect(invalidApi.getExactDuplicatePair(invoiceId, '40000000-0000-4000-8000-00000000002A')).rejects.toThrow(
      'canonical lowercase UUIDs',
    )
    expect(invalidFetcher).not.toHaveBeenCalled()

    const reversedApi = new InvoiceApi(
      new ApiClient({
        fetcher: async () =>
          jsonResponse({
            ...rawExactDuplicatePair,
            source: rawDuplicateCandidate,
            candidate: rawListItem,
          }),
      }),
    )
    await expect(reversedApi.getExactDuplicatePair(invoiceId, duplicateCandidateId)).rejects.toThrow(
      'does not match request',
    )
  })
})

describe('InvoiceDetailView', () => {
  it('展示 API 发票字段与明细，不展示旧演示事实', async () => {
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    mockDuplicateCandidates()
    const page = await mountDetail(`/invoices/${invoiceId}`)

    expect(page.get('h1').text()).toContain('增值税电子普通发票 · 66720193')
    expect(page.text()).toContain('销售方公司')
    expect(page.text()).toContain('106.00 CNY')
    expect(page.get(`a[href="/invoices/${invoiceId}/contract-links"]`).text()).toBe(
      '查看当前主合同',
    )
    await page.get('[role="tab"][aria-controls="items-panel"]').trigger('click')
    expect(page.text()).toContain('审计服务')
    expect(page.text()).toContain('发票证据、完整事实修正、确认/拒绝、重复检测与处置、修正历史及合同关联已接入')
    expect(page.get(`a[href="/invoices/${duplicateCandidateId}"]`).text()).toBe('查看')
    expect(page.text()).not.toContain('重复候选、合同候选')
    expect(page.text()).not.toContain('上海云枢科技有限公司')
  })

  it('404 不泄露对象存在性，显示 Trace ID 且可重试', async () => {
    vi.spyOn(invoiceApi, 'getDetail')
      .mockRejectedValueOnce(
        new ApiError({
          code: 'INVOICE_NOT_FOUND',
          message: 'not found',
          status: 404,
          traceId: '90000000-0000-4000-8000-000000000010',
        }),
      )
      .mockResolvedValueOnce(invoice)
    mockDuplicateCandidates()
    const page = await mountDetail(`/invoices/${invoiceId}`)

    expect(page.text()).toContain('发票不存在，或当前账号无权访问。')
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    await page.get('[data-testid="retry-invoice"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('销售方公司')
  })

  it('非 UUID 路由不调用 API', async () => {
    const getDetail = vi.spyOn(invoiceApi, 'getDetail')
    const page = await mountDetail('/invoices/invoice-i001')

    expect(page.text()).toContain('发票标识无效，未向服务器发送请求。')
    expect(getDetail).not.toHaveBeenCalled()
  })

  it('路由切换后忽略不遵守 AbortSignal 的旧响应', async () => {
    const nextInvoiceId = '40000000-0000-4000-8000-000000000004'
    let resolveOld: ((value: InvoiceDetail) => void) | undefined
    vi.spyOn(invoiceApi, 'getDetail').mockImplementation((id) => {
      if (id === invoiceId) {
        return new Promise<InvoiceDetail>((resolve) => {
          resolveOld = resolve
        })
      }
      return Promise.resolve({ ...invoice, id: nextInvoiceId, invoiceNumber: 'NEW-002' })
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/invoices/:invoiceId', name: 'invoice-detail', component: InvoiceDetailView },
        {
          path: '/invoices/:invoiceId/contract-links',
          name: 'contract-invoice-links',
          component: { template: '<div />' },
        },
      ],
    })
    await router.push(`/invoices/${invoiceId}`)
    await router.isReady()
    wrapper = mount(InvoiceDetailView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await router.push(`/invoices/${nextInvoiceId}`)
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-002')
    resolveOld?.(invoice)
    await flushPromises()

    expect(wrapper.text()).toContain('NEW-002')
    expect(wrapper.text()).not.toContain('66720193')
  })

  it('有效 UUID 加载中切到非法路由时退出 loading 并显示本地错误', async () => {
    vi.spyOn(invoiceApi, 'getDetail').mockImplementation(
      () => new Promise<InvoiceDetail>(() => undefined),
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/invoices/:invoiceId', name: 'invoice-detail', component: InvoiceDetailView },
        {
          path: '/invoices/:invoiceId/contract-links',
          name: 'contract-invoice-links',
          component: { template: '<div />' },
        },
      ],
    })
    await router.push(`/invoices/${invoiceId}`)
    await router.isReady()
    wrapper = mount(InvoiceDetailView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('正在加载发票详情…')

    await router.push('/invoices/not-a-uuid')
    await flushPromises()

    expect(wrapper.text()).toContain('发票标识无效，未向服务器发送请求。')
    expect(wrapper.text()).not.toContain('正在加载发票详情…')
  })

  it.each([
    ['ready', '身份字段完整，已执行精确等值查询'],
    ['incomplete_identity', '身份字段不完整，未执行候选查询'],
    ['source_voided', '源发票已作废，未执行候选查询'],
  ] as const)('展示 %s basis 且无写权限时保持只读', async (basisStatus, label) => {
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    mockDuplicateCandidates({
      basisStatus,
      items: basisStatus === 'ready' ? [readyDuplicateCandidatePage.items[0]!] : [],
      pageSize: 20,
      nextCursor: null,
    })
    const page = await mountDetail(`/invoices/${invoiceId}`)

    expect(page.text()).toContain(label)
    expect(page.text()).toContain('当前账号没有发票管理权限')
    expect(page.find('[data-testid="check-invoice-duplicate"]').exists()).toBe(false)
    expect(page.find('[data-testid="confirm-invoice-duplicate"]').exists()).toBe(false)
  })

  it('ready 空页说明边界并支持 cursor 前后翻页', async () => {
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    const cursor = encodeIdCursor(duplicateCandidateId)
    vi.spyOn(invoiceApi, 'listDuplicateCandidates')
      .mockResolvedValueOnce({
        basisStatus: 'ready',
        items: [readyDuplicateCandidatePage.items[0]!],
        pageSize: 20,
        nextCursor: cursor,
      })
      .mockResolvedValueOnce({ basisStatus: 'ready', items: [], pageSize: 20, nextCursor: null })
      .mockResolvedValueOnce(readyDuplicateCandidatePage)
    const page = await mountDetail(`/invoices/${invoiceId}`)

    await page.get('button[aria-label="重复候选下一页"]').trigger('click')
    await flushPromises()
    expect(invoiceApi.listDuplicateCandidates).toHaveBeenNthCalledWith(
      2,
      invoiceId,
      20,
      cursor,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('不等同于税务唯一性、外部真伪或人工确认结论')

    await page.get('button[aria-label="重复候选上一页"]').trigger('click')
    await flushPromises()
    expect(invoiceApi.listDuplicateCandidates).toHaveBeenNthCalledWith(
      3,
      invoiceId,
      20,
      undefined,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('第 1 页 · 每页 20 条')
  })

  it('按候选显式核对 pair，并展示共同三元组与两端只读摘要', async () => {
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    mockDuplicateCandidates()
    const page = await mountDetail(`/invoices/${invoiceId}`)

    expect(invoiceApi.getExactDuplicatePair).not.toHaveBeenCalled()
    await page.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    await flushPromises()

    expect(invoiceApi.getExactDuplicatePair).toHaveBeenCalledWith(
      invoiceId,
      duplicateCandidateId,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('精确重复对比')
    expect(page.text()).toContain('共同发票代码')
    expect(page.text()).toContain(rawInvoice.invoice_code)
    expect(page.text()).toContain('共同销售方税号')
    expect(page.text()).toContain(rawInvoice.seller_tax_no)
    expect(page.text()).toContain('当前发票')
    expect(page.text()).toContain('候选发票')
    expect(page.text()).toContain('不代表税务真伪、人工确认或重复状态已更新')
  })

  it('共同三元组对混合空白、纯空白与空串提供可辨识但不归一化的显示', async () => {
    const rawBlankPair = {
      source: { ...rawListItem, invoice_code: ' INV  CODE ', invoice_number: ' ' },
      candidate: { ...rawDuplicateCandidate, invoice_code: ' INV  CODE ', invoice_number: ' ' },
      exact_identity: { invoice_code: ' INV  CODE ', invoice_number: ' ', seller_tax_no: '' },
    }
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    mockDuplicateCandidates()
    vi.spyOn(invoiceApi, 'getExactDuplicatePair').mockResolvedValue(
      decodeInvoiceExactDuplicatePair(rawBlankPair),
    )
    const page = await mountDetail(`/invoices/${invoiceId}`)

    await page.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    await flushPromises()
    expect(page.text()).toContain('"\\u0020INV\\u0020\\u0020CODE\\u0020"')
    expect(page.text()).toContain('（空字符串）')
    expect(page.text()).toContain('（纯空白，1 个字符）')
  })

  it.each([
    [403, '当前账号无权核对这组精确重复发票。'],
    [404, '这组发票已不存在、不可访问或不再构成精确重复候选。'],
    [500, '精确重复对比加载失败，请稍后重试。'],
  ])('精确重复 pair %i 安全显示 Trace 并按同一对象重试', async (status, expected) => {
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    mockDuplicateCandidates()
    vi.spyOn(invoiceApi, 'getExactDuplicatePair')
      .mockRejectedValueOnce(
        new ApiError({
          code: 'SYNTHETIC',
          message: 'raw backend secret',
          status,
          traceId: '90000000-0000-4000-8000-000000000010',
        }),
      )
      .mockResolvedValueOnce(exactDuplicatePair)
    const page = await mountDetail(`/invoices/${invoiceId}`)

    await page.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    await flushPromises()
    expect(page.text()).toContain(expected)
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    expect(page.text()).not.toContain('raw backend secret')

    await page.get('[data-testid="retry-invoice-duplicate-pair"]').trigger('click')
    await flushPromises()
    expect(invoiceApi.getExactDuplicatePair).toHaveBeenNthCalledWith(
      2,
      invoiceId,
      duplicateCandidateId,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain(rawInvoice.seller_tax_no)
  })

  it('切换候选会中止并忽略不遵守 Abort 的旧 pair 响应', async () => {
    const nextCandidateId = '40000000-0000-4000-8000-000000000022'
    const nextCandidate = { ...readyDuplicateCandidatePage.items[0]!, id: nextCandidateId }
    const nextPair: InvoiceExactDuplicatePairData = {
      ...exactDuplicatePair,
      candidate: { ...exactDuplicatePair.candidate, id: nextCandidateId, sellerName: 'NEW-PAIR' },
    }
    let oldSignal: AbortSignal | undefined
    let resolveOld: ((value: InvoiceExactDuplicatePairData) => void) | undefined
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    mockDuplicateCandidates({
      ...readyDuplicateCandidatePage,
      items: [readyDuplicateCandidatePage.items[0]!, nextCandidate],
    })
    vi.spyOn(invoiceApi, 'getExactDuplicatePair').mockImplementation(
      (_sourceId, candidateId, signal) => {
        if (candidateId === duplicateCandidateId) {
          oldSignal = signal
          return new Promise<InvoiceExactDuplicatePairData>((resolve) => {
            resolveOld = resolve
          })
        }
        return Promise.resolve(nextPair)
      },
    )
    const page = await mountDetail(`/invoices/${invoiceId}`)

    await page.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    await page.get(`[data-testid="compare-invoice-duplicate-${nextCandidateId}"]`).trigger('click')
    await flushPromises()
    resolveOld?.({
      ...exactDuplicatePair,
      candidate: { ...exactDuplicatePair.candidate, sellerName: 'OLD-PAIR' },
    })
    await flushPromises()

    expect(oldSignal?.aborted).toBe(true)
    expect(page.text()).toContain('NEW-PAIR')
    expect(page.text()).not.toContain('OLD-PAIR')
  })

  it('详情路由变化会清理已展示的 pair', async () => {
    const nextInvoiceId = '40000000-0000-4000-8000-000000000004'
    vi.spyOn(invoiceApi, 'getDetail').mockImplementation((id) =>
      Promise.resolve({ ...invoice, id, invoiceNumber: id === invoiceId ? 'OLD-SOURCE' : 'NEW-SOURCE' }),
    )
    mockDuplicateCandidates()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/invoices/:invoiceId', name: 'invoice-detail', component: InvoiceDetailView },
        { path: '/invoices/:invoiceId/contract-links', name: 'contract-invoice-links', component: { template: '<div />' } },
      ],
    })
    await router.push(`/invoices/${invoiceId}`)
    await router.isReady()
    wrapper = mount(InvoiceDetailView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    await wrapper.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('共同销售方税号')

    await router.push(`/invoices/${nextInvoiceId}`)
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-SOURCE')
    expect(wrapper.text()).not.toContain('共同销售方税号')
  })

  it('候选翻页清理 pair，对比请求在卸载时中止', async () => {
    let pairSignal: AbortSignal | undefined
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    vi.spyOn(invoiceApi, 'listDuplicateCandidates')
      .mockResolvedValueOnce({
        ...readyDuplicateCandidatePage,
        nextCursor: duplicateCandidateCursor,
      })
      .mockResolvedValueOnce({ basisStatus: 'ready', items: [], pageSize: 20, nextCursor: null })
    vi.spyOn(invoiceApi, 'getExactDuplicatePair').mockImplementation(
      (_sourceId, _candidateId, signal) => {
        pairSignal = signal
        return new Promise<InvoiceExactDuplicatePairData>(() => undefined)
      },
    )
    const page = await mountDetail(`/invoices/${invoiceId}`)

    await page.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    expect(page.text()).toContain('正在核对精确重复发票对…')
    await page.get('button[aria-label="重复候选下一页"]').trigger('click')
    await flushPromises()
    expect(pairSignal?.aborted).toBe(true)
    expect(page.text()).not.toContain('正在核对精确重复发票对…')

    vi.spyOn(invoiceApi, 'listDuplicateCandidates').mockResolvedValue(readyDuplicateCandidatePage)
    await page.get('button[aria-label="重复候选上一页"]').trigger('click')
    await flushPromises()
    await page.get(`[data-testid="compare-invoice-duplicate-${duplicateCandidateId}"]`).trigger('click')
    page.unmount()
    wrapper = undefined
    expect(pairSignal?.aborted).toBe(true)
  })

  it.each([
    [401, '登录状态已失效，请重新登录。'],
    [403, '当前账号无权读取此发票的精确重复候选。'],
    [404, '发票不存在，或当前账号无权访问其精确重复候选。'],
    [500, '精确重复候选加载失败，请稍后重试。'],
  ])('重复候选 %i 安全显示 Trace 并以同一 cursor 重试', async (status, expected) => {
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    vi.spyOn(invoiceApi, 'listDuplicateCandidates')
      .mockRejectedValueOnce(
        new ApiError({
          code: 'SYNTHETIC',
          message: 'raw backend secret',
          status,
          traceId: '90000000-0000-4000-8000-000000000010',
        }),
      )
      .mockResolvedValueOnce(readyDuplicateCandidatePage)
    const page = await mountDetail(`/invoices/${invoiceId}`)

    expect(page.text()).toContain(expected)
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    expect(page.text()).not.toContain('raw backend secret')
    await page.get('[data-testid="retry-invoice-duplicate-candidates"]').trigger('click')
    await flushPromises()
    expect(invoiceApi.listDuplicateCandidates).toHaveBeenNthCalledWith(
      2,
      invoiceId,
      20,
      undefined,
      expect.any(AbortSignal),
    )
    expect(page.get(`a[href="/invoices/${duplicateCandidateId}"]`).text()).toBe('查看')
  })

  it('详情路由变化中止候选请求并忽略不遵守 Abort 的旧候选响应', async () => {
    const nextInvoiceId = '40000000-0000-4000-8000-000000000004'
    let oldSignal: AbortSignal | undefined
    let resolveOld: ((value: InvoiceDuplicateCandidateListData) => void) | undefined
    vi.spyOn(invoiceApi, 'getDetail').mockImplementation((id) =>
      Promise.resolve({ ...invoice, id, invoiceNumber: id === invoiceId ? 'OLD-SOURCE' : 'NEW-SOURCE' }),
    )
    vi.spyOn(invoiceApi, 'listDuplicateCandidates').mockImplementation(
      (id, _pageSize, _cursor, signal) => {
        if (id === invoiceId) {
          oldSignal = signal
          return new Promise<InvoiceDuplicateCandidateListData>((resolve) => {
            resolveOld = resolve
          })
        }
        return Promise.resolve({
          ...readyDuplicateCandidatePage,
          items: [{
            ...readyDuplicateCandidatePage.items[0]!,
            id: '40000000-0000-4000-8000-000000000023',
            invoiceNumber: '66720193',
            sellerName: 'NEW-CANDIDATE',
          }],
        })
      },
    )
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/invoices/:invoiceId', name: 'invoice-detail', component: InvoiceDetailView },
        { path: '/invoices/:invoiceId/contract-links', name: 'contract-invoice-links', component: { template: '<div />' } },
      ],
    })
    await router.push(`/invoices/${invoiceId}`)
    await router.isReady()
    wrapper = mount(InvoiceDetailView, { global: { plugins: [createPinia(), router] } })
    await flushPromises()

    await router.push(`/invoices/${nextInvoiceId}`)
    await flushPromises()
    resolveOld?.({
      ...readyDuplicateCandidatePage,
      items: [{ ...readyDuplicateCandidatePage.items[0]!, sellerName: 'OLD-CANDIDATE' }],
    })
    await flushPromises()

    expect(oldSignal?.aborted).toBe(true)
    expect(wrapper.text()).toContain('NEW-CANDIDATE')
    expect(wrapper.text()).not.toContain('OLD-CANDIDATE')
  })

  it('卸载时中止详情成功后仍未完成的候选请求', async () => {
    let signal: AbortSignal | undefined
    vi.spyOn(invoiceApi, 'getDetail').mockResolvedValue(invoice)
    vi.spyOn(invoiceApi, 'listDuplicateCandidates').mockImplementation(
      (_id, _pageSize, _cursor, requestSignal) => {
        signal = requestSignal
        return new Promise<InvoiceDuplicateCandidateListData>(() => undefined)
      },
    )
    const page = await mountDetail(`/invoices/${invoiceId}`)
    expect(page.text()).toContain('正在加载精确重复候选…')
    page.unmount()
    wrapper = undefined
    expect(signal?.aborted).toBe(true)
  })
})

describe('InvoiceListView', () => {
  it('展示真实列表字段并以 canonical UUID 链接详情', async () => {
    vi.spyOn(invoiceApi, 'list').mockResolvedValue(invoiceList)
    const page = await mountList()

    expect(page.text()).toContain('66720193')
    expect(page.text()).toContain('销售方公司')
    expect(page.text()).toContain('106.00 CNY')
    expect(page.text()).toContain('第 1 页 · 每页 20 条')
    expect(page.get(`a[href="/invoices/${invoiceId}"]`).text()).toBe('查看')
    expect(page.text()).not.toContain('当前演示数据集')
    expect(page.text()).not.toContain('主合同')
    expect(page.text()).not.toContain('更新时间')
    expect(page.get('a[href="/files"]').text()).toBe('前往文件管理')
  })

  it('使用 opaque cursor 前后翻页并显示末端空页', async () => {
    vi.spyOn(invoiceApi, 'list')
      .mockResolvedValueOnce(invoiceList)
      .mockResolvedValueOnce({ items: [], pageSize: 20, nextCursor: null })
      .mockResolvedValueOnce(invoiceList)
    const page = await mountList()

    await page.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()

    expect(invoiceApi.list).toHaveBeenNthCalledWith(
      2,
      20,
      'eyJ2IjoxfQ',
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('当前页没有发票。')
    expect(page.get('button[aria-label="下一页"]').attributes('disabled')).toBeDefined()

    await page.get('button[aria-label="上一页"]').trigger('click')
    await flushPromises()

    expect(invoiceApi.list).toHaveBeenNthCalledWith(
      3,
      20,
      undefined,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('第 1 页 · 每页 20 条')
    expect(page.text()).toContain('销售方公司')
  })

  it('下一页失败后重试保持同一 opaque cursor', async () => {
    vi.spyOn(invoiceApi, 'list')
      .mockResolvedValueOnce(invoiceList)
      .mockRejectedValueOnce(new Error('synthetic cursor page failure'))
      .mockResolvedValueOnce({ items: [], pageSize: 20, nextCursor: null })
    const page = await mountList()

    await page.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('发票列表加载失败，请稍后重试。')
    await page.get('[data-testid="retry-invoice-list"]').trigger('click')
    await flushPromises()

    expect(invoiceApi.list).toHaveBeenNthCalledWith(
      3,
      20,
      'eyJ2IjoxfQ',
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('第 2 页 · 每页 20 条')
  })

  it('403 安全显示 Trace ID 并允许重试', async () => {
    vi.spyOn(invoiceApi, 'list')
      .mockRejectedValueOnce(
        new ApiError({
          code: 'PERMISSION_DENIED',
          message: 'forbidden',
          status: 403,
          traceId: '90000000-0000-4000-8000-000000000010',
        }),
      )
      .mockResolvedValueOnce(invoiceList)
    const page = await mountList()

    expect(page.text()).toContain('当前账号无权读取发票列表。')
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    await page.get('[data-testid="retry-invoice-list"]').trigger('click')
    await flushPromises()

    expect(page.text()).toContain('销售方公司')
  })

  it('卸载时中止未完成请求', async () => {
    let requestSignal: AbortSignal | undefined
    vi.spyOn(invoiceApi, 'list').mockImplementation((_pageSize, _cursor, signal) => {
      requestSignal = signal
      return new Promise<InvoiceListData>(() => undefined)
    })
    const page = await mountList()

    expect(page.text()).toContain('正在加载发票列表…')
    page.unmount()
    wrapper = undefined

    expect(requestSignal?.aborted).toBe(true)
  })
})
