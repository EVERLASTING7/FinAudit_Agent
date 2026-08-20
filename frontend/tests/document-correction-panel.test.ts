import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DocumentCorrectionPanel from '@/components/DocumentCorrectionPanel.vue'
import { documentCorrectionApi } from '@/services/documentCorrections'
import { useAuthStore } from '@/stores/auth'

const blockId = '62000000-0000-4000-8000-000000000001'
const sourceParseId = '62000000-0000-4000-8000-000000000002'
const resultParseId = '62000000-0000-4000-8000-000000000003'
const correctionId = '62000000-0000-4000-8000-000000000004'
const jobId = '62000000-0000-4000-8000-000000000005'
let pinia: ReturnType<typeof createPinia>

describe('来源文本纠错面板', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().setAuthenticatedSession(
      {
        id: '62000000-0000-4000-8000-000000000006',
        displayName: '财务复核员',
        roles: ['finance_reviewer'],
        permissions: ['files.manage'],
      },
      'token',
    )
  })

  it('只在人工点击后创建候选，并以第二个动作独立激活', async () => {
    const correct = vi.spyOn(documentCorrectionApi, 'correctBlock').mockResolvedValue({
      correctionId,
      resultParseVersionId: resultParseId,
      jobId,
      status: 'queued',
    })
    const activate = vi.spyOn(documentCorrectionApi, 'activateParse').mockResolvedValue({
      id: resultParseId,
      status: 'active',
      supersededVersionId: sourceParseId,
      activatedAt: '2026-08-18T08:00:00Z',
    })
    const wrapper = mount(DocumentCorrectionPanel, {
      props: {
        businessType: 'contract',
        evidenceItems: [
          {
            blockId,
            parseVersionId: sourceParseId,
            pageNo: 1,
            quoteText: 'Contract Number C-001',
          },
        ],
      },
      global: { plugins: [pinia] },
    })

    await wrapper.get('select').setValue(`${sourceParseId}:${blockId}`)
    await wrapper.get('#document-correction-text').setValue('Contract Number C-002')
    await wrapper.get('#document-correction-reason').setValue('人工复核')
    await wrapper.get('[data-testid="submit-document-correction"]').trigger('click')
    await flushPromises()

    expect(correct).toHaveBeenCalledOnce()
    expect(activate).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(resultParseId)
    expect(wrapper.text()).toContain('当前活动解析版本尚未改变')

    await wrapper.get('[data-testid="activate-document-correction"]').trigger('click')
    await flushPromises()

    expect(activate).toHaveBeenCalledOnce()
    expect(wrapper.emitted('activated')).toHaveLength(1)
    expect(wrapper.text()).toContain('已独立激活')
  })

  it('角色或权限不满足时不呈现写入口', () => {
    useAuthStore().setAuthenticatedSession(
      {
        id: '62000000-0000-4000-8000-000000000006',
        displayName: '只读用户',
        roles: ['read_only'],
        permissions: ['files.read'],
      },
      'token',
    )
    const wrapper = mount(DocumentCorrectionPanel, {
      props: {
        businessType: 'invoice',
        evidenceItems: [
          { blockId, parseVersionId: sourceParseId, pageNo: 1, quoteText: 'invoice' },
        ],
      },
      global: { plugins: [pinia] },
    })

    expect(wrapper.text()).toContain('只能查看现有证据')
    expect(wrapper.find('[data-testid="submit-document-correction"]').exists()).toBe(false)
  })
})
