import { ApiClient, UUID_PATTERN, apiClient } from './api'
import { roleCodes, type RoleCode } from './auth'

export const userStatuses = ['active', 'disabled', 'locked'] as const

export type UserStatus = (typeof userStatuses)[number]

export interface UserListItem {
  id: string
  username: string
  displayName: string
  status: UserStatus
  fixedRoles: RoleCode[]
  rowVersion: string
}

export interface UserListData {
  items: UserListItem[]
  pageSize: number
  nextCursor: string | null
}

export interface UserCreateInput {
  username: string
  displayName: string
  initialPassword: string
  fixedRoles: RoleCode[]
}

interface UserCursor {
  id: string
  username: string
}

const usernamePattern = /^[a-z0-9][a-z0-9._-]{0,99}$/
const positiveIntegerPattern = /^[1-9]\d*$/
const cursorPattern = /^[A-Za-z0-9_-]+$/
const itemKeys = [
  'id',
  'username',
  'display_name',
  'status',
  'fixed_roles',
  'row_version',
] as const
const listKeys = ['items', 'page_size', 'next_cursor'] as const
const cursorKeys = ['id', 'username', 'v'] as const
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/
const positiveRowVersionPattern = /^[1-9]\d*$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actualKeys = Object.keys(value)
  return actualKeys.length === keys.length && keys.every((key) => key in value)
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === 'string' && allowed.some((candidate) => candidate === value)
}

function encodeBase64Url(value: string): string {
  return btoa(value).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

function decodeCursor(value: unknown): UserCursor {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 256 ||
    !cursorPattern.test(value)
  ) {
    throw new TypeError('invalid user cursor')
  }

  try {
    const base64 = value.replaceAll('-', '+').replaceAll('_', '/')
    const binary = atob(base64 + '='.repeat(-base64.length & 3))
    if (encodeBase64Url(binary) !== value) throw new TypeError('noncanonical base64url')

    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    const payload: unknown = JSON.parse(text)
    if (
      !isRecord(payload) ||
      !hasExactKeys(payload, cursorKeys) ||
      payload.v !== 1 ||
      typeof payload.id !== 'string' ||
      !UUID_PATTERN.test(payload.id) ||
      typeof payload.username !== 'string' ||
      !usernamePattern.test(payload.username)
    ) {
      throw new TypeError('invalid user cursor payload')
    }
    const canonical = JSON.stringify({ id: payload.id, username: payload.username, v: 1 })
    if (encodeBase64Url(canonical) !== value) throw new TypeError('noncanonical user cursor')
    return { id: payload.id, username: payload.username }
  } catch {
    throw new TypeError('invalid user cursor')
  }
}

export function decodeUserListItem(value: unknown): UserListItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, itemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.username !== 'string' ||
    !usernamePattern.test(value.username) ||
    typeof value.display_name !== 'string' ||
    !isOneOf(value.status, userStatuses) ||
    !Array.isArray(value.fixed_roles) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid user list item')
  }

  const fixedRoles: RoleCode[] = []
  for (const role of value.fixed_roles) {
    if (!isOneOf(role, roleCodes) || (fixedRoles.length > 0 && fixedRoles.at(-1)! >= role)) {
      throw new TypeError('invalid fixed role order')
    }
    fixedRoles.push(role)
  }

  return {
    id: value.id,
    username: value.username,
    displayName: value.display_name,
    status: value.status,
    fixedRoles,
    rowVersion: value.row_version,
  }
}

export function decodeUserList(value: unknown): UserListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null && typeof value.next_cursor !== 'string')
  ) {
    throw new TypeError('invalid user list')
  }

  const items = value.items.map(decodeUserListItem)
  const pageSize = Number(value.page_size)
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid user list page size')
  }

  const ids = new Set<string>()
  for (const item of items) {
    if (ids.has(item.id)) throw new TypeError('duplicate user list item')
    ids.add(item.id)
  }

  if (value.next_cursor !== null) {
    const cursor = decodeCursor(value.next_cursor)
    const lastItem = items.at(-1)!
    if (cursor.id !== lastItem.id || cursor.username !== lastItem.username) {
      throw new TypeError('user cursor does not match the last item')
    }
  }

  return { items, pageSize, nextCursor: value.next_cursor }
}

