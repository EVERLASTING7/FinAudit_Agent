import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError } from '@/services/api'
import {
  OperationLogApi,
  decodeOperationLogList,
  operationLogApi,
} from '@/services/operationLogs'
import OperationLogView from '@/views/OperationLogView.vue'

const traceId = '90000000-0000-4000-8000-000000000010'
const logId = '70000000-0000-4000-8000-000000000001'
const actorId = '10000000-0000-4000-8000-000000000001'
const resourceId = '10000000-0000-4000-8000-000000000002'
const rawItem = {
  id: logId,
  actor_kind: 'user',
  actor_id: actorId,
  action_code: 'users.status_changed',
  outcome: 'succeeded',
  resource_type: 'user',
  resource_id: resourceId,
  trace_id: traceId,
  change_summary: { from_status: 'active', to_status: 'disabled', row_version: '2' },
  created_at: '2026-08-13T01:02:03.123456Z',
}
const oneItemPage = decodeOperationLogList({
  items: [rawItem],
  page_size: 20,
  next_cursor: null,
})
let wrapper: VueWrapper | undefined

function cursorFor(createdAt: string, id: string): string {
  return btoa(JSON.stringify({ created_at: createdAt, id, v: 1 }))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '')
}

function jsonResponse(data: unknown): Response {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      data,
      trace_id: traceId,
      timestamp: '2026-08-13T00:00:00Z',
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

describe('OperationLogApi', () => {
  it('严格解码追加日志并保留 bigint 字符串和脱敏摘要', () => {
    expect(oneItemPage.items[0]).toEqual({
      id: logId,
      actorKind: 'user',
      actorId,
      actionCode: 'users.status_changed',
      outcome: 'succeeded',
      resourceType: 'user',
      resourceId,
      traceId,
      changeSummary: { from_status: 'active', to_status: 'disabled', row_version: '2' },
      createdAt: '2026-08-13T01:02:03.123456Z',
    })
  })

  it.each([
    ['额外字段', { secret: 'must-not-render' }],
    ['非法 Actor 矩阵', { actor_kind: 'anonymous' }],
    ['未知 action', { action_code: 'database.dumped' }],
    ['非法资源矩阵', { resource_id: null }],
    ['非法 Trace ID', { trace_id: 'TRACE-1' }],
    ['非法时间', { created_at: 'yesterday' }],
    ['非有限 JSON', { change_summary: { value: Number.NaN } }],
  ])('拒绝%s', (_label, change) => {
    expect(() =>
      decodeOperationLogList({
        items: [{ ...rawItem, ...change }],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })

  it('只发送 page_size 与 canonical opaque cursor', async () => {
    const cursor = cursorFor(rawItem.created_at, logId)
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ items: [rawItem], page_size: 1, next_cursor: cursor }),
    )
    const api = new OperationLogApi(new ApiClient({ fetcher }))

    await expect(api.list(1, cursor)).resolves.toMatchObject({ pageSize: 1, nextCursor: cursor })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/operation-logs?page_size=1&cursor=${cursor}`,
    )
  })

  it.each(['bad=', '含中文', 'A'])('拒绝非法 cursor %s 且不发请求', async (cursor) => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new OperationLogApi(new ApiClient({ fetcher }))

    await expect(api.list(20, cursor)).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('OperationLogView', () => {
  it('展示真实 action、资源、脱敏摘要与 Trace ID', async () => {
    vi.spyOn(operationLogApi, 'list').mockResolvedValue(oneItemPage)
    wrapper = mount(OperationLogView)
    await flushPromises()

    expect(wrapper.text()).toContain('变更用户状态')
    expect(wrapper.text()).toContain(resourceId)
    expect(wrapper.text()).toContain('"to_status":"disabled"')
    expect(wrapper.text()).toContain(traceId)
  })

  it('错误只展示安全文案与 Trace ID 并允许同页重试', async () => {
    vi.spyOn(operationLogApi, 'list')
      .mockRejectedValueOnce(
        new ApiError({ code: 'SYNTHETIC', message: 'backend secret', status: 403, traceId }),
      )
      .mockResolvedValueOnce(oneItemPage)
    wrapper = mount(OperationLogView)
    await flushPromises()

    expect(wrapper.text()).toContain('当前账号无权读取操作日志')
    expect(wrapper.text()).toContain(traceId)
    expect(wrapper.text()).not.toContain('backend secret')
    await wrapper.get('[data-testid="retry-operation-logs"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('变更用户状态')
  })
})
