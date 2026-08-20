import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import App from '@/App.vue'
import { createAppRouter } from '@/router'
import {
  permissionCodes,
  roleCodes,
  type PermissionCode,
  type RoleCode,
} from '@/services/auth'
import { useAuthStore } from '@/stores/auth'
import { invoiceApi } from '@/services/invoices'
import { contractApi } from '@/services/contracts'
import { invoicePrimaryContractApi } from '@/services/invoicePrimaryContract'
import { contractPrimaryInvoiceApi } from '@/services/contractPrimaryInvoices'
import { userApi } from '@/services/users'
import { operationLogApi } from '@/services/operationLogs'
import { fileApi } from '@/services/files'
import { auditApi } from '@/services/audits'
import { reportApi } from '@/services/reports'
import { dashboardApi } from '@/services/dashboard'
import { knowledgeApi } from '@/services/knowledge'
import { policyApi } from '@/services/policies'
import { supplierApi } from '@/services/suppliers'

const fileId = '41000000-0000-4000-8000-000000000001'
const fileJobId = '41000000-0000-4000-8000-000000000002'
const auditTaskId = 'a5000000-0000-4000-8000-000000000004'
const auditExecutionId = 'a5000000-0000-4000-8000-000000000005'
const knowledgeBaseId = '61000000-0000-4000-8000-000000000001'
const supplierId = '51000000-0000-4000-8000-000000000001'
const fileItem = {
  fileId,
  originalName: 'contract-c001-scan.pdf',
  status: 'stored' as const,
  securityScanStatus: 'clean' as const,
  reused: false,
  intendedBusinessType: 'contract' as const,
  targetKnowledgeBaseId: null,
  autoProcessRequested: true,
  jobId: fileJobId,
  jobStatus: 'succeeded' as const,
  job: {
    id: fileJobId,
    status: 'succeeded' as const,
    stage: 'markdown' as const,
    attemptNo: 1,
    maxAttempts: 3,
    rowVersion: '4',
    retryable: false,
  },
  jobScope: 'full' as const,
  nextStage: 'scan' as const,
  rowVersion: '2',
  sizeBytes: '1887437',
  createdAt: '2026-08-08T09:20:00+08:00',
}

const allRoles: RoleCode[] = [...roleCodes]
const allPermissions: PermissionCode[] = [...permissionCodes]

const pageRoutes = [
  ['/dashboard', '工作台'],
  ['/files', '文件管理'],
  [`/files/${fileId}`, 'contract-c001-scan.pdf'],
  ['/contracts', '合同管理'],
  ['/contracts/contract-c001', '合同详情'],
  ['/contracts/30000000-0000-4000-8000-000000000001/primary-invoices', '合同当前主合同发票'],
  ['/invoices', '发票管理'],
  ['/invoices/invoice-i001', '发票详情'],
  ['/invoices/40000000-0000-4000-8000-000000000001/contract-links', '发票主合同'],
  ['/suppliers', '供应商管理'],
  [`/suppliers/${supplierId}`, '示例供应商'],
  ['/knowledge-bases', '制度知识库'],
  [`/knowledge-bases/${knowledgeBaseId}`, '企业财务制度库'],
  ['/qa', '制度问答'],
  ['/audit-tasks', '审核任务'],
  [`/audit-tasks/${auditTaskId}`, 'AUD-2026-0088'],
  ['/audit-reports/REP-2026-0042', '审核报告'],
  ['/users', '用户管理'],
  ['/operation-logs', '操作日志'],
] as const

let wrapper: VueWrapper | undefined

