import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import BreakGlassPanel from '@/components/BreakGlassPanel.vue'
import { ApiClient, ApiError } from '@/services/api'
import {
  BreakGlassApi,
  breakGlassApi,
  decodeBreakGlassData,
} from '@/services/breakGlass'

const traceId = '90000000-0000-4000-8000-000000000010'
const requestId = '20000000-0000-4000-8000-000000000001'
const userId = '10000000-0000-4000-8000-000000000001'
const rawPending = {
  id: requestId,
  target_user_id: userId,
  target_role_code: 'finance_reviewer',
  requested_duration_seconds: 3600,
  status: 'pending',
  effective_from: null,
  expires_at: null,
  row_version: '1',
}
const pending = decodeBreakGlassData(rawPending)
let wrapper: VueWrapper | undefined

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

describe('BreakGlassApi', () => {
  it('严格解码状态与时间字段矩阵', () => {
    expect(pending).toEqual({
      id: requestId,
      targetUserId: userId,
      targetRoleCode: 'finance_reviewer',
      requestedDurationSeconds: 3600,
      status: 'pending',
      effectiveFrom: null,
      expiresAt: null,
      rowVersion: '1',
    })
    expect(
      decodeBreakGlassData({
        ...rawPending,
        status: 'approved',
        row_version: '2',
        effective_from: '2026-08-13T00:00:00+00:00',
        expires_at: '2026-08-13T01:00:00+00:00',
      }).status,
    ).toBe('approved')
  })

  it.each([
    ['额外字段', { extra: true }],
    ['非法申请 ID', { id: 'BG-1' }],
    ['非法角色', { target_role_code: 'read_only' }],
    ['超长时长', { requested_duration_seconds: 14_401 }],
    ['未知状态', { status: 'cancelled' }],
    ['非法版本', { row_version: '0' }],
    ['待审批却有生效时间', { effective_from: '2026-08-13T00:00:00Z' }],
  ])('拒绝%s', (_label, change) => {
    expect(() => decodeBreakGlassData({ ...rawPending, ...change })).toThrow()
  })

  it('发送创建、决定和撤销的 exact 幂等写请求', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => jsonResponse(rawPending))
    const api = new BreakGlassApi(new ApiClient({ fetcher }))

    await api.create(
      {
        targetUserId: userId,
        targetRoleCode: 'finance_reviewer',
        requestedDurationSeconds: 3600,
        reason: '处理紧急结算异常',
      },
      'request-key-1',
    )
    await api.decide(requestId, 'rejected', '材料不足', '1', 'decision-key-1')
    await api.revoke(requestId, '紧急事项已结束', '2', 'revoke-key-1')

    expect(fetcher.mock.calls.map((call) => String(call[0]))).toEqual([
      '/api/v1/break-glass-requests',
      `/api/v1/break-glass-requests/${requestId}/decision`,
      `/api/v1/break-glass-requests/${requestId}/revoke`,
    ])
    expect(fetcher.mock.calls.map((call) => call[1]?.method)).toEqual(['POST', 'POST', 'POST'])
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      target_user_id: userId,
      target_role_code: 'finance_reviewer',
      requested_duration_seconds: 3600,
      reason: '处理紧急结算异常',
    })
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      decision: 'rejected',
      reason: '材料不足',
      row_version: '1',
    })
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({
      reason: '紧急事项已结束',
      row_version: '2',
    })
    expect(new Headers(fetcher.mock.calls[2]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'revoke-key-1',
    )
  })

  it('非法目标、时长、原因和版本不会发送请求', async () => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new BreakGlassApi(new ApiClient({ fetcher }))

    await expect(
      api.create(
        {
          targetUserId: 'USER-1',
          targetRoleCode: 'finance_reviewer',
          requestedDurationSeconds: 3600,
          reason: '原因',
        },
        'request-key-1',
      ),
    ).rejects.toThrow()
    await expect(
      api.decide(requestId, 'approved', ' 有空格 ', '1', 'decision-key-1'),
    ).rejects.toThrow()
    await expect(api.revoke(requestId, '原因', '0', 'revoke-key-1')).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('BreakGlassPanel', () => {
  it('创建成功后显示真实申请并为后续 CAS 操作带入 ID 与版本', async () => {
    vi.spyOn(breakGlassApi, 'create').mockResolvedValue(pending)
    wrapper = mount(BreakGlassPanel, { props: { users: [] } })

    await wrapper.get('#break-glass-target').setValue(userId)
    await wrapper.get('#break-glass-reason').setValue('处理紧急结算异常')
    await wrapper.get('[data-testid="break-glass-create-form"]').trigger('submit')
    await flushPromises()

    expect(breakGlassApi.create).toHaveBeenCalledWith(
      {
        targetUserId: userId,
        targetRoleCode: 'finance_reviewer',
        requestedDurationSeconds: 3600,
        reason: '处理紧急结算异常',
      },
      expect.stringMatching(/^break-glass-request\.[0-9a-f-]{36}$/),
      expect.any(AbortSignal),
    )
    expect(wrapper.get('#break-glass-request-id').element).toHaveProperty('value', requestId)
    expect(wrapper.get('#break-glass-row-version').element).toHaveProperty('value', '1')
    expect(wrapper.text()).toContain('必须由独立审批人决定')
  })

  it('服务错误只显示安全文案与 Trace ID', async () => {
    vi.spyOn(breakGlassApi, 'create').mockRejectedValue(
      new ApiError({ code: 'SYNTHETIC', message: 'backend secret', status: 409, traceId }),
    )
    wrapper = mount(BreakGlassPanel, { props: { users: [] } })
    await wrapper.get('#break-glass-target').setValue(userId)
    await wrapper.get('#break-glass-reason').setValue('处理紧急结算异常')
    await wrapper.get('[data-testid="break-glass-create-form"]').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('双人控制资格冲突')
    expect(wrapper.text()).toContain(traceId)
    expect(wrapper.text()).not.toContain('backend secret')
  })
})
