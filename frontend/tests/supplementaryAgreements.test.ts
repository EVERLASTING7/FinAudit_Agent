import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { ApiClient, ApiError } from '@/services/api'
import { contractApi, decodeContractDetail, type ContractDetail } from '@/services/contracts'
import {
  SupplementaryAgreementApi,
  decodeEffectiveContractData,
  decodeSupplementaryAgreementDetail,
  decodeSupplementaryAgreementHeaderList,
  supplementaryAgreementApi,
  type SupplementaryAgreementHeaderListData,
} from '@/services/supplementaryAgreements'
import ContractDetailView from '@/views/ContractDetailView.vue'

const contractId = '30000000-0000-4000-8000-000000000020'
const nextContractId = '30000000-0000-4000-8000-000000000021'
const traceId = '90000000-0000-4000-8000-000000000010'
const rawDetail = {
  id: contractId,
  contract_no: 'HT-2026-0020',
  name: '企业软件服务合同',
  party_a_name: '购买方企业',
  party_a_tax_no: 'BUYER-TAX-NO',
  party_b_name: '服务供应方',
  party_b_tax_no: 'SELLER-TAX-NO',
  amount: '1200000.00',
  currency: 'CNY',
  signed_date: '2025-12-20',
  effective_date: '2026-01-01',
  expiry_date: '2026-12-31',
  payment_method: 'bank_transfer',
  payment_terms: '验收后 30 日内付款',
  confirmation_status: 'confirmed',
  status: 'active',
  row_version: '8',
}
const detail = decodeContractDetail(rawDetail)
const rawHeader = {
  id: '31000000-0000-4000-8000-000000000020',
  agreement_no: 'BC-2026-0020',
  name: '服务范围补充协议',
  signed_date: '2026-02-10',
  effective_date: '2026-02-15',
  status: 'pending_confirmation',
  confirmation_status: 'unconfirmed',
}
const agreementId = rawHeader.id
const changeId = '32000000-0000-4000-8000-000000000020'
const evidenceBlockId = '33000000-0000-4000-8000-000000000020'
const rawAgreementDetail = {
  ...rawHeader,
  contract_id: contractId,
  changes: [
    {
      id: changeId,
      field_code: 'amount',
      value_type: 'number',
      old_value: '1200000.00',
      new_value: '1250000.00',
      evidence_block_id: evidenceBlockId,
      page_no: 2,
      quote_text: '合同总金额调整为 1,250,000.00 元',
      bbox: { x: 12, y: 24 },
      confirmation_status: 'unconfirmed',
    },
  ],
  row_version: '2',
}
const agreementDetail = decodeSupplementaryAgreementDetail(rawAgreementDetail)
const confirmedAgreementDetail = decodeSupplementaryAgreementDetail({
  ...rawAgreementDetail,
  status: 'confirmed',
  confirmation_status: 'confirmed',
  changes: rawAgreementDetail.changes.map((change) => ({
    ...change,
    confirmation_status: 'confirmed',
  })),
  row_version: '3',
})
const rawEffectiveContract = {
  id: contractId,
  baseline_date: '2026-03-01',
  confirmation_status: 'confirmed',
  fields: [
    {
      field_code: 'amount',
      value_type: 'number',
      original_value: '1200000.00',
      effective_value: '1250000.00',
      source_agreement_id: agreementId,
      source_effective_date: '2026-02-15',
    },
  ],
  applied_agreement_ids: [agreementId],
  row_version: '8',
}
const effectiveContract = decodeEffectiveContractData(rawEffectiveContract)
const firstPage = decodeSupplementaryAgreementHeaderList({
  items: Array.from({ length: 20 }, (_value, index) => ({
    ...rawHeader,
    id: `31000000-0000-4000-8000-${String(20 - index).padStart(12, '0')}`,
  })),
  page_size: 20,
  next_cursor: 'eyJ2IjoxfQ',
})
const oneHeaderPage = decodeSupplementaryAgreementHeaderList({
  items: [rawHeader],
  page_size: 20,
  next_cursor: null,
})
const emptyPage: SupplementaryAgreementHeaderListData = {
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

async function mountPage(path = `/contracts/${contractId}`): Promise<{
  page: VueWrapper
  router: Router
}> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/contracts/:contractId', component: ContractDetailView },
      { path: '/contracts/:contractId/primary-invoices', name: 'contract-primary-invoices', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(ContractDetailView, {
    global: {
      plugins: [router, createPinia()],
      stubs: { ContractManagementPanel: true },
    },
  })
  await flushPromises()
  return { page: wrapper, router }
}

describe('SupplementaryAgreementApi', () => {
  it('只请求合同范围 Header，并严格解码 nullable 字段', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        items: [{ ...rawHeader, agreement_no: null, signed_date: null }],
        page_size: 20,
        next_cursor: null,
      }),
    )
    const api = new SupplementaryAgreementApi(new ApiClient({ fetcher }))

    await expect(api.listHeaders(contractId, 20, 'eyJ2IjoxfQ')).resolves.toMatchObject({
      items: [{ agreementNo: null, signedDate: null }],
      pageSize: 20,
      nextCursor: null,
    })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/contracts/${contractId}/supplementary-agreements?page_size=20&cursor=eyJ2IjoxfQ`,
    )
  })

  it.each([
    ['非法 UUID', { id: 'SA-001' }],
    ['非法日历日期', { effective_date: '2026-02-31' }],
    ['未知业务状态', { status: 'active' }],
    ['未知确认状态', { confirmation_status: 'pending' }],
    ['额外 row_version', { row_version: '1' }],
    ['额外字段变更', { field_changes: [] }],
    ['额外生效推导', { is_effective: true }],
  ])('拒绝 Header 的%s', (_label, change) => {
    expect(() =>
      decodeSupplementaryAgreementHeaderList({
        items: [{ ...rawHeader, ...change }],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })

  it('拒绝短页或空页带 cursor、重复 id 及乱序', () => {
    expect(() =>
      decodeSupplementaryAgreementHeaderList({
        items: [rawHeader],
        page_size: 20,
        next_cursor: 'eyJ2IjoxfQ',
      }),
    ).toThrow()
    expect(() =>
      decodeSupplementaryAgreementHeaderList({
        items: [],
        page_size: 20,
        next_cursor: 'eyJ2IjoxfQ',
      }),
    ).toThrow()
    expect(() =>
      decodeSupplementaryAgreementHeaderList({
        items: [rawHeader, rawHeader],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
    expect(() =>
      decodeSupplementaryAgreementHeaderList({
        items: [
          rawHeader,
          {
            ...rawHeader,
            id: '31000000-0000-4000-8000-000000000019',
            effective_date: '2026-03-01',
          },
        ],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
    expect(() =>
      decodeSupplementaryAgreementHeaderList({
        items: [
          { ...rawHeader, id: '31000000-0000-4000-8000-000000000019' },
          rawHeader,
        ],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })

  it('非法 path、page_size、cursor 与响应 page_size 不发出或不接受请求', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ items: [], page_size: 10, next_cursor: null }),
    )
    const api = new SupplementaryAgreementApi(new ApiClient({ fetcher }))

    await expect(api.listHeaders('CON-001')).rejects.toThrow('canonical lowercase UUID')
    await expect(api.listHeaders(contractId, 0)).rejects.toThrow()
    await expect(api.listHeaders(contractId, 20, 'bad=cursor')).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
    await expect(api.listHeaders(contractId, 20)).rejects.toThrow('does not match request')
  })

  it('按冻结路由读取详情、替换变更、执行决定并读取基准日期投影', async () => {
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input)
      if (path.endsWith('/decision') && init?.method === 'POST') {
        return jsonResponse({
          ...rawAgreementDetail,
          status: 'confirmed',
          confirmation_status: 'confirmed',
          changes: rawAgreementDetail.changes.map((change) => ({
            ...change,
            confirmation_status: 'confirmed',
          })),
          row_version: '3',
        })
      }
      if (path.includes('/effective-fields?')) return jsonResponse(rawEffectiveContract)
      return jsonResponse(rawAgreementDetail)
    })
    const api = new SupplementaryAgreementApi(new ApiClient({ fetcher }))
    const change = {
      fieldCode: 'amount',
      valueType: 'number' as const,
      newValue: '1250000.00',
      evidenceBlockId,
      pageNo: 2,
      quoteText: '合同总金额调整为 1,250,000.00 元',
      bbox: { x: 12, y: 24 },
    }

    await expect(api.getDetail(contractId, agreementId)).resolves.toEqual(agreementDetail)
    await api.replaceChanges(
      contractId,
      agreementId,
      { rowVersion: '2', reason: '按补充协议原文修正金额', changes: [change] },
      'supplementary.replace.12345678',
    )
    await expect(
      api.decide(
        contractId,
        agreementId,
        { rowVersion: '2', decision: 'confirmed', reason: '来源证据已逐项复核' },
        'supplementary.decision.12345678',
      ),
    ).resolves.toEqual(confirmedAgreementDetail)
    await expect(api.getEffectiveFields(contractId, '2026-03-01')).resolves.toEqual(
      effectiveContract,
    )

    expect(fetcher.mock.calls.map((call) => String(call[0]))).toEqual([
      `/api/v1/contracts/${contractId}/supplementary-agreements/${agreementId}`,
      `/api/v1/contracts/${contractId}/supplementary-agreements/${agreementId}/changes`,
      `/api/v1/contracts/${contractId}/supplementary-agreements/${agreementId}/decision`,
      `/api/v1/contracts/${contractId}/effective-fields?baseline_date=2026-03-01`,
    ])
    expect(fetcher.mock.calls.map((call) => call[1]?.method)).toEqual([
      'GET',
      'PUT',
      'POST',
      'GET',
    ])
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      row_version: '2',
      reason: '按补充协议原文修正金额',
      changes: [
        {
          field_code: 'amount',
          value_type: 'number',
          new_value: '1250000.00',
          evidence_block_id: evidenceBlockId,
          page_no: 2,
          quote_text: '合同总金额调整为 1,250,000.00 元',
          bbox: { x: 12, y: 24 },
        },
      ],
    })
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({
      row_version: '2',
      decision: 'confirmed',
      reason: '来源证据已逐项复核',
    })
    expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'supplementary.replace.12345678',
    )
    expect(new Headers(fetcher.mock.calls[2]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'supplementary.decision.12345678',
    )
  })

  it('严格拒绝类型、排序、来源配对与证据矩阵不合法的响应', () => {
    expect(() =>
      decodeSupplementaryAgreementDetail({
        ...rawAgreementDetail,
        changes: [
          { ...rawAgreementDetail.changes[0], field_code: 'name' },
          { ...rawAgreementDetail.changes[0], id: '32000000-0000-4000-8000-000000000021' },
        ],
      }),
    ).toThrow('unique and sorted')
    expect(() =>
      decodeSupplementaryAgreementDetail({
        ...rawAgreementDetail,
        changes: [
          {
            ...rawAgreementDetail.changes[0],
            evidence_block_id: null,
            page_no: null,
            quote_text: null,
          },
        ],
      }),
    ).toThrow('evidence')
    expect(() =>
      decodeSupplementaryAgreementDetail({
        ...rawAgreementDetail,
        changes: [{ ...rawAgreementDetail.changes[0], new_value: 1250000 }],
      }),
    ).toThrow('change')
    expect(() =>
      decodeEffectiveContractData({
        ...rawEffectiveContract,
        fields: [
          {
            ...rawEffectiveContract.fields[0],
            source_effective_date: null,
          },
        ],
      }),
    ).toThrow('field')
    expect(() =>
      decodeEffectiveContractData({
        ...rawEffectiveContract,
        applied_agreement_ids: [agreementId, agreementId],
      }),
    ).toThrow('applied')
  })

  it('请求前拒绝 bbox 孤立、非法日期，并拒绝响应身份漂移', async () => {
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ ...rawAgreementDetail, contract_id: nextContractId }),
    )
    const api = new SupplementaryAgreementApi(new ApiClient({ fetcher }))

    await expect(
      api.replaceChanges(
        contractId,
        agreementId,
        {
          rowVersion: '2',
          reason: '尝试提交孤立坐标',
          changes: [
            {
              fieldCode: 'amount',
              valueType: 'number',
              newValue: '1250000.00',
              evidenceBlockId: null,
              pageNo: null,
              quoteText: null,
              bbox: { x: 1 },
            },
          ],
        },
        'supplementary.replace.12345678',
      ),
    ).rejects.toThrow('bbox requires complete evidence')
    await expect(api.getEffectiveFields(contractId, '2026-02-31')).rejects.toThrow('calendar date')
    expect(fetcher).not.toHaveBeenCalled()

    await expect(api.getDetail(contractId, agreementId)).rejects.toThrow('identity mismatch')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

describe('ContractDetailView 补充协议原始 Header', () => {
  it('合同成功后独立加载 7 字段原始 Header 与字段操作入口', async () => {
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockResolvedValue(oneHeaderPage)

    const { page } = await mountPage()

    expect(supplementaryAgreementApi.listHeaders).toHaveBeenCalledWith(
      contractId,
      20,
      undefined,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('补充协议原始 Header')
    expect(page.text()).toContain('BC-2026-0020')
    expect(page.text()).toContain('服务范围补充协议')
    expect(page.text()).toContain('两个状态独立原样展示')
    expect(page.text()).not.toContain('is_effective')
    expect(page.text()).not.toContain('字段变更明细')
    expect(page.text()).not.toContain('新增补充协议')
  })

  it('展示独立空态且不把原始 Header 宣称为有效字段投影', async () => {
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockResolvedValue(emptyPage)

    const { page } = await mountPage()

    expect(page.text()).toContain('当前合同没有补充协议原始 Header。')
    expect(page.text()).toContain('基准日期有效字段')
  })

  it('从 Header 打开字段级详情，并按基准日期读取有效字段来源', async () => {
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockResolvedValue(oneHeaderPage)
    const getDetail = vi.spyOn(supplementaryAgreementApi, 'getDetail').mockResolvedValue(agreementDetail)
    const getEffectiveFields = vi
      .spyOn(supplementaryAgreementApi, 'getEffectiveFields')
      .mockResolvedValue(effectiveContract)

    const { page } = await mountPage()
    await page.get(`[data-testid="open-supplementary-${agreementId}"]`).trigger('click')
    await flushPromises()

    expect(getDetail).toHaveBeenCalledWith(contractId, agreementId, expect.any(AbortSignal))
    expect(page.text()).toContain('补充协议字段级详情')
    expect(page.text()).toContain('合同总金额调整为 1,250,000.00 元')

    await page.get('#effective-baseline-date').setValue('2026-03-01')
    await page.get('form.filter-bar').trigger('submit')
    await flushPromises()

    expect(getEffectiveFields).toHaveBeenCalledWith(
      contractId,
      '2026-03-01',
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('1250000.00')
    expect(page.text()).toContain(agreementId)
  })

  it('cursor 翻页失败后的重试保持 cursor，并可返回上一页', async () => {
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    vi.spyOn(supplementaryAgreementApi, 'listHeaders')
      .mockResolvedValueOnce(firstPage)
      .mockRejectedValueOnce(new Error('synthetic raw error'))
      .mockResolvedValueOnce(emptyPage)
      .mockResolvedValueOnce(firstPage)

    const { page } = await mountPage()
    await page.get('button[aria-label="补充协议下一页"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('补充协议原始 Header 加载失败，请稍后重试。')
    expect(page.text()).not.toContain('synthetic raw error')

    await page.get('[data-testid="retry-supplementary-agreements"]').trigger('click')
    await flushPromises()
    expect(supplementaryAgreementApi.listHeaders).toHaveBeenNthCalledWith(
      3,
      contractId,
      20,
      'eyJ2IjoxfQ',
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('第 2 页')

    await page.get('button[aria-label="补充协议上一页"]').trigger('click')
    await flushPromises()
    expect(supplementaryAgreementApi.listHeaders).toHaveBeenNthCalledWith(
      4,
      contractId,
      20,
      undefined,
      expect.any(AbortSignal),
    )
  })

  it.each([
    [401, '登录状态已失效，请重新登录。'],
    [403, '当前账号无权读取补充协议原始 Header。'],
    [404, '合同不存在，或当前账号无权访问其补充协议原始 Header。'],
    [500, '补充协议原始 Header 加载失败，请稍后重试。'],
  ])('%i 错误安全展示且保留合同和 Trace', async (status, message) => {
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockRejectedValue(
      new ApiError({ code: 'SYNTHETIC', message: 'raw backend secret', status, traceId }),
    )

    const { page } = await mountPage()

    expect(page.text()).toContain('企业软件服务合同')
    expect(page.text()).toContain(message)
    expect(page.text()).toContain(traceId)
    expect(page.text()).not.toContain('raw backend secret')
  })

  it('路由切换中止旧请求并忽略无视 Abort 的迟到 Header', async () => {
    let oldSignal: AbortSignal | undefined
    let resolveOld: ((value: SupplementaryAgreementHeaderListData) => void) | undefined
    vi.spyOn(contractApi, 'getDetail').mockImplementation((id) =>
      Promise.resolve(
        id === contractId
          ? detail
          : ({ ...detail, id: nextContractId, name: '新合同' } satisfies ContractDetail),
      ),
    )
    vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockImplementation(
      (id, _pageSize, _cursor, signal) => {
        if (id === contractId) {
          oldSignal = signal
          return new Promise<SupplementaryAgreementHeaderListData>((resolve) => {
            resolveOld = resolve
          })
        }
        return Promise.resolve({
          ...oneHeaderPage,
          items: [{ ...oneHeaderPage.items[0]!, id: '31000000-0000-4000-8000-000000000021', name: '新合同补充协议' }],
        })
      },
    )

    const { page, router } = await mountPage()
    await router.push(`/contracts/${nextContractId}`)
    await flushPromises()
    resolveOld?.(oneHeaderPage)
    await flushPromises()

    expect(oldSignal?.aborted).toBe(true)
    expect(page.text()).toContain('新合同补充协议')
    expect(page.text()).not.toContain('服务范围补充协议')
  })

  it('有效路由切到非法标识时中止 Header，清除 loading 且不发送新请求', async () => {
    let signal: AbortSignal | undefined
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    const listHeaders = vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockImplementation(
      (_id, _pageSize, _cursor, requestSignal) => {
        signal = requestSignal
        return new Promise<SupplementaryAgreementHeaderListData>(() => undefined)
      },
    )

    const { page, router } = await mountPage()
    expect(page.text()).toContain('正在加载补充协议原始 Header…')
    await router.push('/contracts/CON-001')
    await flushPromises()

    expect(signal?.aborted).toBe(true)
    expect(page.text()).toContain('合同标识无效，未向服务器发送请求。')
    expect(page.text()).not.toContain('正在加载补充协议原始 Header…')
    expect(listHeaders).toHaveBeenCalledTimes(1)
  })

  it('卸载页面时中止未完成的 Header 请求', async () => {
    let signal: AbortSignal | undefined
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockImplementation(
      (_id, _pageSize, _cursor, requestSignal) => {
        signal = requestSignal
        return new Promise<SupplementaryAgreementHeaderListData>(() => undefined)
      },
    )

    const { page } = await mountPage()
    page.unmount()
    wrapper = undefined
    expect(signal?.aborted).toBe(true)
  })
})
