import { describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError } from '@/services/api'

const traceId = '90000000-0000-0000-0000-000000000001'

function jsonResponse(
  payload: unknown,
  status = 200,
  additionalHeaders: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json', ...additionalHeaders },
  })
}

function successResponse(data: unknown): Response {
  return jsonResponse({
    code: 'OK',
    message: 'success',
    data,
    trace_id: traceId,
    timestamp: '2026-08-05T05:00:00Z',
  })
}

describe('ApiClient', () => {
  it('默认 Fetch 保留浏览器全局 receiver', async () => {
    const originalFetch = globalThis.fetch
    let receiver: unknown
    globalThis.fetch = (async function (this: unknown) {
      receiver = this
      return successResponse({})
    }) as typeof fetch

    try {
      const client = new ApiClient()
      await client.request('/health')
      expect(receiver).toBe(globalThis)
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('统一附加 Bearer、调用方幂等键和 row_version', async () => {
    const requests: Array<{ input: RequestInfo | URL; init?: RequestInit }> = []
    const fetcher: typeof fetch = async (input, init) => {
      requests.push({ input, init })
      return successResponse({ id: 'contract-1' })
    }
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => 'unit-test-token',
    })

    const options = {
      method: 'PATCH' as const,
      body: { reason: '字段修正' },
      idempotencyKey: 'same-operation-key',
      rowVersion: 3,
    }
    await client.request('/contracts/contract-1', options)
    await client.request('/contracts/contract-1', options)

    expect(requests).toHaveLength(2)
    for (const request of requests) {
      const headers = new Headers(request.init?.headers)
      expect(request.input).toBe('/api/v1/contracts/contract-1')
      expect(headers.get('Authorization')).toBe('Bearer unit-test-token')
      expect(headers.get('Idempotency-Key')).toBe('same-operation-key')
      expect(JSON.parse(String(request.init?.body))).toEqual({
        reason: '字段修正',
        row_version: 3,
      })
    }
  })

  it('FormData 请求删除调用方 Content-Type 以保留浏览器 multipart boundary', async () => {
    let capturedInit: RequestInit | undefined
    const formData = new FormData()
    formData.set('file', new Blob(['synthetic-file']), 'sample.pdf')
    const client = new ApiClient({
      fetcher: async (_input, init) => {
        capturedInit = init
        return successResponse({ accepted: true })
      },
    })

    await client.request('/files', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: formData,
    })

    expect(capturedInit?.body).toBe(formData)
    expect(new Headers(capturedInit?.headers).has('Content-Type')).toBe(false)
  })

  it('将统一错误响应映射为包含 Trace ID 的 ApiError', async () => {
    const fetcher: typeof fetch = async () =>
      jsonResponse(
        {
          code: 'RESOURCE_VERSION_CONFLICT',
          message: '资源已被其他用户修改，请刷新后重试',
          details: [{ field: 'row_version', reason: 'version mismatch' }],
          trace_id: traceId,
          timestamp: '2026-08-05T05:00:00Z',
        },
        409,
      )
    const client = new ApiClient({ fetcher })

    const request = client.request('/contracts/contract-1')

    await expect(request).rejects.toMatchObject({
      name: 'ApiError',
      code: 'RESOURCE_VERSION_CONFLICT',
      message: '资源已被其他用户修改，请刷新后重试',
      details: [{ field: 'row_version', reason: 'version mismatch' }],
      status: 409,
      traceId,
    })
  })

  it('普通错误拒绝非法响应体 Trace ID 并使用合法响应头回退', async () => {
    const client = new ApiClient({
      fetcher: async () =>
        jsonResponse(
          {
            code: 'RESOURCE_VERSION_CONFLICT',
            message: '资源已被其他用户修改，请刷新后重试',
            trace_id: 'not-a-uuid',
            timestamp: '2026-08-05T05:00:00Z',
          },
          409,
          { 'X-Trace-ID': traceId },
        ),
    })

    await expect(client.request('/contracts/contract-1')).rejects.toMatchObject({
      code: 'RESOURCE_VERSION_CONFLICT',
      traceId,
    })
  })

  it.each(['not-a-uuid', 'AAAAAAAA-0000-0000-0000-000000000001'])(
    '成功响应拒绝非标准小写 UUID Trace ID：%s',
    async (invalidTraceId) => {
      const client = new ApiClient({
        fetcher: async () =>
          jsonResponse(
            {
              code: 'OK',
              message: 'success',
              data: { id: 'contract-1' },
              trace_id: invalidTraceId,
              timestamp: '2026-08-05T05:00:00Z',
            },
            200,
            { 'X-Trace-ID': invalidTraceId },
          ),
      })

      await expect(client.request('/contracts/contract-1')).rejects.toMatchObject({
        code: 'API_RESPONSE_INVALID',
        traceId: '',
      })
    },
  )

  it('保留强制换密错误的受限 data，供客户端进入唯一允许的换密流程', async () => {
    const onAuthenticationInvalid = vi.fn()
    const fetcher: typeof fetch = async () =>
      jsonResponse(
        {
          code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
          message: '首次登录必须修改密码',
          data: {
            password_change_token: 'synthetic-password-change-token',
            expires_in: 300,
          },
          trace_id: traceId,
          timestamp: '2026-08-05T05:00:00Z',
        },
        403,
      )
    const client = new ApiClient({ fetcher, onAuthenticationInvalid })

    const error = await client
      .request('/auth/login', { method: 'POST' })
      .then(() => null)
      .catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
      data: {
        passwordChangeToken: 'synthetic-password-change-token',
        expiresIn: 300,
      },
      status: 403,
      traceId,
    })
    expect(JSON.stringify(error)).not.toContain('synthetic-password-change-token')
    expect(onAuthenticationInvalid).not.toHaveBeenCalled()
  })

  it('强制换密错误只在不可枚举 data 中保留受限 Token', async () => {
    const restrictedToken = 'sensitive-password-change-token'
    const client = new ApiClient({
      fetcher: async () =>
        jsonResponse(
          {
            code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
            message: `不得记录 ${restrictedToken}`,
            data: {
              password_change_token: restrictedToken,
              expires_in: 300,
            },
            details: { echoed_value: restrictedToken },
            trace_id: restrictedToken,
            timestamp: '2026-08-05T05:00:00Z',
          },
          403,
        ),
    })

    const error = await client
      .request('/auth/login', { method: 'POST' })
      .then(() => null)
      .catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
      data: {
        passwordChangeToken: restrictedToken,
        expiresIn: 300,
      },
      details: undefined,
      traceId: '',
    })
    expect(String(error)).not.toContain(restrictedToken)
    expect(JSON.stringify(error)).not.toContain(restrictedToken)
    expect((error as Error).stack ?? '').not.toContain(restrictedToken)
  })

  it.each([
    ['响应体 Trace ID', true],
    ['响应头 Trace ID', false],
  ])('%s 不得复用 UUID 形态的换密 Token', async (_caseName, useBodyTrace) => {
    const restrictedToken = '91000000-0000-4000-8000-000000000001'
    const client = new ApiClient({
      fetcher: async () =>
        jsonResponse(
          {
            code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
            message: '首次登录必须修改密码',
            data: {
              password_change_token: restrictedToken,
              expires_in: 300,
            },
            trace_id: useBodyTrace ? restrictedToken : 'invalid-trace-id',
            timestamp: '2026-08-05T05:00:00Z',
          },
          403,
          useBodyTrace ? {} : { 'X-Trace-ID': restrictedToken },
        ),
    })

    const error = await client
      .request('/auth/login', { method: 'POST' })
      .then(() => null)
      .catch((caught: unknown) => caught)

    expect(error).toMatchObject({
      code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
      data: {
        passwordChangeToken: restrictedToken,
        expiresIn: 300,
      },
      traceId: '',
    })
    expect(String(error)).not.toContain(restrictedToken)
    expect(JSON.stringify(error)).not.toContain(restrictedToken)
    expect((error as Error).stack ?? '').not.toContain(restrictedToken)
  })

  it('将缺少受限 Token 的强制换密错误拒绝为响应契约错误', async () => {
    const client = new ApiClient({
      fetcher: async () =>
        jsonResponse(
          {
            code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
            message: '首次登录必须修改密码',
            data: { expires_in: 300 },
            trace_id: traceId,
            timestamp: '2026-08-05T05:00:00Z',
          },
          403,
        ),
    })

    await expect(client.request('/auth/login', { method: 'POST' })).rejects.toMatchObject({
      code: 'API_RESPONSE_INVALID',
      status: 403,
      traceId,
    })
  })

  it.each([
    ['非登录接口', '/contracts'],
    ['错误方法的登录接口', '/auth/login'],
  ])('%s的强制换密错误不保留或回显受限 Token', async (_caseName, path) => {
    const restrictedToken = 'must-not-be-retained'
    const client = new ApiClient({
      fetcher: async () =>
        jsonResponse(
          {
            code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
            message: `必须先完成密码修改 ${restrictedToken}`,
            data: {
              password_change_token: restrictedToken,
              expires_in: 300,
            },
            details: { echoed_value: restrictedToken },
            trace_id: restrictedToken,
            timestamp: '2026-08-05T05:00:00Z',
          },
          403,
        ),
    })

    const error = await client
      .request(path)
      .then(() => null)
      .catch((caught: unknown) => caught)

    expect(error).toMatchObject({
      code: 'AUTH_PASSWORD_CHANGE_REQUIRED',
      data: undefined,
      details: undefined,
      message: '首次登录必须修改密码。',
      status: 403,
      traceId: '',
    })
    expect(String(error)).not.toContain(restrictedToken)
    expect(JSON.stringify(error)).not.toContain(restrictedToken)
    expect((error as Error).stack ?? '').not.toContain(restrictedToken)
  })

  it('认证失效时触发会话清理入口', async () => {
    const onAuthenticationInvalid = vi.fn()
    const fetcher: typeof fetch = async () =>
      jsonResponse(
        {
          code: 'AUTH_TOKEN_REVOKED',
          message: '登录状态已失效',
          trace_id: traceId,
          timestamp: '2026-08-05T05:00:00Z',
        },
        401,
      )
    const client = new ApiClient({ fetcher, onAuthenticationInvalid })

    await expect(client.request('/auth/me')).rejects.toBeInstanceOf(ApiError)
    expect(onAuthenticationInvalid).toHaveBeenCalledOnce()
  })

  it('匿名登录凭据错误不会误触发已有会话清理入口', async () => {
    const onAuthenticationInvalid = vi.fn()
    const client = new ApiClient({
      fetcher: async () =>
        jsonResponse(
          {
            code: 'AUTH_INVALID_CREDENTIALS',
            message: '用户名或密码错误',
            trace_id: traceId,
            timestamp: '2026-08-05T05:00:00Z',
          },
          401,
        ),
      onAuthenticationInvalid,
    })

    await expect(client.request('/auth/login', { method: 'POST' })).rejects.toMatchObject({
      code: 'AUTH_INVALID_CREDENTIALS',
      status: 401,
    })
    expect(onAuthenticationInvalid).not.toHaveBeenCalled()
  })

  it('显式 no-content 请求接受 HTTP 204 无响应体', async () => {
    const client = new ApiClient({
      fetcher: async () =>
        new Response(null, {
          status: 204,
          headers: { 'X-Trace-ID': traceId },
        }),
    })

    await expect(
      client.request('/auth/logout', { method: 'POST', expectNoContent: true }),
    ).resolves.toBeUndefined()
  })

  it('JSON 请求收到 HTTP 204 时保留 Trace ID 并拒绝静默吞掉契约漂移', async () => {
    const client = new ApiClient({
      fetcher: async () =>
        new Response(null, {
          status: 204,
          headers: { 'X-Trace-ID': traceId },
        }),
    })

    await expect(client.request('/auth/logout', { method: 'POST' })).rejects.toMatchObject({
      code: 'API_RESPONSE_INVALID',
      status: 204,
      traceId,
    })
  })

  it('no-content 请求收到带 JSON 的成功响应时拒绝契约漂移', async () => {
    const client = new ApiClient({ fetcher: async () => successResponse({}) })

    await expect(
      client.request('/auth/logout', { method: 'POST', expectNoContent: true }),
    ).rejects.toMatchObject({
      code: 'API_RESPONSE_INVALID',
      status: 200,
      traceId,
    })
  })

  it('将业务数据解码失败归类为响应契约错误并保留 Trace ID', async () => {
    const client = new ApiClient({ fetcher: async () => successResponse({ id: 123 }) })

    const request = client.request('/contracts/contract-1', {
      decode: () => {
        throw new TypeError('invalid contract payload')
      },
    })

    await expect(request).rejects.toMatchObject({
      name: 'ApiError',
      code: 'API_RESPONSE_INVALID',
      status: 200,
      traceId,
    })
  })

  it('拒绝绕过 /api/v1 的外部 URL', async () => {
    const client = new ApiClient({ fetcher: vi.fn() })

    await expect(client.request('https://example.invalid/data')).rejects.toThrow(
      'API path 必须是以单个 / 开头的站内路径。',
    )
  })

  it('拒绝把 API 基址改到站外并在请求前终止', () => {
    const fetcher = vi.fn()

    expect(
      () =>
        new ApiClient({
          baseUrl: 'https://qdrant.example.invalid',
          fetcher,
          getAccessToken: () => 'synthetic-token',
        }),
    ).toThrow('API base URL 必须固定为同源 /api/v1。')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('接受后端返回的完整同源 /api/v1 Job 路径且不重复添加前缀', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => successResponse({ status: 'queued' }))
    const client = new ApiClient({ fetcher })

    await client.request('/api/v1/jobs/70000000-0000-0000-0000-000000000001')

    expect(fetcher).toHaveBeenCalledWith(
      '/api/v1/jobs/70000000-0000-0000-0000-000000000001',
      expect.any(Object),
    )
  })

  it.each([
    '/../../health',
    '/contracts/%2e%2e/%2e%2e/health',
    '/contracts\\..\\health',
    '/contracts/%2e%2e%2f%2e%2e%2fhealth',
    '/contracts/%2e%2e%5c%2e%2e%5chealth',
    '/contracts/%252e%252e%252fhealth',
  ])(
    '拒绝逃出 /api/v1 的路径 %s，并且不发送请求',
    async (path) => {
      const fetcher = vi.fn()
      const client = new ApiClient({ fetcher })

      await expect(client.request(path)).rejects.toThrow(
        'API path 必须保留在同源 /api/v1 下。',
      )
      expect(fetcher).not.toHaveBeenCalled()
    },
  )
})
