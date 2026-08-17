import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/services/api'
import {
  AuthApi,
  authApi,
  decodeAuthSession,
  permissionCodes,
  type AuthSession,
} from '@/services/auth'
import { useAuthStore } from '@/stores/auth'

const traceId = '90000000-0000-4000-8000-000000000010'

const rawUser = {
  id: '90000000-0000-4000-8000-000000000011',
  display_name: '财务审核员',
  roles: ['finance_reviewer'],
  permissions: ['files.read', 'financial.read'],
}

const rawSession = {
  access_token: 'access-token',
  token_type: 'Bearer',
  expires_in: 900,
  user: rawUser,
}

const session: AuthSession = {
  accessToken: 'access-token',
  tokenType: 'Bearer',
  expiresIn: 900,
  user: {
    id: rawUser.id,
    displayName: rawUser.display_name,
    roles: ['finance_reviewer'],
    permissions: ['files.read', 'financial.read'],
  },
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(
    JSON.stringify({
      code: 'OK',
      message: 'success',
      data,
      trace_id: traceId,
      timestamp: '2026-08-12T00:00:00Z',
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
})

describe('Auth wire decoder', () => {
  it('严格映射登录和刷新返回的会话 DTO', () => {
    expect(decodeAuthSession(rawSession)).toEqual(session)
    expect(permissionCodes).toHaveLength(26)
  })

  it.each([
    { ...rawSession, token_type: 'bearer' },
    { ...rawSession, expires_in: 899 },
    { ...rawSession, user: { ...rawUser, roles: ['unknown_role'] } },
    { ...rawSession, user: { ...rawUser, permissions: ['unknown.permission'] } },
    { ...rawSession, user: { ...rawUser, permissions: ['files.read', 'files.read'] } },
    { ...rawSession, user: { ...rawUser, permissions: ['financial.read', 'files.read'] } },
    { ...rawSession, user: { ...rawUser, id: 'x' } },
    { ...rawSession, user: { ...rawUser, id: '90000000-0000-4000-8000-0000000000AB' } },
    { ...rawSession, user: { ...rawUser, id: rawUser.id.replaceAll('-', '') } },
  ])('拒绝漂移或重复的 Auth DTO：%o', (payload) => {
    expect(() => decodeAuthSession(payload)).toThrow()
  })
})

describe('AuthApi', () => {
  it('使用冻结端点、请求体、Cookie 凭据和一次性换密 Bearer', async () => {
    const requests: Array<{ path: string; init?: RequestInit }> = []
    const fetcher: typeof fetch = async (input, init) => {
      const path = String(input)
      requests.push({ path, init })
      if (path.endsWith('/auth/logout') || path.endsWith('/auth/password/change')) {
        return new Response(null, { status: 204, headers: { 'X-Trace-ID': traceId } })
      }
      return jsonResponse(path.endsWith('/auth/me') ? rawUser : rawSession)
    }
    const client = new ApiClient({ fetcher, getAccessToken: () => 'session-access-token' })
    const service = new AuthApi(client, new ApiClient({ fetcher }))

    await service.login({ username: 'reviewer', password: 'secret', rememberMe: true })
    await service.refresh()
    await service.getCurrentUser()
    await service.changePassword('password-change-token', 'new-secret')
    await service.logout()

    expect(requests.map(({ path }) => path)).toEqual([
      '/api/v1/auth/login',
      '/api/v1/auth/refresh',
      '/api/v1/auth/me',
      '/api/v1/auth/password/change',
      '/api/v1/auth/logout',
    ])
    expect(JSON.parse(String(requests[0]?.init?.body))).toEqual({
      username: 'reviewer',
      password: 'secret',
      remember_me: true,
    })
    expect(new Headers(requests[2]?.init?.headers).get('Authorization')).toBe(
      'Bearer session-access-token',
    )
    expect(new Headers(requests[3]?.init?.headers).get('Authorization')).toBe(
      'Bearer password-change-token',
    )
    expect(JSON.parse(String(requests[3]?.init?.body))).toEqual({ new_password: 'new-secret' })
    expect(requests.every(({ init }) => init?.credentials === 'same-origin')).toBe(true)
  })
})

describe('Auth Store', () => {
  it('页面刷新恢复共用一次 Refresh，并且 Token 与用户不写入 Web Storage', async () => {
    let resolveRefresh: ((value: AuthSession) => void) | undefined
    vi.spyOn(authApi, 'refresh').mockImplementation(
      () =>
        new Promise<AuthSession>((resolve) => {
          resolveRefresh = resolve
        }),
    )
    const auth = useAuthStore()

    const first = auth.restoreSession()
    const second = auth.restoreSession()
    expect(authApi.refresh).toHaveBeenCalledOnce()

    resolveRefresh?.(session)
    await Promise.all([first, second])

    expect(auth.initialized).toBe(true)
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.accessToken).toBe(session.accessToken)
    expect(auth.user).toEqual(session.user)
    expect(localStorage).toHaveLength(0)
    expect(sessionStorage).toHaveLength(0)
  })

  it('Refresh 失败时完成匿名初始化且不保留旧内存会话', async () => {
    vi.spyOn(authApi, 'refresh').mockRejectedValue(new Error('synthetic refresh failure'))
    const auth = useAuthStore()
    auth.setAuthenticatedSession(session.user, 'stale-token')
    auth.initialized = false

    await auth.restoreSession()

    expect(auth.initialized).toBe(true)
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.accessToken).toBeNull()
    expect(auth.user).toBeNull()
  })

  it('旧会话的延迟 CurrentUser 响应不得覆盖新会话', async () => {
    let resolveCurrentUser: ((value: AuthSession['user']) => void) | undefined
    vi.spyOn(authApi, 'getCurrentUser').mockImplementation(
      () =>
        new Promise<AuthSession['user']>((resolve) => {
          resolveCurrentUser = resolve
        }),
    )
    const auth = useAuthStore()
    auth.setAuthenticatedSession(session.user, 'old-access-token')
    const reload = auth.reloadCurrentUser()
    const nextUser: AuthSession['user'] = {
      id: '90000000-0000-4000-8000-000000000012',
      displayName: '新会话审计员',
      roles: ['audit_reviewer'],
      permissions: ['audits.read', 'risks.review_high'],
    }

    auth.setAuthenticatedSession(nextUser, 'new-access-token')
    resolveCurrentUser?.(session.user)
    await reload

    expect(auth.accessToken).toBe('new-access-token')
    expect(auth.user).toEqual(nextUser)
  })

  it('Logout 立即撤销会话，并在旧 Refresh 落定后补一次 Cookie 清理', async () => {
    let resolveRefresh: ((value: AuthSession) => void) | undefined
    const callOrder: string[] = []
    vi.spyOn(authApi, 'refresh').mockImplementation(
      () =>
        new Promise<AuthSession>((resolve) => {
          resolveRefresh = (value) => {
            callOrder.push('refresh-resolved')
            resolve(value)
          }
        }),
    )
    vi.spyOn(authApi, 'logout').mockImplementation(async () => {
      callOrder.push('logout-called')
    })
    const auth = useAuthStore()
    auth.setAuthenticatedSession(session.user, 'access-before-logout')
    auth.initialized = false

    const restoration = auth.restoreSession()
    expect(authApi.refresh).toHaveBeenCalledOnce()
    const logout = auth.signOut()

    expect(auth.isAuthenticated).toBe(false)
    await expect(logout).resolves.toBe(true)
    expect(callOrder).toEqual(['logout-called'])
    resolveRefresh?.({ ...session, accessToken: 'stale-refresh-result' })
    await restoration
    await vi.waitFor(() => expect(authApi.logout).toHaveBeenCalledTimes(2))

    expect(callOrder).toEqual(['logout-called', 'refresh-resolved', 'logout-called'])
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.accessToken).toBeNull()
    expect(auth.user).toBeNull()
  })

  it('Logout 中止未落定的 Refresh，并在远端 204 前保持撤销未确认提示', async () => {
    let releaseLogout: (() => void) | undefined
    vi.spyOn(authApi, 'refresh').mockImplementation(
      (signal) =>
        new Promise<AuthSession>((_resolve, reject) => {
          signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        }),
    )
    vi.spyOn(authApi, 'logout')
      .mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            releaseLogout = resolve
          }),
      )
      .mockResolvedValue()
    const auth = useAuthStore()
    auth.setAuthenticatedSession(session.user, 'access-before-logout')
    auth.initialized = false

    const restoration = auth.restoreSession()
    const logout = auth.signOut()

    expect(auth.isAuthenticated).toBe(false)
    expect(auth.remoteLogoutUnconfirmed).toBe(true)
    await vi.waitFor(() => expect(authApi.logout).toHaveBeenCalledOnce())
    releaseLogout?.()
    await Promise.all([restoration, logout])
    await vi.waitFor(() => expect(authApi.logout).toHaveBeenCalledTimes(2))

    expect(auth.remoteLogoutUnconfirmed).toBe(false)
    expect(auth.isAuthenticated).toBe(false)
  })

  it('Refresh 永不落定时，Logout 仍立即发出并完成', async () => {
    vi.spyOn(authApi, 'refresh').mockImplementation(
      () => new Promise<AuthSession>(() => undefined),
    )
    vi.spyOn(authApi, 'logout').mockResolvedValue()
    const auth = useAuthStore()
    auth.setAuthenticatedSession(session.user, 'access-before-logout')
    auth.initialized = false

    void auth.restoreSession()

    await expect(auth.signOut()).resolves.toBe(true)
    expect(authApi.logout).toHaveBeenCalledOnce()
    expect(auth.isAuthenticated).toBe(false)
    expect(auth.remoteLogoutUnconfirmed).toBe(false)
  })
})

