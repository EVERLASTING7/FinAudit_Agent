import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiClient, ApiError } from '@/services/api'
import {
  ContractApi,
  contractFieldCodes,
  contractApi,
  decodeContractEvidenceResponse,
  decodeContractDetail,
  decodeContractList,
  type ContractDetail,
  type ContractListData,
} from '@/services/contracts'
import { supplementaryAgreementApi } from '@/services/supplementaryAgreements'
import ContractDetailView from '@/views/ContractDetailView.vue'
import ContractListView from '@/views/ContractListView.vue'

const contractId = '30000000-0000-4000-8000-000000000020'
const rawListItem = {
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
const rawDetail = {
  id: contractId,
  contract_no: rawListItem.contract_no,
  name: rawListItem.name,
  party_a_name: '购买方企业',
  party_a_tax_no: 'BUYER-TAX-NO',
  party_b_name: rawListItem.party_b_name,
  party_b_tax_no: 'SELLER-TAX-NO',
  amount: rawListItem.amount,
  currency: rawListItem.currency,
  signed_date: '2025-12-20',
  effective_date: rawListItem.effective_date,
  expiry_date: rawListItem.expiry_date,
  payment_method: 'bank_transfer',
  payment_terms: '验收后 30 日内付款',
  confirmation_status: rawListItem.confirmation_status,
  status: rawListItem.status,
  row_version: '9007199254740993',
}
const detail = decodeContractDetail(rawDetail)
const rawEvidence = {
  contract_id: contractId,
  file_id: '32000000-0000-4000-8000-000000000020',
  row_version: rawDetail.row_version,
  fields: contractFieldCodes.map((fieldCode, index) => ({
    field_code: fieldCode,
    value_type: fieldCode === 'amount' ? 'number' : fieldCode.endsWith('_date') ? 'date' : 'string',
    candidate_value: null,
    confirmed_value: null,
    confirmation_status: 'confirmed',
    evidence: {
      block_id: `34000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      parse_version_id: '33000000-0000-4000-8000-000000000020',
      page_no: 1,
      quote_text: `字段证据 ${index + 1}`,
      bbox: null,
      confidence: '0.98',
    },
  })),
}
const listItems = Array.from({ length: 20 }, (_value, index) => {
  const sequence = 20 - index
  return {
    ...rawListItem,
    id: `30000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
    contract_no: sequence === 20 ? rawListItem.contract_no : `HT-${sequence}`,
  }
})
const listData = decodeContractList({
  items: listItems,
  page_size: 20,
  next_cursor: 'eyJ2IjoxfQ',
})

let wrapper: VueWrapper | undefined

beforeEach(() => {
  vi.spyOn(supplementaryAgreementApi, 'listHeaders').mockResolvedValue({
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(contractApi, 'getEvidence').mockResolvedValue({
    contractId,
    fileId: '32000000-0000-4000-8000-000000000020',
    rowVersion: detail.rowVersion,
    fields: [
      'contract_no', 'name', 'party_a_name', 'party_a_tax_no', 'party_b_name',
      'party_b_tax_no', 'amount', 'currency', 'signed_date', 'effective_date',
      'expiry_date', 'payment_method', 'payment_terms',
    ].map((fieldCode) => ({
      fieldCode,
      valueType: fieldCode === 'amount' ? 'number' : fieldCode.includes('date') ? 'date' : 'string',
      candidateValue: null,
      confirmedValue: null,
      confirmationStatus: 'confirmed',
      evidence: null,
    })) as Awaited<ReturnType<typeof contractApi.getEvidence>>['fields'],
  })
  vi.spyOn(contractApi, 'getHistory').mockResolvedValue({ contractId, items: [] })
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

async function mountList(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/contracts', name: 'contracts', component: ContractListView },
      { path: '/contracts/:contractId', name: 'contract-detail', component: { template: '<div />' } },
      { path: '/files', name: 'files', component: { template: '<div />' } },
    ],
  })
  await router.push('/contracts')
  await router.isReady()
  wrapper = mount(ContractListView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

async function mountDetail(path: string): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/contracts/:contractId', component: ContractDetailView },
      { path: '/contracts/:contractId/primary-invoices', name: 'contract-primary-invoices', component: { template: '<div />' } },
    ],
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(ContractDetailView, { global: { plugins: [router, createPinia()] } })
  await flushPromises()
  return wrapper
}

describe('ContractApi', () => {
  it('请求合同列表和 canonical UUID 详情', async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) =>
      String(input).includes('?')
        ? jsonResponse({ items: [], page_size: 20, next_cursor: null })
        : jsonResponse(rawDetail),
    )
    const api = new ContractApi(new ApiClient({ fetcher }))

    await api.list(20, 'eyJ2IjoxfQ')
    await expect(api.getDetail(contractId)).resolves.toEqual(detail)

    expect(String(fetcher.mock.calls[0]?.[0])).toBe('/api/v1/contracts?page_size=20&cursor=eyJ2IjoxfQ')
    expect(String(fetcher.mock.calls[1]?.[0])).toBe(`/api/v1/contracts/${contractId}`)
  })

  it('严格解码冻结顺序的合同证据，并拒绝乱序字段', () => {
    const decoded = decodeContractEvidenceResponse(rawEvidence)
    expect(decoded.fields.map((field) => field.fieldCode)).toEqual(contractFieldCodes)
    expect(decoded.fields[0]?.evidence?.quoteText).toBe('字段证据 1')
    expect(() =>
      decodeContractEvidenceResponse({ ...rawEvidence, fields: [...rawEvidence.fields].reverse() }),
    ).toThrow('field order')
  })

  it('合同事实替换发送行版本、幂等键和逐字段证据', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => jsonResponse({ contract: rawDetail }))
    const api = new ContractApi(new ApiClient({ fetcher }))
    const decodedEvidence = decodeContractEvidenceResponse(rawEvidence)

    await api.replaceFacts(
      contractId,
      {
        rowVersion: rawDetail.row_version,
        reason: '根据来源证据修正',
        facts: {
          contractNo: rawDetail.contract_no,
          name: rawDetail.name,
          partyAName: rawDetail.party_a_name,
          partyATaxNo: rawDetail.party_a_tax_no,
          partyBName: rawDetail.party_b_name,
          partyBTaxNo: rawDetail.party_b_tax_no,
          amount: rawDetail.amount,
          currency: rawDetail.currency,
          signedDate: rawDetail.signed_date,
          effectiveDate: rawDetail.effective_date,
          expiryDate: rawDetail.expiry_date,
          paymentMethod: rawDetail.payment_method,
          paymentTerms: rawDetail.payment_terms,
        },
        fieldEvidence: decodedEvidence.fields.map((field) => ({
          fieldCode: field.fieldCode,
          evidence: field.evidence!,
        })),
      },
      'contract-write.12345678',
    )

    const request = fetcher.mock.calls[0]
    expect(String(request?.[0])).toBe(`/api/v1/contracts/${contractId}/facts`)
    expect(request?.[1]?.method).toBe('PUT')
    expect(new Headers(request?.[1]?.headers).get('Idempotency-Key')).toBe('contract-write.12345678')
    const body = JSON.parse(String(request?.[1]?.body)) as Record<string, unknown>
    expect(body.row_version).toBe(rawDetail.row_version)
    expect(body.field_evidence).toHaveLength(contractFieldCodes.length)
  })

  it.each([
    ['前导零金额', { amount: '00.10' }],
    ['非法日期', { effective_date: '2026-02-31' }],
    ['非法币种', { currency: 'cny' }],
    ['未知状态', { status: 'confirmed' }],
    ['number row_version', { row_version: 2 }],
    ['多余字段', { extra: true }],
  ])('详情拒绝%s', (_label, change) => {
    expect(() => decodeContractDetail({ ...rawDetail, ...change })).toThrow()
  })

  it('详情接受 nullable currency/amount/date 并保留 BIGINT string', () => {
    const decoded = decodeContractDetail({
      ...rawDetail,
      currency: null,
      amount: null,
      signed_date: null,
    })
    expect(decoded).toMatchObject({ currency: null, amount: null, signedDate: null })
    expect(decoded.rowVersion).toBe('9007199254740993')
  })

  it('拒绝非法分页、cursor、非UUID且不发请求', async () => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new ContractApi(new ApiClient({ fetcher }))

    await expect(api.list(0)).rejects.toThrow()
    await expect(api.list(20, 'bad=cursor')).rejects.toThrow()
    await expect(api.getDetail('CON-001')).rejects.toThrow('canonical lowercase UUID')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('拒绝未满页带cursor、重复ID和不稳定排序', () => {
    expect(() =>
      decodeContractList({ items: [rawListItem], page_size: 20, next_cursor: 'eyJ2IjoxfQ' }),
    ).toThrow()
    expect(() =>
      decodeContractList({ items: [rawListItem, rawListItem], page_size: 20, next_cursor: null }),
    ).toThrow()
    expect(() =>
      decodeContractList({
        items: [
          { ...rawListItem, effective_date: null },
          { ...rawListItem, id: '30000000-0000-4000-8000-000000000019' },
        ],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })
})

describe('ContractListView', () => {
  it('展示真实合同并链接 canonical UUID 详情', async () => {
    vi.spyOn(contractApi, 'list').mockResolvedValue(listData)
    const page = await mountList()

    expect(page.text()).toContain('企业软件服务合同')
    expect(page.text()).toContain('1,200,000.00 CNY')
    expect(page.get(`a[href="/contracts/${contractId}"]`).text()).toBe('查看')
    expect(page.text()).not.toContain('当前演示数据集')
    expect(page.text()).not.toContain('供应商')
    expect(page.text()).not.toContain('更新时间')
  })

  it('cursor前后翻页且错误重试保持cursor', async () => {
    vi.spyOn(contractApi, 'list')
      .mockResolvedValueOnce(listData)
      .mockRejectedValueOnce(new Error('synthetic'))
      .mockResolvedValueOnce({ items: [], pageSize: 20, nextCursor: null })
      .mockResolvedValueOnce(listData)
    const page = await mountList()

    await page.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    await page.get('[data-testid="retry-contract-list"]').trigger('click')
    await flushPromises()
    expect(contractApi.list).toHaveBeenNthCalledWith(3, 20, 'eyJ2IjoxfQ', expect.any(AbortSignal))
    expect(page.text()).toContain('第 2 页')
    await page.get('button[aria-label="上一页"]').trigger('click')
    await flushPromises()
    expect(contractApi.list).toHaveBeenNthCalledWith(4, 20, undefined, expect.any(AbortSignal))
  })

  it('403安全显示Trace并可重试', async () => {
    vi.spyOn(contractApi, 'list')
      .mockRejectedValueOnce(new ApiError({ code: 'DENIED', message: 'raw', status: 403, traceId: '90000000-0000-4000-8000-000000000010' }))
      .mockResolvedValueOnce({ items: [], pageSize: 20, nextCursor: null })
    const page = await mountList()
    expect(page.text()).toContain('当前账号无权读取合同列表。')
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    await page.get('[data-testid="retry-contract-list"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('当前页没有合同。')
  })

  it('卸载时中止未完成列表请求', async () => {
    let signal: AbortSignal | undefined
    vi.spyOn(contractApi, 'list').mockImplementation((_pageSize, _cursor, requestSignal) => {
      signal = requestSignal
      return new Promise<ContractListData>(() => undefined)
    })
    const page = await mountList()
    expect(page.text()).toContain('正在加载合同列表…')
    page.unmount()
    wrapper = undefined
    expect(signal?.aborted).toBe(true)
  })
})

describe('ContractDetailView', () => {
  it('展示真实当前持久化字段且不展示Demo事实', async () => {
    vi.spyOn(contractApi, 'getDetail').mockResolvedValue(detail)
    const page = await mountDetail(`/contracts/${contractId}`)
    expect(page.get('h1').text()).toContain('企业软件服务合同')
    expect(page.text()).toContain('验收后 30 日内付款')
    expect(page.text()).toContain('不是按审核基准日期应用补充协议后的有效字段投影')
    expect(page.text()).toContain('合同字段证据')
    expect(page.text()).not.toContain('活动解析版本')
    expect(page.get(`a[href="/contracts/${contractId}/primary-invoices"]`).text()).toBe('查看当前主合同发票')
    expect(page.get('[data-testid="open-contract-editor"]').attributes('disabled')).toBeUndefined()
    expect(page.text()).toContain('当前账号没有合同管理权限')
  })

  it('非法UUID不发请求，404安全显示Trace并可重试', async () => {
    const getDetail = vi.spyOn(contractApi, 'getDetail')
    let page = await mountDetail('/contracts/CON-001')
    expect(page.text()).toContain('合同标识无效，未向服务器发送请求。')
    expect(getDetail).not.toHaveBeenCalled()
    page.unmount()
    wrapper = undefined

    getDetail
      .mockRejectedValueOnce(new ApiError({ code: 'NOT_FOUND', message: 'raw', status: 404, traceId: '90000000-0000-4000-8000-000000000010' }))
      .mockResolvedValueOnce(detail)
    page = await mountDetail(`/contracts/${contractId}`)
    expect(page.text()).toContain('合同不存在，或当前账号无权访问。')
    expect(page.text()).toContain('90000000-0000-4000-8000-000000000010')
    await page.get('[data-testid="retry-contract"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('验收后 30 日内付款')
  })

  it('路由切换忽略迟到旧响应', async () => {
    const nextId = '30000000-0000-4000-8000-000000000021'
    let resolveOld: ((value: ContractDetail) => void) | undefined
    vi.spyOn(contractApi, 'getDetail').mockImplementation((id) =>
      id === contractId
        ? new Promise<ContractDetail>((resolve) => { resolveOld = resolve })
        : Promise.resolve({ ...detail, id: nextId, name: '新合同' }),
    )
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/contracts/:contractId', component: ContractDetailView },
      { path: '/contracts/:contractId/primary-invoices', name: 'contract-primary-invoices', component: { template: '<div />' } },
    ] })
    await router.push(`/contracts/${contractId}`)
    await router.isReady()
    wrapper = mount(ContractDetailView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    await router.push(`/contracts/${nextId}`)
    await flushPromises()
    resolveOld?.(detail)
    await flushPromises()
    expect(wrapper.text()).toContain('新合同')
    expect(wrapper.text()).not.toContain('企业软件服务合同')
  })
})
