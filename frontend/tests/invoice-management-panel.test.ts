import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import InvoiceManagementPanel from '@/components/InvoiceManagementPanel.vue'
import { ApiError } from '@/services/api'
import {
  invoiceApi,
  type InvoiceDetail,
  type InvoiceEvidence,
  type InvoiceEvidenceResponseData,
} from '@/services/invoices'
import { useAuthStore } from '@/stores/auth'

const invoiceId = '40000000-0000-4000-8000-000000000001'
const candidateId = '40000000-0000-4000-8000-000000000021'
const evidenceItem: InvoiceEvidence = {
  blockId: '42000000-0000-4000-8000-000000000001',
  parseVersionId: '42000000-0000-4000-8000-000000000002',
  pageNo: 1,
  quoteText: '发票号码：66720193',
  bbox: { x: 1, y: 2 },
  confidence: '0.98',
}
const draftInvoice: InvoiceDetail = {
  id: invoiceId,
  invoiceCode: '031002600311',
  invoiceNumber: '66720193',
  invoiceType: '增值税电子普通发票',
  isRedInvoice: false,
  invoiceDate: '2026-07-31',
  buyerName: '购买方公司',
  buyerTaxNo: 'BUYER-TAX-NO',
  sellerName: '销售方公司',
  sellerTaxNo: 'SELLER-TAX-NO',
  amountExcludingTax: '100.00',
  taxAmount: '6.00',
  totalAmount: '106.00',
  currency: 'CNY',
  confirmationStatus: 'unconfirmed',
  duplicateStatus: 'suspected',
  status: 'draft',
  rowVersion: '2',
  items: [
    {
      id: '40000000-0000-4000-8000-000000000002',
      lineNo: 1,
      itemName: '审计服务',
      specification: null,
      unit: '项',
      quantity: '1',
      unitPrice: '100.00',
      amountExcludingTax: '100.00',
      taxRate: '0.06',
      taxAmount: '6.00',
      totalAmount: '106.00',
      rowVersion: '1',
    },
  ],
}
const evidence: InvoiceEvidenceResponseData = {
  invoiceId,
  rowVersion: '2',
  fieldEvidence: [{ fieldCode: 'invoice_number', evidence: evidenceItem }],
  itemEvidence: { '1': [evidenceItem] },
}
let wrapper: VueWrapper | undefined

function mountPanel(canManage = true): VueWrapper {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).setAuthenticatedSession(
    {
      id: '90000000-0000-4000-8000-000000000001',
      displayName: '发票复核用户',
      roles: ['finance_reviewer'],
      permissions: canManage ? ['financial.read', 'invoices.manage'] : ['financial.read'],
    },
    'test-token',
  )
  wrapper = mount(InvoiceManagementPanel, {
    props: { invoice: draftInvoice, duplicateCandidateIds: [candidateId] },
    global: { plugins: [pinia] },
  })
  return wrapper
}

beforeEach(() => {
  vi.spyOn(invoiceApi, 'getEvidence').mockResolvedValue(evidence)
  vi.spyOn(invoiceApi, 'getHistory').mockResolvedValue({ invoiceId, items: [] })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('发票管理面板', () => {
  it('无发票管理权限时只读取证据和历史，不渲染写按钮', async () => {
    const page = mountPanel(false)
    await flushPromises()

    expect(page.text()).toContain('当前账号没有发票管理权限')
    expect(page.find('[data-testid="confirm-invoice"]').exists()).toBe(false)
    expect(invoiceApi.getEvidence).toHaveBeenCalledWith(invoiceId, expect.any(AbortSignal))
  })

  it('未知失败后以相同幂等键重试确认，并发出新版本结果', async () => {
    const confirmed = {
      ...draftInvoice,
      confirmationStatus: 'confirmed' as const,
      status: 'confirmed' as const,
      rowVersion: '3',
    }
    const decide = vi
      .spyOn(invoiceApi, 'decide')
      .mockRejectedValueOnce(
        new ApiError({ code: 'NETWORK_ERROR', message: 'raw', status: 0, traceId: '' }),
      )
      .mockResolvedValueOnce({ invoice: confirmed, duplicateCandidateId: null })
    const page = mountPanel()
    await flushPromises()
    await page.get('#invoice-write-reason').setValue('字段与证据复核一致')

    await page.get('[data-testid="confirm-invoice"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('发票操作失败')

    await page.get('[data-testid="confirm-invoice"]').trigger('click')
    await flushPromises()
    expect(decide).toHaveBeenCalledTimes(2)
    expect(decide.mock.calls[1]?.[2]).toBe(decide.mock.calls[0]?.[2])
    expect(page.emitted('updated')?.[0]?.[0]).toMatchObject({ invoice: { rowVersion: '3' } })
  })

  it('完整事实修正保留当前字段证据和明细证据', async () => {
    const replaceFacts = vi.spyOn(invoiceApi, 'replaceFacts').mockResolvedValue({
      invoice: { ...draftInvoice, invoiceNumber: '66720194', rowVersion: '3' },
      duplicateCandidateId: null,
    })
    const page = mountPanel()
    await flushPromises()
    await page.get('#invoice-write-reason').setValue('根据原文修正号码')
    await page.get('button').trigger('click')
    await page.get('#edit-invoice-number').setValue('66720194')
    await page.get('[data-testid="replace-invoice-facts"]').trigger('click')
    await flushPromises()

    const input = replaceFacts.mock.calls[0]?.[1]
    expect(input?.facts.invoiceNumber).toBe('66720194')
    expect(input?.facts.isRedInvoice).toBe(false)
    expect(input?.fieldEvidence).toEqual(evidence.fieldEvidence)
    expect(input?.items[0]?.evidence).toEqual([evidenceItem])
  })

  it('重复处置绑定当前候选和当前发票行版本', async () => {
    const decideDuplicate = vi.spyOn(invoiceApi, 'decideDuplicate').mockResolvedValue({
      invoice: { ...draftInvoice, duplicateStatus: 'confirmed_duplicate', rowVersion: '3' },
      duplicateCandidateId: candidateId,
    })
    const page = mountPanel()
    await flushPromises()
    await page.get('#invoice-write-reason').setValue('人工核对确认同一发票')
    await page.get('[data-testid="confirm-invoice-duplicate"]').trigger('click')
    await flushPromises()

    expect(decideDuplicate.mock.calls[0]?.[1]).toEqual({
      rowVersion: '2',
      candidateId,
      decision: 'confirmed_duplicate',
      reason: '人工核对确认同一发票',
    })
  })
})