describe('ApiClient 认证恢复', () => {
  it('并发 401 只刷新一次，并用新 Access Token 各重放一次', async () => {
    let accessToken = 'expired-token'
    const fetcher = vi.fn<typeof fetch>(async (_input, init) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      return authorization === 'Bearer fresh-token'
        ? jsonResponse({ accepted: true })
        : new Response(
            JSON.stringify({
              code: 'AUTH_ACCESS_EXPIRED',
              message: 'access expired',
              trace_id: traceId,
              timestamp: '2026-08-12T00:00:00Z',
            }),
            { status: 401, headers: { 'Content-Type': 'application/json' } },
          )
    })
    const refreshAccessToken = vi.fn(async () => {
      accessToken = 'fresh-token'
      return true
    })
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      refreshAccessToken,
    })

    await Promise.all([client.request('/contracts'), client.request('/invoices')])

    expect(refreshAccessToken).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledTimes(4)
  })

  it('迟到的旧 Token 401 复用已刷新的 Token，不再次旋转会话', async () => {
    let accessToken = 'expired-token'
    let releaseDelayedResponse: (() => void) | undefined
    const expiredResponse = () =>
      new Response(
        JSON.stringify({
          code: 'AUTH_ACCESS_EXPIRED',
          message: 'access expired',
          trace_id: traceId,
          timestamp: '2026-08-12T00:00:00Z',
        }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      )
    const fetcher: typeof fetch = (input, init) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      if (authorization === 'Bearer fresh-token') {
        return Promise.resolve(jsonResponse({ accepted: true }))
      }
      if (String(input).endsWith('/contracts')) {
        return new Promise<Response>((resolve) => {
          releaseDelayedResponse = () => resolve(expiredResponse())
        })
      }
      return Promise.resolve(expiredResponse())
    }
    const refreshAccessToken = vi.fn(async () => {
      accessToken = 'fresh-token'
      return true
    })
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      refreshAccessToken,
    })

    const delayedRequest = client.request('/contracts')
    await client.request('/invoices')
    releaseDelayedResponse?.()
    await delayedRequest

    expect(refreshAccessToken).toHaveBeenCalledOnce()
  })

  it('旧会话的迟到 401 不得用新会话 Token 重放或清理新会话', async () => {
    let accessToken = 'user-a-token'
    let generation = 1
    let releaseResponse: (() => void) | undefined
    const refreshAccessToken = vi.fn(async () => true)
    const onAuthenticationInvalid = vi.fn()
    const fetcher = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          releaseResponse = () =>
            resolve(
              new Response(
                JSON.stringify({
                  code: 'AUTH_ACCESS_EXPIRED',
                  message: 'access expired',
                  trace_id: traceId,
                  timestamp: '2026-08-12T00:00:00Z',
                }),
                { status: 401, headers: { 'Content-Type': 'application/json' } },
              ),
            )
        }),
    )
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      getSessionGeneration: () => generation,
      refreshAccessToken,
      onAuthenticationInvalid,
    })

    const oldRequest = client.request('/contracts')
    await vi.waitFor(() => expect(releaseResponse).toBeTypeOf('function'))
    generation = 2
    accessToken = 'user-b-token'
    releaseResponse?.()

    await expect(oldRequest).rejects.toMatchObject({ status: 401 })
    expect(fetcher).toHaveBeenCalledOnce()
    expect(refreshAccessToken).not.toHaveBeenCalled()
    expect(onAuthenticationInvalid).not.toHaveBeenCalled()
  })

  it('Refresh 返回后若会话 epoch 已推进，不得再以新会话重放原请求', async () => {
    let accessToken = 'user-a-token'
    let generation = 1
    const onAuthenticationInvalid = vi.fn()
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          code: 'AUTH_ACCESS_EXPIRED',
          message: 'access expired',
          trace_id: traceId,
          timestamp: '2026-08-12T00:00:00Z',
        }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const refreshAccessToken = vi.fn(async () => {
      generation = 2
      accessToken = 'user-b-token'
      return true
    })
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      getSessionGeneration: () => generation,
      refreshAccessToken,
      onAuthenticationInvalid,
    })

    await expect(client.request('/contracts')).rejects.toMatchObject({ status: 401 })
    expect(refreshAccessToken).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledOnce()
    expect(onAuthenticationInvalid).not.toHaveBeenCalled()
  })

  it('同一会话刷新后，旧 Token 的迟到终止撤销仍清理当前会话', async () => {
    let accessToken = 'old-token'
    const generation = 1
    let releaseResponse: (() => void) | undefined
    const onAuthenticationInvalid = vi.fn()
    const fetcher = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((resolve) => {
          releaseResponse = () =>
            resolve(
              new Response(
                JSON.stringify({
                  code: 'AUTH_TOKEN_REVOKED',
                  message: 'session revoked',
                  trace_id: traceId,
                  timestamp: '2026-08-12T00:00:00Z',
                }),
                { status: 401, headers: { 'Content-Type': 'application/json' } },
              ),
            )
        }),
    )
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      getSessionGeneration: () => generation,
      onAuthenticationInvalid,
    })

    const oldRequest = client.request('/contracts')
    await vi.waitFor(() => expect(releaseResponse).toBeTypeOf('function'))
    accessToken = 'refreshed-token'
    releaseResponse?.()

    await expect(oldRequest).rejects.toMatchObject({ code: 'AUTH_TOKEN_REVOKED' })
    expect(onAuthenticationInvalid).toHaveBeenCalledOnce()
  })

  it('无 Idempotency-Key 的写请求刷新会话但不自动重放', async () => {
    let accessToken = 'expired-token'
    const fetcher = vi.fn<typeof fetch>(async () =>
      new Response(
        JSON.stringify({
          code: 'AUTH_ACCESS_EXPIRED',
          message: 'access expired',
          trace_id: traceId,
          timestamp: '2026-08-12T00:00:00Z',
        }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    const refreshAccessToken = vi.fn(async () => {
      accessToken = 'fresh-token'
      return true
    })
    const onAuthenticationInvalid = vi.fn()
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      refreshAccessToken,
      onAuthenticationInvalid,
    })

    await expect(
      client.request('/contracts', { method: 'POST', body: { name: 'contract' } }),
    ).rejects.toMatchObject({ status: 401 })
    expect(refreshAccessToken).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledOnce()
    expect(onAuthenticationInvalid).not.toHaveBeenCalled()
  })

  it('带 Idempotency-Key 的写请求允许在刷新后重放一次', async () => {
    let accessToken = 'expired-token'
    const fetcher = vi.fn<typeof fetch>(async (_input, init) => {
      const authorization = new Headers(init?.headers).get('Authorization')
      return authorization === 'Bearer fresh-token'
        ? jsonResponse({ accepted: true })
        : new Response(
            JSON.stringify({
              code: 'AUTH_ACCESS_EXPIRED',
              message: 'access expired',
              trace_id: traceId,
              timestamp: '2026-08-12T00:00:00Z',
            }),
            { status: 401, headers: { 'Content-Type': 'application/json' } },
          )
    })
    const refreshAccessToken = vi.fn(async () => {
      accessToken = 'fresh-token'
      return true
    })
    const client = new ApiClient({
      fetcher,
      getAccessToken: () => accessToken,
      refreshAccessToken,
    })

    await client.request('/contracts', {
      method: 'POST',
      body: { name: 'contract' },
      idempotencyKey: 'create-contract-once',
    })

    expect(refreshAccessToken).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('刷新后仍为 401 时不进行第二次刷新并清理会话', async () => {
    const refreshAccessToken = vi.fn(async () => true)
    const onAuthenticationInvalid = vi.fn()
    const client = new ApiClient({
      fetcher: async () =>
        new Response(
          JSON.stringify({
            code: 'AUTH_ACCESS_EXPIRED',
            message: 'access expired',
            trace_id: traceId,
            timestamp: '2026-08-12T00:00:00Z',
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        ),
      getAccessToken: () => 'expired-token',
      refreshAccessToken,
      onAuthenticationInvalid,
    })

    await expect(client.request('/contracts')).rejects.toMatchObject({ status: 401 })
    expect(refreshAccessToken).toHaveBeenCalledOnce()
    expect(onAuthenticationInvalid).toHaveBeenCalledOnce()
  })
})
