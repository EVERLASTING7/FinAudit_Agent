import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/services/api'
import { fileApi } from '@/services/files'
import {
  decodeKnowledgeBase,
  decodeQaQuery,
  KnowledgeApi,
  knowledgeApi,
} from '@/services/knowledge'
import {
  decodePendingPolicyRevocationList,
  decodePolicy,
  PolicyApi,
  policyApi,
  type PolicyDocument,
} from '@/services/policies'
import { useAuthStore } from '@/stores/auth'
import KnowledgeBaseDetailView from '@/views/KnowledgeBaseDetailView.vue'
import KnowledgeBaseListView from '@/views/KnowledgeBaseListView.vue'
import QaView from '@/views/QaView.vue'

const knowledgeBaseId = '61000000-0000-4000-8000-000000000001'
const policyId = '62000000-0000-4000-8000-000000000001'
const fileId = '63000000-0000-4000-8000-000000000001'
const queryId = '64000000-0000-4000-8000-000000000001'
const feedbackId = '65000000-0000-4000-8000-000000000001'
const indexId = '66000000-0000-4000-8000-000000000001'
const markdownId = '67000000-0000-4000-8000-000000000001'
const chunkId = '68000000-0000-4000-8000-000000000001'
const blockId = '69000000-0000-4000-8000-000000000001'
const userId = '6a000000-0000-4000-8000-000000000001'
const adminId = '6a000000-0000-4000-8000-000000000002'
const revocationRequestId = '6a000000-0000-4000-8000-000000000003'
const traceId = '6b000000-0000-4000-8000-000000000001'

const rawKnowledgeBase = {
  id: knowledgeBaseId,
  code: 'KB-FIN-001',
  name: '企业财务制度库',
  description: '组织级财务制度',
  status: 'active',
  default_top_k: 5,
  row_version: '2',
}
const knowledgeBase = decodeKnowledgeBase(rawKnowledgeBase)

const rawPolicy = {
  id: policyId,
  knowledge_base_id: knowledgeBaseId,
  source_file_id: fileId,
  policy_code: 'POL-FIN-001',
  name: '财务审核办法',
  version: 'v1.0',
  issuing_department: '财务部',
  effective_from: '2026-01-01',
  effective_to: null,
  scope: {},
  status: 'draft',
  submitted_by: null,
  submitted_at: null,
  business_approved_by: null,
  business_approved_at: null,
  technical_published_by: null,
  technical_published_at: null,
  revoked_at: null,
  revoked_by: null,
  revoke_reason: null,
  row_version: '1',
}
const draftPolicy = decodePolicy(rawPolicy)
const submittedPolicy: PolicyDocument = {
  ...draftPolicy,
  status: 'submitted',
  submittedBy: userId,
  submittedAt: '2026-08-15T08:00:00Z',
  rowVersion: '2',
}
const publishedPolicy: PolicyDocument = {
  ...submittedPolicy,
  status: 'published',
  businessApprovedBy: userId,
  businessApprovedAt: '2026-08-15T08:01:00Z',
  technicalPublishedBy: adminId,
  technicalPublishedAt: '2026-08-15T08:02:00Z',
  rowVersion: '4',
}
const revokedPolicy: PolicyDocument = {
  ...publishedPolicy,
  status: 'revoked',
  revokedAt: '2026-08-15T08:03:00Z',
  revokedBy: adminId,
  revokeReason: '执行独立撤销确认',
  rowVersion: '5',
}
const pendingRevocation = {
  revocationRequestId,
  policyId,
  policyCode: publishedPolicy.policyCode,
  policyName: publishedPolicy.name,
  policyRowVersion: publishedPolicy.rowVersion,
  requestedBy: userId,
  requestedAt: '2026-08-15T08:03:00Z',
}

const rawQaQuery = {
  id: queryId,
  knowledge_base_id: knowledgeBaseId,
  index_version_id: indexId,
  baseline_date: '2026-08-15',
  status: 'answered',
  answer: '根据制度，需保留审批链和比价证据。',
  reason_code: null,
  citations: [
    {
      policy_document_id: policyId,
      policy_version: 'v1.0',
      markdown_version_id: markdownId,
      chunk_id: chunkId,
      block_ids: [blockId],
      index_version_id: indexId,
      page_range: '1-2',
      title_path: ['采购审批', '证据留存'],
      quote: '应保留审批链和比价证据。',
      content_sha256: 'a'.repeat(64),
    },
  ],
  retrieved_count: 1,
  created_at: '2026-08-15T08:00:00Z',
}
const qaResult = decodeQaQuery(rawQaQuery)