beforeEach(() => {
  sessionStorage.clear()
  document.body.innerHTML = ''
  vi.spyOn(invoiceApi, 'list').mockResolvedValue({
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(invoiceApi, 'listDuplicateCandidates').mockResolvedValue({
    basisStatus: 'ready',
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(invoiceApi, 'getEvidence').mockResolvedValue({
    invoiceId: '40000000-0000-4000-8000-000000000001',
    rowVersion: '2',
    fieldEvidence: [],
    itemEvidence: {},
  })
  vi.spyOn(invoiceApi, 'getHistory').mockResolvedValue({
    invoiceId: '40000000-0000-4000-8000-000000000001',
    items: [],
  })
  vi.spyOn(contractApi, 'list').mockResolvedValue({
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(invoicePrimaryContractApi, 'get').mockResolvedValue({ primaryContract: null })
  vi.spyOn(invoicePrimaryContractApi, 'listCandidates').mockResolvedValue({
    invoiceId: '40000000-0000-4000-8000-000000000001',
    invoiceRowVersion: '1',
    items: [],
  })
  vi.spyOn(invoicePrimaryContractApi, 'getHistory').mockResolvedValue({
    invoiceId: '40000000-0000-4000-8000-000000000001',
    items: [],
  })
  vi.spyOn(contractPrimaryInvoiceApi, 'list').mockResolvedValue({
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(userApi, 'list').mockResolvedValue({ items: [], pageSize: 20, nextCursor: null })
  vi.spyOn(operationLogApi, 'list').mockResolvedValue({
    items: [],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(fileApi, 'list').mockResolvedValue({ items: [], pageSize: 20, nextCursor: null })
  vi.spyOn(fileApi, 'get').mockResolvedValue(fileItem)
  vi.spyOn(fileApi, 'previewOriginal').mockResolvedValue({
    body: new Blob(['preview'], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }),
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    status: 'stored',
  })
  vi.spyOn(fileApi, 'textPreview').mockResolvedValue({
    fileId,
    markdownVersionId: 'a5000000-0000-4000-8000-000000000009',
    contentSha256: 'a'.repeat(64),
    markdownText: '# 合同预览',
    charCount: 6,
    truncated: false,
  })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:page-file-preview')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(auditApi, 'list').mockResolvedValue({ items: [], pageSize: 20, nextCursor: null })
  vi.spyOn(auditApi, 'getTask').mockResolvedValue({
    task: {
      id: auditTaskId,
      taskNo: 'AUD-2026-0088',
      name: '浏览器审核任务',
      description: null,
      ownerId: '90000000-0000-4000-8000-000000000001',
      currentExecutionId: auditExecutionId,
      status: 'open',
      rowVersion: '1',
      createdAt: '2026-08-15T00:00:00Z',
      updatedAt: '2026-08-15T00:00:00Z',
    },
    execution: {
      id: auditExecutionId,
      auditTaskId,
      versionNo: 1,
      baselineDate: '2026-08-15',
      status: 'pending_finance_review',
      snapshotSha256: 'a'.repeat(64),
      jobId: 'a5000000-0000-4000-8000-000000000006',
      financeReviewerId: null,
      financeReviewedAt: null,
      auditReviewerId: null,
      auditReviewedAt: null,
      retryable: false,
      job: {
        id: 'a5000000-0000-4000-8000-000000000006',
        status: 'succeeded',
        stage: 'evaluate',
        attemptNo: 1,
        maxAttempts: 3,
        rowVersion: '3',
        retryable: false,
      },
      failureCode: null,
      cancelReason: null,
      returnReason: null,
      rowVersion: '2',
      createdAt: '2026-08-15T00:00:00Z',
      startedAt: '2026-08-15T00:00:01Z',
      finishedAt: null,
      outdatedAt: null,
    },
    rules: [],
    risks: [],
  })
  vi.spyOn(reportApi, 'list').mockResolvedValue({ executionId: auditExecutionId, items: [] })
  vi.spyOn(dashboardApi, 'get').mockResolvedValue({
    itemLimit: 5,
    auditTasks: { openCount: 0, pendingReviewCount: 0, items: [] },
    files: { activeProcessingCount: 0, failedProcessingCount: 0, items: [] },
    failedJobs: { failedCount: 0, items: [] },
  })
  vi.spyOn(knowledgeApi, 'list').mockResolvedValue({
    items: [{ id: knowledgeBaseId, code: 'KB-FIN-001', name: '企业财务制度库', description: null, status: 'active', defaultTopK: 5, rowVersion: '1' }],
    pageSize: 20,
    nextCursor: null,
  })
  vi.spyOn(knowledgeApi, 'getDetail').mockResolvedValue({ id: knowledgeBaseId, code: 'KB-FIN-001', name: '企业财务制度库', description: null, status: 'active', defaultTopK: 5, rowVersion: '1' })
  vi.spyOn(policyApi, 'list').mockResolvedValue({ items: [], pageSize: 20, nextCursor: null })
  const supplier = { id: supplierId, standardName: '示例供应商', taxNumber: '91310000EXAMPLE01', sourceType: 'contract' as const, sourceContractId: '30000000-0000-4000-8000-000000000001', sourceInvoiceId: null, confirmationStatus: 'unconfirmed' as const, status: 'candidate' as const, confirmedBy: null, confirmedAt: null, rowVersion: '1' }
  vi.spyOn(supplierApi, 'list').mockResolvedValue({ items: [supplier], pageSize: 20, nextCursor: null })
  vi.spyOn(supplierApi, 'getDetail').mockResolvedValue(supplier)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('P0 页面渲染', () => {
  it('所有业务路由都渲染专用页面且不再落入模块占位页', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore(pinia).setAuthenticatedSession(
      {
        id: '90000000-0000-4000-8000-000000000001',
        displayName: '页面验收用户',
        roles: allRoles,
        permissions: allPermissions,
      },
      'test-token',
    )

    const router = createAppRouter(createMemoryHistory())
    await router.push('/dashboard')
    await router.isReady()

    wrapper = mount(App, {
      attachTo: document.body,
      global: { plugins: [pinia, router] },
    })

    expect(wrapper.get('nav[aria-label="主导航"]').text()).not.toContain('合同发票关联')

    for (const [path, expectedTitle] of pageRoutes) {
      await router.push(path)
      await flushPromises()

      const heading = wrapper.get('#main-content h1').text()
      expect(heading).toContain(expectedTitle)
      expect(wrapper.text()).not.toContain('业务页面尚未实现')
    }
  })
})
