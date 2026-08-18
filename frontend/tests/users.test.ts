import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError } from '@/services/api'
import {
  UserApi,
  decodeUserList,
  userApi,
  type UserListData,
} from '@/services/users'
import UserManagementView from '@/views/UserManagementView.vue'

const traceId = '90000000-0000-4000-8000-000000000010'
const userId = '10000000-0000-4000-8000-000000000001'
const rawUser = {
  id: userId,
  username: 'admin.ops',
  display_name: '平台运维管理员',
  status: 'active',
  fixed_roles: ['system_admin'],
  row_version: '9007199254740993',
}

function cursorFor(id: string, username: string): string {
  return btoa(JSON.stringify({ id, username, v: 1 }))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '')
}

const rawUsers = Array.from({ length: 20 }, (_value, index) => {
  const sequence = index + 1
  return {
    ...rawUser,
    id: `10000000-0000-4000-8000-${String(sequence).padStart(12, '0')}`,
    username: `user-${String(sequence).padStart(2, '0')}`,
    display_name: sequence === 1 ? '真实用户一' : `真实用户 ${sequence}`,
  }
})
const lastRawUser = rawUsers.at(-1)!
const firstPage = decodeUserList({
  items: rawUsers,
  page_size: 20,
  next_cursor: cursorFor(lastRawUser.id, lastRawUser.username),
})
const oneUserPage = decodeUserList({ items: [rawUser], page_size: 20, next_cursor: null })
const emptyPage: UserListData = { items: [], pageSize: 20, nextCursor: null }

let wrapper: VueWrapper | undefined

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
})

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

async function mountPage(): Promise<VueWrapper> {
  wrapper = mount(UserManagementView)
  await flushPromises()
  return wrapper
}