let wrapper: VueWrapper | undefined

function jsonResponse(data: unknown): Response {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'success', data, trace_id: traceId, timestamp: '2026-08-15T08:00:00Z' }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

function authenticatedPinia(
  permissions: string[],
  roles: Array<'audit_reviewer' | 'system_admin'> = ['audit_reviewer'],
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore(pinia).setAuthenticatedSession(
    { id: userId, displayName: '知识管理员', roles, permissions: permissions as never[] },
    'test-token',
  )
  return pinia
}

beforeEach(() => {
  vi.spyOn(knowledgeApi, 'list').mockResolvedValue({ items: [knowledgeBase], pageSize: 20, nextCursor: null })
  vi.spyOn(knowledgeApi, 'getDetail').mockResolvedValue(knowledgeBase)
  vi.spyOn(policyApi, 'list').mockResolvedValue({ items: [draftPolicy], pageSize: 20, nextCursor: null })
  vi.spyOn(policyApi, 'listPendingRevocations').mockResolvedValue({ items: [], pageSize: 50, nextCursor: null })
  vi.spyOn(fileApi, 'list').mockResolvedValue({ items: [], pageSize: 100, nextCursor: null })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('知识服务合同', () => {
  it('严格解码知识库与问答状态投影', () => {
    expect(knowledgeBase).toMatchObject({ name: '企业财务制度库', defaultTopK: 5 })
    expect(qaResult.citations[0]?.titlePath).toEqual(['采购审批', '证据留存'])
    expect(() => decodeKnowledgeBase({ ...rawKnowledgeBase, default_top_k: 8 })).toThrow('must be 5')
    expect(() => decodeQaQuery({ ...rawQaQuery, answer: null })).toThrow('inconsistent')
  })

  it('知识目录、问答与反馈使用冻结路径和幂等键', async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input)
      if (path.includes('/qa-queries/') && path.endsWith('/feedback')) {
        return jsonResponse({ id: feedbackId, qa_query_id: queryId, rating: 'helpful', correction_text: null, created_at: '2026-08-15T08:01:00Z' })
      }
      if (path.endsWith('/qa-queries')) return jsonResponse(rawQaQuery)
      return jsonResponse({ items: [rawKnowledgeBase], page_size: 20, next_cursor: null })
    })
    const api = new KnowledgeApi(new ApiClient({ fetcher }))

    await api.list(20)
    await api.query(knowledgeBaseId, { question: '需要保留什么证据？', baselineDate: '2026-08-15' }, 'qa-query.12345678')
    await api.feedback(queryId, { rating: 'helpful' }, 'qa-feedback.12345678')

    expect(String(fetcher.mock.calls[0]?.[0])).toBe('/api/v1/knowledge-bases?page_size=20')
    expect(new Headers(fetcher.mock.calls[1]?.[1]?.headers).get('Idempotency-Key')).toBe('qa-query.12345678')
    expect(new Headers(fetcher.mock.calls[2]?.[1]?.headers).get('Idempotency-Key')).toBe('qa-feedback.12345678')
  })

  it('制度列表、创建、状态推进与两阶段撤销使用冻结合同', async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const path = String(input)
      if (path.includes('/policy-documents/revocation-requests?')) {
        return jsonResponse({
          items: [
            {
              revocation_request_id: revocationRequestId,
              policy_id: policyId,
              policy_code: publishedPolicy.policyCode,
              policy_name: publishedPolicy.name,
              policy_row_version: publishedPolicy.rowVersion,
              requested_by: userId,
              requested_at: '2026-08-15T08:03:00Z',
            },
          ],
          page_size: 50,
          next_cursor: null,
        })
      }
      if (path.includes('?')) return jsonResponse({ items: [rawPolicy], page_size: 20, next_cursor: null })
      if (path.endsWith('/submit-review')) {
        return jsonResponse({ policy: { ...rawPolicy, status: 'submitted', submitted_by: userId, submitted_at: '2026-08-15T08:00:00Z', row_version: '2' }, chunk_set: null })
      }
      if (path.endsWith('/revocation-requests')) {
        return jsonResponse({
          revocation_request_id: revocationRequestId,
          policy_id: policyId,
          status: 'pending_execution',
          requested_by: userId,
          requested_at: '2026-08-15T08:03:00Z',
        })
      }
      if (path.endsWith('/revoke')) {
        return jsonResponse({
          policy: {
            ...rawPolicy,
            status: 'revoked',
            submitted_by: userId,
            submitted_at: '2026-08-15T08:00:00Z',
            business_approved_by: userId,
            business_approved_at: '2026-08-15T08:01:00Z',
            technical_published_by: adminId,
            technical_published_at: '2026-08-15T08:02:00Z',
            revoked_at: '2026-08-15T08:03:00Z',
            revoked_by: adminId,
            revoke_reason: '执行独立撤销确认',
            row_version: '5',
          },
          chunk_set: null,
        })
      }
      return jsonResponse({ policy: rawPolicy, chunk_set: null })
    })
    const api = new PolicyApi(new ApiClient({ fetcher }))

    await api.list(20, undefined, knowledgeBaseId)
    const pending = await api.listPendingRevocations(knowledgeBaseId)
    await api.create({ knowledgeBaseId, sourceFileId: fileId, policyCode: 'POL-FIN-001', name: '财务审核办法', version: 'v1.0', issuingDepartment: null, effectiveFrom: '2026-01-01', effectiveTo: null, scope: {} }, 'policy-create.12345678')
    await api.transition(policyId, 'submit-review', '1', '提交业务审批', 'policy-transition.12345678')
    await api.requestRevocation(policyId, '4', '申请撤销', 'policy-revoke-request.12345678')
    await api.revoke(policyId, '4', revocationRequestId, '执行独立撤销确认', 'policy-revoke.12345678')

    expect(String(fetcher.mock.calls[0]?.[0])).toContain(`knowledge_base_id=${knowledgeBaseId}`)
    expect(String(fetcher.mock.calls[1]?.[0])).toContain(
      `/api/v1/policy-documents/revocation-requests?knowledge_base_id=${knowledgeBaseId}`,
    )
    expect(pending.items).toEqual([pendingRevocation])
    expect(() =>
      decodePendingPolicyRevocationList({
        items: [
          {
            revocation_request_id: revocationRequestId,
            policy_id: policyId,
            policy_code: publishedPolicy.policyCode,
            policy_name: publishedPolicy.name,
            policy_row_version: '0',
            requested_by: userId,
            requested_at: '2026-08-15T08:03:00Z',
          },
        ],
        page_size: 50,
        next_cursor: null,
      }),
    ).toThrow(TypeError)
    expect(String(fetcher.mock.calls[3]?.[0])).toBe(`/api/v1/policy-documents/${policyId}/submit-review`)
    expect(String(fetcher.mock.calls[4]?.[0])).toBe(`/api/v1/policy-documents/${policyId}/revocation-requests`)
    expect(JSON.parse(String(fetcher.mock.calls[5]?.[1]?.body))).toEqual({
      row_version: '4',
      revocation_request_id: revocationRequestId,
      reason: '执行独立撤销确认',
    })
  })
})

