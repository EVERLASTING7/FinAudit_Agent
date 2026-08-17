import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ContractManagementPanel from '@/components/ContractManagementPanel.vue'
import { ApiError } from '@/services/api'
import {
  contractApi,
  contractFieldCodes,
  type ContractDetail,
  type ContractEvidence,
  type ContractEvidenceResponseData,
} from '@/services/contracts'
import { useAuthStore } from '@/stores/auth'

const contractId = '30000000-0000-4000-8000-000000000020'
const fileId = '32000000-0000-4000-8000-000000000020'
const parseVersionId = '33000000-0000-4000-8000-000000000020'
const draftContract: ContractDetail = {
  id: contractId,
  contractNo: 'HT-2026-0020',
  name: '企业软件服务合同',
  partyAName: '购买方企业',
  partyATaxNo: 'BUYER-TAX-NO',
  partyBName: '服务供应方',
  partyBTaxNo: 'SELLER-TAX-NO',
  amount: '1200000.00',
  currency: 'CNY',
  signedDate: '2025-12-20',
  effectiveDate: '2026-01-01',
  expiryDate: '2026-12-31',
  paymentMethod: 'bank_transfer',
  paymentTerms: '验收后 30 日内付款',
  confirmationStatus: 'unconfirmed',
  status: 'draft',
  rowVersion: '2',
}

function sourceEvidence(index: number): ContractEvidence {
  return {
    blockId: `34000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
    parseVersionId,
    pageNo: 1,
    quoteText: `字段证据 ${index + 1}`,
    bbox: null,
    confidence: '0.98',
  }
}

const evidence: ContractEvidenceResponseData = {
  contractId,
  fileId,
  rowVersion: '2',
  fields: contractFieldCodes.map((fieldCode, index) => ({
    fieldCode,
    valueType: fieldCode === 'amount' ? 'number' : fieldCode.endsWith('_date') ? 'date' : 'string',
    candidateValue: 'candidate',
    confirmedValue: null,
    confirmationStatus: 'unconfirmed',
    evidence: sourceEvidence(index),
  })),
}

let wrapper: VueWrapper | undefined

function mountPanel(canManage = true, source = evidence): VueWrapper {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).setAuthenticatedSession(
    {
      id: '90000000-0000-4000-8000-000000000001',
      displayName: '合同复核用户',
      roles: ['contract_admin'],
      permissions: canManage ? ['financial.read', 'contracts.manage'] : ['financial.read'],
    },
    'test-token',
  )
  vi.mocked(contractApi.getEvidence).mockResolvedValue(source)
  wrapper = mount(ContractManagementPanel, {
    props: { contract: draftContract },
    global: { plugins: [pinia] },
  })
  return wrapper
}

beforeEach(() => {
  vi.spyOn(contractApi, 'getEvidence').mockResolvedValue(evidence)
  vi.spyOn(contractApi, 'getHistory').mockResolvedValue({ contractId, items: [] })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('合同管理面板', () => {
  it('无合同管理权限时只读取证据和历史，不渲染写按钮', async () => {
    const page = mountPanel(false)
    await flushPromises()

    expect(page.text()).toContain('当前账号没有合同管理权限')
    expect(page.find('[data-testid="confirm-contract"]').exists()).toBe(false)
    expect(contractApi.getEvidence).toHaveBeenCalledWith(contractId, expect.any(AbortSignal))
  })

  it('未知失败后以相同幂等键重试确认，并发出新版本结果', async () => {
    const confirmed: ContractDetail = {
      ...draftContract,
      confirmationStatus: 'confirmed',
      status: 'active',
      rowVersion: '3',
    }
    const decide = vi
      .spyOn(contractApi, 'decide')
      .mockRejectedValueOnce(
        new ApiError({ code: 'NETWORK_ERROR', message: 'raw', status: 0, traceId: '' }),
      )
      .mockResolvedValueOnce({ contract: confirmed })
    const page = mountPanel()
    await flushPromises()
    await page.get('#contract-write-reason').setValue('字段与证据复核一致')

    await page.get('[data-testid="confirm-contract"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('合同操作失败')

    await page.get('[data-testid="confirm-contract"]').trigger('click')
    await flushPromises()
    expect(decide).toHaveBeenCalledTimes(2)
    expect(decide.mock.calls[1]?.[2]).toBe(decide.mock.calls[0]?.[2])
    expect(page.emitted('updated')?.[0]?.[0]).toMatchObject({ contract: { rowVersion: '3' } })
  })

  it('完整事实修正保留每个非空字段的当前来源证据', async () => {
    const replaceFacts = vi.spyOn(contractApi, 'replaceFacts').mockResolvedValue({
      contract: { ...draftContract, name: '修正后的合同名称', rowVersion: '3' },
    })
    const page = mountPanel()
    await flushPromises()
    await page.get('#contract-write-reason').setValue('根据合同原文修正名称')
    await page.get('[data-testid="edit-contract-facts"]').trigger('click')
    await page.get('#edit-contract-name').setValue('修正后的合同名称')
    await page.get('[data-testid="replace-contract-facts"]').trigger('click')
    await flushPromises()

    const input = replaceFacts.mock.calls[0]?.[1]
    expect(input?.facts.name).toBe('修正后的合同名称')
    expect(input?.fieldEvidence).toHaveLength(contractFieldCodes.length)
    expect(input?.fieldEvidence[1]).toEqual({ fieldCode: 'name', evidence: sourceEvidence(1) })
  })

  it('不为缺失来源证据的非空字段伪造写入证据', async () => {
    const incomplete: ContractEvidenceResponseData = {
      ...evidence,
      fields: evidence.fields.map((field) =>
        field.fieldCode === 'payment_terms' ? { ...field, evidence: null } : field,
      ),
    }
    const replaceFacts = vi.spyOn(contractApi, 'replaceFacts')
    const page = mountPanel(true, incomplete)
    await flushPromises()
    await page.get('#contract-write-reason').setValue('尝试提交缺证据字段')
    await page.get('[data-testid="edit-contract-facts"]').trigger('click')
    await page.get('[data-testid="replace-contract-facts"]').trigger('click')
    await flushPromises()

    expect(page.text()).toContain('付款条件没有可复核的来源证据')
    expect(replaceFacts).not.toHaveBeenCalled()
  })
})