describe('UserApi', () => {
  it('只发送 page_size 与 canonical cursor，并严格解码六字段', async () => {
    const cursor = cursorFor(userId, rawUser.username)
    const fetcher = vi.fn<typeof fetch>(async () =>
      jsonResponse({ items: [rawUser], page_size: 50, next_cursor: null }),
    )
    const api = new UserApi(new ApiClient({ fetcher }))

    await expect(api.list(50, cursor)).resolves.toEqual({
      items: [
        {
          id: userId,
          username: 'admin.ops',
          displayName: '平台运维管理员',
          status: 'active',
          fixedRoles: ['system_admin'],
          rowVersion: '9007199254740993',
        },
      ],
      pageSize: 50,
      nextCursor: null,
    })
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      `/api/v1/users?page_size=50&cursor=${cursor}`,
    )
    expect(fetcher.mock.calls[0]?.[1]).not.toMatchObject({
      headers: expect.objectContaining({ 'Idempotency-Key': expect.anything() }),
    })
  })

  it.each([
    ['非 canonical UUID', { id: 'USER-001' }],
    ['大写用户名', { username: 'Admin.Ops' }],
    ['超长用户名', { username: `a${'b'.repeat(100)}` }],
    ['非字符串显示名', { display_name: null }],
    ['未知状态', { status: 'archived' }],
    ['未知固定角色', { fixed_roles: ['owner'] }],
    ['固定角色非 ASCII 升序', { fixed_roles: ['system_admin', 'audit_reviewer'] }],
    ['重复固定角色', { fixed_roles: ['read_only', 'read_only'] }],
    ['非正整数字符串版本', { row_version: '0' }],
    ['额外敏感字段', { email: 'secret@example.invalid' }],
  ])('拒绝列表项的%s', (_label, change) => {
    expect(() =>
      decodeUserList({
        items: [{ ...rawUser, ...change }],
        page_size: 20,
        next_cursor: null,
      }),
    ).toThrow()
  })

  it('接受数据库允许且按 ASCII 排序的多固定角色投影', () => {
    expect(
      decodeUserList({
        items: [{ ...rawUser, fixed_roles: ['audit_reviewer', 'contract_admin'] }],
        page_size: 20,
        next_cursor: null,
      }).items[0]?.fixedRoles,
    ).toEqual(['audit_reviewer', 'contract_admin'])
  })

  it('拒绝多余列表字段、重复用户和非法分页关系', () => {
    expect(() =>
      decodeUserList({ items: [rawUser], page_size: 20, next_cursor: null, total: 1 }),
    ).toThrow()
    expect(() =>
      decodeUserList({ items: [rawUser, rawUser], page_size: 20, next_cursor: null }),
    ).toThrow('duplicate')
    expect(() =>
      decodeUserList({ items: [rawUser], page_size: 0, next_cursor: null }),
    ).toThrow()
    expect(() =>
      decodeUserList({
        items: [rawUser, { ...rawUser, id: '10000000-0000-4000-8000-000000000002' }],
        page_size: 1,
        next_cursor: null,
      }),
    ).toThrow('page size')
    expect(() =>
      decodeUserList({
        items: [rawUser],
        page_size: 20,
        next_cursor: cursorFor(userId, rawUser.username),
      }),
    ).toThrow('page size')
  })

  it('只接受 exact canonical cursor，且 next_cursor 必须指向本页末项', async () => {
    const canonical = cursorFor(userId, rawUser.username)
    const noncanonicalJson = btoa(
      JSON.stringify({ v: 1, username: rawUser.username, id: userId }),
    ).replace(/=+$/, '')
    const unknownKey = btoa(
      JSON.stringify({ id: userId, username: rawUser.username, v: 1, extra: true }),
    ).replace(/=+$/, '')
    const fetcher = vi.fn<typeof fetch>()
    const api = new UserApi(new ApiClient({ fetcher }))

    await expect(api.list(20, canonical)).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
    expect(fetcher).toHaveBeenCalledOnce()
    fetcher.mockClear()

    for (const cursor of ['', 'has-padding=', '含中文', 'A', noncanonicalJson, unknownKey]) {
      await expect(api.list(20, cursor)).rejects.toThrow('invalid user cursor')
    }
    expect(fetcher).not.toHaveBeenCalled()

    expect(() =>
      decodeUserList({
        items: Array.from({ length: 20 }, (_value, index) => ({
          ...rawUser,
          id: `10000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
        })),
        page_size: 20,
        next_cursor: cursorFor('10000000-0000-4000-8000-000000000999', rawUser.username),
      }),
    ).toThrow('does not match')
  })

  it.each([0, 101, 1.5])('拒绝非法 page_size=%s 且不发请求', async (pageSize) => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new UserApi(new ApiClient({ fetcher }))

    await expect(api.list(pageSize)).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('拒绝响应 page_size 与请求不一致', async () => {
    const api = new UserApi(
      new ApiClient({
        fetcher: async () => jsonResponse({ items: [], page_size: 20, next_cursor: null }),
      }),
    )

    await expect(api.list(50)).rejects.toThrow('page size does not match')
  })

  it('用户写请求携带幂等键、字符串版本与 exact 请求体', async () => {
    const fetcher = vi.fn<typeof fetch>(async () => jsonResponse(rawUser))
    const api = new UserApi(new ApiClient({ fetcher }))

    await api.create(
      {
        username: 'new.user',
        displayName: '新用户',
        initialPassword: 'Initial-Passphrase-123!',
        fixedRoles: ['read_only'],
      },
      'create-key-1',
    )
    await api.updateStatus(userId, 'disabled', '9007199254740993', 'status-key-1')
    await api.resetPassword(
      userId,
      'Replacement-Passphrase-123!',
      '9007199254740993',
      'password-key-1',
    )
    await api.replaceRoles(
      userId,
      ['audit_reviewer', 'contract_admin'],
      '9007199254740993',
      'roles-key-1',
    )

    expect(fetcher).toHaveBeenCalledTimes(4)
    expect(String(fetcher.mock.calls[0]?.[0])).toBe('/api/v1/users')
    expect(String(fetcher.mock.calls[1]?.[0])).toBe(`/api/v1/users/${userId}/status`)
    expect(String(fetcher.mock.calls[2]?.[0])).toBe(
      `/api/v1/users/${userId}/password/reset`,
    )
    expect(String(fetcher.mock.calls[3]?.[0])).toBe(`/api/v1/users/${userId}/roles`)
    expect(fetcher.mock.calls.map((call) => call[1]?.method)).toEqual([
      'POST',
      'PATCH',
      'POST',
      'PUT',
    ])
    expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'create-key-1',
    )
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      username: 'new.user',
      display_name: '新用户',
      initial_password: 'Initial-Passphrase-123!',
      fixed_roles: ['read_only'],
    })
    expect(JSON.parse(String(fetcher.mock.calls[1]?.[1]?.body))).toEqual({
      status: 'disabled',
      row_version: '9007199254740993',
    })
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({
      new_password: 'Replacement-Passphrase-123!',
      row_version: '9007199254740993',
    })
    expect(JSON.parse(String(fetcher.mock.calls[3]?.[1]?.body))).toEqual({
      fixed_roles: ['audit_reviewer', 'contract_admin'],
      row_version: '9007199254740993',
    })
  })

  it('用户写入的非法本地参数不会发出请求', async () => {
    const fetcher = vi.fn<typeof fetch>()
    const api = new UserApi(new ApiClient({ fetcher }))

    await expect(
      api.create(
        {
          username: 'INVALID',
          displayName: '用户',
          initialPassword: 'password',
          fixedRoles: ['read_only'],
        },
        'create-key-1',
      ),
    ).rejects.toThrow()
    await expect(
      api.replaceRoles(
        userId,
        ['system_admin', 'audit_reviewer'],
        '9007199254740993',
        'roles-key-1',
      ),
    ).rejects.toThrow()
    await expect(
      api.updateStatus('not-a-uuid', 'active', '1', 'status-key-1'),
    ).rejects.toThrow()
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('UserManagementView', () => {
  it('展示真实六字段与已接入写入口，不再展示 Demo 或未接入占位', async () => {
    vi.spyOn(userApi, 'list').mockResolvedValue(oneUserPage)
    const page = await mountPage()

    expect(page.text()).toContain('平台运维管理员')
    expect(page.text()).toContain('admin.ops')
    expect(page.text()).toContain('系统管理员')
    expect(page.text()).toContain('9007199254740993')
    expect(page.find('[data-testid="create-user-form"]').exists()).toBe(true)
    expect(page.get(`[data-testid="manage-user-${userId}"]`).text()).toBe('管理')
    expect(page.text()).not.toContain('未接入')
    expect(page.text()).not.toContain('admin.ops@example.invalid')
    expect(page.text()).not.toContain('BG-2026-0018')
    expect(page.find('#user-keyword').exists()).toBe(false)
    expect(page.find('#create-password').attributes('autocomplete')).toBe('new-password')
    expect(page.find('#create-password').attributes('minlength')).toBe('6')
    expect(page.text()).toContain('密码至少 6 个字符')
  })

  it('使用当前字符串版本提交状态变更，并以服务端返回版本更新页面', async () => {
    vi.spyOn(userApi, 'list').mockResolvedValue(oneUserPage)
    vi.spyOn(userApi, 'updateStatus').mockResolvedValue({
      id: userId,
      username: 'admin.ops',
      displayName: '平台运维管理员',
      status: 'disabled',
      fixedRoles: ['system_admin'],
      rowVersion: '9007199254740994',
    })
    const page = await mountPage()

    await page.get(`[data-testid="manage-user-${userId}"]`).trigger('click')
    await page.get('#edit-status').setValue('disabled')
    await page.get('[data-testid="user-status-form"]').trigger('submit')
    await flushPromises()

    expect(userApi.updateStatus).toHaveBeenCalledWith(
      userId,
      'disabled',
      '9007199254740993',
      expect.stringMatching(/^user-status\.[0-9a-f-]{36}$/),
      expect.any(AbortSignal),
    )
    expect(page.text()).toContain('9007199254740994')
    expect(page.text()).toContain('用户状态已更新')
  })

  it('展示独立空态', async () => {
    vi.spyOn(userApi, 'list').mockResolvedValue(emptyPage)
    const page = await mountPage()

    expect(page.text()).toContain('当前页没有用户。')
  })

  it('使用 opaque cursor 前后翻页，失败重试保持同一 cursor', async () => {
    vi.spyOn(userApi, 'list')
      .mockResolvedValueOnce(firstPage)
      .mockRejectedValueOnce(new Error('synthetic secret'))
      .mockResolvedValueOnce(emptyPage)
      .mockResolvedValueOnce(firstPage)
    const page = await mountPage()
    const cursor = firstPage.nextCursor!

    await page.get('button[aria-label="下一页"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('用户列表加载失败，请稍后重试。')
    expect(page.text()).not.toContain('synthetic secret')

    await page.get('[data-testid="retry-user-list"]').trigger('click')
    await flushPromises()
    expect(userApi.list).toHaveBeenNthCalledWith(3, 20, cursor, expect.any(AbortSignal))
    expect(page.text()).toContain('第 2 页 · 每页 20 条')

    await page.get('button[aria-label="上一页"]').trigger('click')
    await flushPromises()
    expect(userApi.list).toHaveBeenNthCalledWith(4, 20, undefined, expect.any(AbortSignal))
    expect(page.text()).toContain('真实用户一')
  })

  it.each([
    [401, '登录状态已失效，请重新登录。'],
    [403, '当前账号无权读取用户列表。'],
    [500, '用户列表加载失败，请稍后重试。'],
  ])('%i 错误只显示安全文案、Trace ID 并允许重试', async (status, message) => {
    vi.spyOn(userApi, 'list')
      .mockRejectedValueOnce(
        new ApiError({ code: 'SYNTHETIC', message: 'backend secret', status, traceId }),
      )
      .mockResolvedValueOnce(oneUserPage)
    const page = await mountPage()

    expect(page.text()).toContain(message)
    expect(page.text()).toContain(traceId)
    expect(page.text()).not.toContain('backend secret')
    await page.get('[data-testid="retry-user-list"]').trigger('click')
    await flushPromises()
    expect(page.text()).toContain('平台运维管理员')
  })

  it('快速重复翻页会中止旧请求并忽略无视 Abort 的迟到响应', async () => {
    let oldSignal: AbortSignal | undefined
    let resolveOld: ((value: UserListData) => void) | undefined
    const oldPage = decodeUserList({
      items: [{ ...rawUser, display_name: '迟到旧用户' }],
      page_size: 20,
      next_cursor: null,
    })
    const newPage = decodeUserList({
      items: [{ ...rawUser, display_name: '最新用户' }],
      page_size: 20,
      next_cursor: null,
    })
    vi.spyOn(userApi, 'list')
      .mockResolvedValueOnce(firstPage)
      .mockImplementationOnce((_pageSize, _cursor, signal) => {
        oldSignal = signal
        return new Promise<UserListData>((resolve) => {
          resolveOld = resolve
        })
      })
      .mockResolvedValueOnce(newPage)
    const page = await mountPage()
    const next = page.get('button[aria-label="下一页"]')

    await Promise.all([next.trigger('click'), next.trigger('click')])
    await flushPromises()
    expect(oldSignal?.aborted).toBe(true)
    expect(page.text()).toContain('最新用户')
    resolveOld?.(oldPage)
    await flushPromises()
    expect(page.text()).toContain('最新用户')
    expect(page.text()).not.toContain('迟到旧用户')
  })

  it('卸载时中止未完成请求', async () => {
    let requestSignal: AbortSignal | undefined
    vi.spyOn(userApi, 'list').mockImplementation((_pageSize, _cursor, signal) => {
      requestSignal = signal
      return new Promise<UserListData>(() => undefined)
    })
    const page = await mountPage()

    expect(page.text()).toContain('正在加载用户列表…')
    page.unmount()
    wrapper = undefined
    expect(requestSignal?.aborted).toBe(true)
  })
})
