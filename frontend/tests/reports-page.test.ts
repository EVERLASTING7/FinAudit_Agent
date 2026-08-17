import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter } from '@/router'
import { reportApi, type AuditReportData } from '@/services/reports'
import { useAuthStore } from '@/stores/auth'
import AuditReportView from '@/views/AuditReportView.vue'

const reportId = '52000000-0000-4000-8000-000000000001'
const taskId = '52000000-0000-4000-8000-000000000002'
const executionId = '52000000-0000-4000-8000-000000000003'
const userId = '52000000-0000-4000-8000-000000000004'
const jobId = '52000000-0000-4000-8000-000000000005'
const pdf = new Blob(['%PDF-1.7\nformal'], { type: 'application/pdf' })
const xlsx = new Blob(['PK\u0003\u0004formal'], {
  type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
})
const report: AuditReportData = {
  id: reportId,
  auditTaskId: taskId,
  executionId,
  reportVersion: 2,
  status: 'ready',
  payloadSha256: 'a'.repeat(64),
  generatorVersion: 'formal-report-generator-v2',
  pdfSha256: 'b'.repeat(64),
  pdfSizeBytes: pdf.size,
  pdfMimeType: 'application/pdf',
  xlsxSha256: 'c'.repeat(64),
  xlsxSizeBytes: xlsx.size,
  xlsxMimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  jobId,
  failureCode: null,
  rowVersion: '3',
  createdBy: userId,
  createdAt: '2026-08-14T08:00:00+00:00',
  generatedAt: '2026-08-14T08:01:00+00:00',
  outdatedAt: null,
  archivedAt: null,
  isOutdated: false,
  aiDraftStatus: 'succeeded',
  aiDraftSha256: 'd'.repeat(64),
  aiDraft: {
    executiveSummary: '本期审核由确定性规则形成事实，AI 仅生成文字草稿。',
    scopeSummary: '覆盖当前冻结执行版本。',
    riskSummary: '存在待人工复核风险。',
    recommendations: ['由授权审核人复核风险事实。'],
    warnings: ['AI 草稿不替代人工结论。'],
  },
}

let wrapper: VueWrapper | undefined

beforeEach(() => {
  sessionStorage.clear()
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).setAuthenticatedSession(
    {
      id: userId,
      displayName: '报告验收用户',
      roles: ['audit_reviewer'],
      permissions: ['audits.read', 'reports.read', 'reports.export'],
    },
    'report-test-token',
  )
  vi.spyOn(reportApi, 'get').mockResolvedValue(report)
  vi.spyOn(reportApi, 'previewPdf').mockResolvedValue({
    body: pdf,
    filename: `audit-report-${reportId}-v2.pdf`,
    status: 'ready',
    isOutdated: false,
  })
  vi.spyOn(reportApi, 'downloadXlsx').mockResolvedValue({
    body: xlsx,
    filename: `audit-report-${reportId}-v2-risks.xlsx`,
    status: 'ready',
    isOutdated: false,
  })
  vi.spyOn(URL, 'createObjectURL')
    .mockReturnValueOnce('blob:formal-report-preview')
    .mockReturnValueOnce('blob:formal-report-download')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

async function mountPage(): Promise<VueWrapper> {
  const router = createAppRouter(createMemoryHistory())
  await router.push(`/audit-reports/${reportId}`)
  await router.isReady()
  const mounted = mount(AuditReportView, {
    global: { plugins: [router] },
  })
  await flushPromises()
  return mounted
}

describe('正式报告页面', () => {
  it('加载授权 PDF Blob 预览并触发 XLSX 下载', async () => {
    wrapper = await mountPage()

    expect(reportApi.get).toHaveBeenCalledWith(reportId, expect.any(AbortSignal))
    expect(reportApi.previewPdf).toHaveBeenCalledWith(report, expect.any(AbortSignal))
    expect(wrapper.get('h1').text()).toContain('V2')
    expect(wrapper.text()).toContain('报告已就绪')
    expect(wrapper.text()).not.toContain('质量通过，待激活')
    expect(wrapper.text()).toContain('AI 报告草稿（未审批）')
    expect(wrapper.text()).toContain('AI 草稿不替代人工结论')
    expect(wrapper.get('iframe[title="正式审核报告 PDF 预览"]').attributes('src')).toBe(
      'blob:formal-report-preview',
    )
    expect(wrapper.text()).not.toContain('演示')

    await wrapper.get('button.button-primary').trigger('click')
    await flushPromises()

    expect(reportApi.downloadXlsx).toHaveBeenCalledWith(report, expect.any(AbortSignal))
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce()
  })

  it('无 reports.export 权限时保持预览可用并禁用下载', async () => {
    useAuthStore().setAuthenticatedSession(
      {
        id: userId,
        displayName: '报告只读用户',
        roles: ['read_only'],
        permissions: ['reports.read'],
      },
      'report-read-token',
    )
    wrapper = await mountPage()

    const download = wrapper.get('button.button-primary')
    expect(download.attributes('disabled')).toBeDefined()
    await download.trigger('click')
    expect(reportApi.downloadXlsx).not.toHaveBeenCalled()
    expect(wrapper.find('iframe[title="正式审核报告 PDF 预览"]').exists()).toBe(true)
  })
})