export class UserApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<UserListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }
    if (cursor !== undefined) decodeCursor(cursor)

    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(
      `/users?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeUserList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('user list page size does not match request')
    }
    return response.data
  }

  async create(
    input: UserCreateInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<UserListItem> {
    requireIdempotencyKey(idempotencyKey)
    requireUsername(input.username)
    requireDisplayName(input.displayName)
    requirePassword(input.initialPassword)
    requireFixedRoles(input.fixedRoles)

    const response = await this.client.request('/users', {
      method: 'POST',
      idempotencyKey,
      signal,
      body: {
        username: input.username,
        display_name: input.displayName,
        initial_password: input.initialPassword,
        fixed_roles: input.fixedRoles,
      },
      decode: decodeUserListItem,
    })
    return response.data
  }

  async updateStatus(
    userId: string,
    status: Extract<UserStatus, 'active' | 'disabled'>,
    rowVersion: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<UserListItem> {
    requireUserMutation(userId, rowVersion, idempotencyKey)
    if (status !== 'active' && status !== 'disabled') throw new TypeError('invalid user status')

    const response = await this.client.request(`/users/${userId}/status`, {
      method: 'PATCH',
      idempotencyKey,
      signal,
      body: { status, row_version: rowVersion },
      decode: decodeUserListItem,
    })
    return response.data
  }

  async resetPassword(
    userId: string,
    newPassword: string,
    rowVersion: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<UserListItem> {
    requireUserMutation(userId, rowVersion, idempotencyKey)
    requirePassword(newPassword)

    const response = await this.client.request(`/users/${userId}/password/reset`, {
      method: 'POST',
      idempotencyKey,
      signal,
      body: { new_password: newPassword, row_version: rowVersion },
      decode: decodeUserListItem,
    })
    return response.data
  }

  async replaceRoles(
    userId: string,
    fixedRoles: RoleCode[],
    rowVersion: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<UserListItem> {
    requireUserMutation(userId, rowVersion, idempotencyKey)
    requireFixedRoles(fixedRoles)

    const response = await this.client.request(`/users/${userId}/roles`, {
      method: 'PUT',
      idempotencyKey,
      signal,
      body: { fixed_roles: fixedRoles, row_version: rowVersion },
      decode: decodeUserListItem,
    })
    return response.data
  }
}

function requireIdempotencyKey(value: string): void {
  if (!idempotencyKeyPattern.test(value)) throw new TypeError('invalid idempotency key')
}

function requireUsername(value: string): void {
  if (!usernamePattern.test(value)) throw new TypeError('invalid username')
}

function requireDisplayName(value: string): void {
  if (
    value.length < 1 ||
    value.length > 100 ||
    value !== value.trim() ||
    /[\u0000-\u001f\u007f]/.test(value)
  ) {
    throw new TypeError('invalid display name')
  }
}

function requirePassword(value: string): void {
  if (value.length < 1 || value.length > 512) throw new TypeError('invalid password')
}

function requireFixedRoles(value: RoleCode[]): void {
  if (
    value.length < 1 ||
    value.length > roleCodes.length ||
    value.some((role) => !roleCodes.includes(role)) ||
    value.some((role, index) => index > 0 && value[index - 1]! >= role)
  ) {
    throw new TypeError('invalid fixed roles')
  }
}

function requireUserMutation(userId: string, rowVersion: string, idempotencyKey: string): void {
  if (!UUID_PATTERN.test(userId)) throw new TypeError('invalid user id')
  if (!positiveRowVersionPattern.test(rowVersion)) throw new TypeError('invalid row version')
  requireIdempotencyKey(idempotencyKey)
}

export const userApi = new UserApi()
