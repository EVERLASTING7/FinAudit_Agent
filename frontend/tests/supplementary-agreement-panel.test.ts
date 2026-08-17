import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SupplementaryAgreementPanel from '@/components/SupplementaryAgreementPanel.vue'
import { ApiError } from '@/services/api'
import {
  decodeSupplementaryAgreementDetail,
  supplementaryAgreementApi,
  type SupplementaryAgreementDetail,
} from '@/services/supplementaryAgreements'
import { useAuthStore } from '@/stores/auth'

const contractId = '30000000-0000-4000-8000-000000000020'
const agreementId = '31000000-0000-4000-8000-000000000020'
const evidenceBlockId = '33000000-0000-4000-8000-000000000020'
const traceId = '90000000-0000-4000-8000-000000000010'
const detail = decodeSupplementaryAgreementDetail({
  id: agreementId,
  contract_id: contractId,
  agreement_no: 'BC-2026-0020',
  name: '服务范围补充协议',
  signed_date: '2026-02-10',
  effective_date: '2026-02-15',
  status: 'pending_confirmation',
  confirmation_status: 'unconfirmed',
  changes: [
    {
      id: '32000000-0000-4000-8000-000000000020',
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
})
const confirmedDetail: SupplementaryAgreementDetail = {
  ...detail,
  status: 'confirmed',
  confirmationStatus: 'confirmed',
  changes: detail.changes.map((change) => ({
    ...change,
    confirmationStatus: 'confirmed',
  })),
  rowVersion: '3',
}

let wrapper: VueWrapper | undefined

function mountPanel(canManage = true): VueWrapper {
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
  wrapper = mount(SupplementaryAgreementPanel, {
    props: { contractId, agreementId },
    global: { plugins: [pinia] },
  })
  return wrapper
}

beforeEach(() => {
  vi.spyOn(supplementaryAgreementApi, 'getDetail').mockResolvedValue(detail)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('补充协议字段级面板', () => {
  it('无合同管理权限时只读取字段与证据，不渲染写操作', async () => {
    const page = mountPanel(false)
    await flushPromises()

    expect(supplementaryAgreementApi.getDetail).toHaveBeenCalledWith(
      contractId,
      agreementId,
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('只读模式')
    expect(page.text()).toContain('合同总金额调整为 1,250,000.00 元')
    expect(page.find('[data-testid="edit-supplementary-changes"]').exists()).toBe(false)
    expect(page.find('[data-testid="confirm-supplementary"]').exists()).toBe(false)
  })

  it('完整替换变更集合时保留来源证据并发出新版本', async () => {
    const updated: SupplementaryAgreementDetail = {
      ...detail,
      changes: detail.changes.map((change) => ({ ...change, newValue: '1300000.00' })),
      rowVersion: '3',
    }
    const replaceChanges = vi
      .spyOn(supplementaryAgreementApi, 'replaceChanges')
      .mockResolvedValue(updated)
    const page = mountPanel()
    await flushPromises()

    await page.get('#supplementary-write-reason').setValue('根据补充协议原文修正金额')
    await page.get('[data-testid="edit-supplementary-changes"]').trigger('click')
    await page.get('[data-testid="supplementary-new-value-0"]').setValue('1300000.00')
    await page.get('[data-testid="replace-supplementary-changes"]').trigger('click')
    await flushPromises()

    expect(replaceChanges).toHaveBeenCalledTimes(1)
    expect(replaceChanges.mock.calls[0]?.[0]).toBe(contractId)
    expect(replaceChanges.mock.calls[0]?.[1]).toBe(agreementId)
    expect(replaceChanges.mock.calls[0]?.[2]).toEqual({
      rowVersion: '2',
      reason: '根据补充协议原文修正金额',
      changes: [
        {
          fieldCode: 'amount',
          valueType: 'number',
          newValue: '1300000.00',
          evidenceBlockId,
          pageNo: 2,
          quoteText: '合同总金额调整为 1,250,000.00 元',
          bbox: { x: 12, y: 24 },
        },
      ],
    })
    expect(replaceChanges.mock.calls[0]?.[3]).toMatch(/^supplementary-write\.[0-9a-f-]{36}$/)
    expect(replaceChanges.mock.calls[0]?.[4]).toBeInstanceOf(AbortSignal)
    expect(page.emitted('updated')?.[0]?.[0]).toMatchObject({ rowVersion: '3' })
    expect(page.text()).toContain('字段级变更已完整替换')
  })

  it('未知结果后以相同幂等键重试确认', async () => {
    const decide = vi
      .spyOn(supplementaryAgreementApi, 'decide')
      .mockRejectedValueOnce(
        new ApiError({ code: 'NETWORK_ERROR', message: 'raw', status: 0, traceId: '' }),
      )
      .mockResolvedValueOnce(confirmedDetail)
    const page = mountPanel()
    await flushPromises()
    await page.get('#supplementary-write-reason').setValue('来源证据已逐项复核')

    await page.get('[data-testid="confirm-supplementary"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('补充协议操作失败')
    expect(page.text()).not.toContain('raw')

    await page.get('[data-testid="confirm-supplementary"]').trigger('click')
    await flushPromises()

    expect(decide).toHaveBeenCalledTimes(2)
    expect(decide.mock.calls[1]?.[3]).toBe(decide.mock.calls[0]?.[3])
    expect(page.emitted('updated')?.[0]?.[0]).toMatchObject({
      confirmationStatus: 'confirmed',
      rowVersion: '3',
    })
  })

  it('并发冲突只展示安全提示和 Trace ID', async () => {
    vi.spyOn(supplementaryAgreementApi, 'decide').mockRejectedValue(
      new ApiError({
        code: 'ROW_VERSION_CONFLICT',
        message: 'raw backend private detail',
        status: 409,
        traceId,
      }),
    )
    const page = mountPanel()
    await flushPromises()
    await page.get('#supplementary-write-reason').setValue('拒绝当前字段集合')
    await page.get('[data-testid="reject-supplementary"]').trigger('click')
    await flushPromises()

    expect(page.text()).toContain('协议版本、状态、字段或证据已变化')
    expect(page.text()).toContain(traceId)
    expect(page.text()).not.toContain('raw backend private detail')
  })

  it('卸载时中止未完成的字段详情请求', () => {
    let signal: AbortSignal | undefined
    vi.mocked(supplementaryAgreementApi.getDetail).mockImplementation(
      (_contractId, _agreementId, requestSignal) => {
        signal = requestSignal
        return new Promise<SupplementaryAgreementDetail>(() => undefined)
      },
    )
    const page = mountPanel()

    page.unmount()
    wrapper = undefined

    expect(signal?.aborted).toBe(true)
  })
})