describe('知识页面', () => {
  it('知识库列表展示真实目录且不再展示演示数据', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/knowledge-bases', name: 'knowledge-bases', component: KnowledgeBaseListView },
      { path: '/knowledge-bases/:kbId', name: 'knowledge-base-detail', component: { template: '<div />' } },
      { path: '/qa', name: 'qa', component: { template: '<div />' } },
    ] })
    await router.push('/knowledge-bases')
    await router.isReady()
    wrapper = mount(KnowledgeBaseListView, { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.text()).toContain('企业财务制度库')
    expect(wrapper.text()).toContain('Top-K 固定为 5')
    expect(wrapper.text()).not.toContain('演示数据')
  })

  it('制度问答提交真实问题、展示引用并记录反馈', async () => {
    vi.spyOn(knowledgeApi, 'query').mockResolvedValue(qaResult)
    vi.spyOn(knowledgeApi, 'feedback').mockResolvedValue({ id: feedbackId, qaQueryId: queryId, rating: 'helpful', correctionText: null, createdAt: '2026-08-15T08:01:00Z' })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/qa', component: QaView }] })
    await router.push(`/qa?knowledge_base_id=${knowledgeBaseId}`)
    await router.isReady()
    wrapper = mount(QaView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('#qa-question').setValue('需要保留什么证据？')
    expect(wrapper.get('[data-testid="submit-qa-query"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('根据制度，需保留审批链和比价证据。')
    expect(wrapper.text()).toContain('采购审批 / 证据留存')
    await wrapper.get('[data-testid="qa-helpful"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('反馈已记录：有帮助')
  })

  it('知识库详情提交制度审批并采用后端返回的新版本', async () => {
    vi.spyOn(policyApi, 'transition').mockResolvedValue({ policy: submittedPolicy, chunkSet: null })
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/knowledge-bases', name: 'knowledge-bases', component: { template: '<div />' } },
      { path: '/knowledge-bases/:kbId', name: 'knowledge-base-detail', component: KnowledgeBaseDetailView },
      { path: '/qa', name: 'qa', component: { template: '<div />' } },
      { path: '/files/:fileId', name: 'file-detail', component: { template: '<div />' } },
    ] })
    await router.push(`/knowledge-bases/${knowledgeBaseId}`)
    await router.isReady()
    wrapper = mount(KnowledgeBaseDetailView, { global: { plugins: [router, authenticatedPinia(['knowledge.use', 'knowledge.submit'])] } })
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
    await wrapper.get(`[aria-label="POL-FIN-001 操作原因"]`).setValue('提交独立业务审批')
    await wrapper.get(`[data-testid="submit-policy-${policyId}"]`).trigger('click')
    await flushPromises()
    expect(policyApi.transition).toHaveBeenCalledWith(policyId, 'submit-review', '1', '提交独立业务审批', expect.stringMatching(/^policy-transition\./), expect.any(AbortSignal))
    expect(wrapper.text()).toContain('待业务批准')
  })

  it('审计复核角色只提交撤销确认，不自动执行撤销', async () => {
    vi.spyOn(policyApi, 'list').mockResolvedValue({ items: [publishedPolicy], pageSize: 20, nextCursor: null })
    const requestRevocation = vi.spyOn(policyApi, 'requestRevocation').mockResolvedValue({
      revocationRequestId,
      policyId,
      status: 'pending_execution',
      requestedBy: userId,
      requestedAt: '2026-08-15T08:03:00Z',
    })
    const revoke = vi.spyOn(policyApi, 'revoke')
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/knowledge-bases', name: 'knowledge-bases', component: { template: '<div />' } },
      { path: '/knowledge-bases/:kbId', name: 'knowledge-base-detail', component: KnowledgeBaseDetailView },
      { path: '/qa', name: 'qa', component: { template: '<div />' } },
      { path: '/files/:fileId', name: 'file-detail', component: { template: '<div />' } },
    ] })
    await router.push(`/knowledge-bases/${knowledgeBaseId}`)
    await router.isReady()
    wrapper = mount(KnowledgeBaseDetailView, { global: { plugins: [router, authenticatedPinia(['knowledge.use', 'knowledge.approve'])] } })
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
    await wrapper.get(`[aria-label="POL-FIN-001 操作原因"]`).setValue('制度已由新版本替代')
    await wrapper.get(`[data-testid="request-policy-revocation-${policyId}"]`).trigger('click')
    await flushPromises()
    expect(requestRevocation).toHaveBeenCalledWith(policyId, '4', '制度已由新版本替代', expect.stringMatching(/^policy-revocation-request\./), expect.any(AbortSignal))
    expect(revoke).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('等待系统管理员独立执行')
  })

  it('系统管理员从待办列表执行撤销并采用后端 revoked 投影', async () => {
    vi.spyOn(policyApi, 'list').mockResolvedValue({ items: [publishedPolicy], pageSize: 20, nextCursor: null })
    vi.mocked(policyApi.listPendingRevocations)
      .mockResolvedValueOnce({ items: [pendingRevocation], pageSize: 50, nextCursor: null })
      .mockResolvedValue({ items: [], pageSize: 50, nextCursor: null })
    const revoke = vi.spyOn(policyApi, 'revoke').mockResolvedValue({ policy: revokedPolicy, chunkSet: null })
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/knowledge-bases', name: 'knowledge-bases', component: { template: '<div />' } },
      { path: '/knowledge-bases/:kbId', name: 'knowledge-base-detail', component: KnowledgeBaseDetailView },
      { path: '/qa', name: 'qa', component: { template: '<div />' } },
      { path: '/files/:fileId', name: 'file-detail', component: { template: '<div />' } },
    ] })
    await router.push(`/knowledge-bases/${knowledgeBaseId}`)
    await router.isReady()
    wrapper = mount(KnowledgeBaseDetailView, { global: { plugins: [router, authenticatedPinia(['knowledge.publish'], ['system_admin'])] } })
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
    await wrapper.get(`[aria-label="POL-FIN-001 撤销执行原因"]`).setValue('执行独立撤销确认')
    await wrapper.get(`[data-testid="revoke-policy-form-${policyId}"]`).trigger('submit')
    await flushPromises()
    expect(revoke).toHaveBeenCalledWith(policyId, '4', revocationRequestId, '执行独立撤销确认', expect.stringMatching(/^policy-revoke\./), expect.any(AbortSignal))
    expect(wrapper.text()).toContain('已撤销，新检索将立即排除该制度')
    expect(wrapper.text()).toContain('执行独立撤销确认')
  })
})
