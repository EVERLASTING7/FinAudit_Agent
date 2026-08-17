import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const operationActionCodes = [
  'auth.login.succeeded',
  'auth.login.failed',
  'auth.logout',
  'authorization.denied',
  'users.created',
  'users.status_changed',
  'users.password_reset',
  'users.roles_replaced',
  'break_glass.requested',
  'break_glass.approved',
  'break_glass.rejected',
  'break_glass.revoked',
  'files.uploaded',
] as const
export const operationActorKinds = ['anonymous', 'user', 'system'] as const
export const operationOutcomes = ['succeeded', 'denied', 'failed'] as const

export type OperationActionCode = (typeof operationActionCodes)[number]
export type OperationActorKind = (typeof operationActorKinds)[number]
export type OperationOutcome = (typeof operationOutcomes)[number]

export interface OperationLogItem {
  id: string
  actorKind: OperationActorKind
  actorId: string | null
  actionCode: OperationActionCode
  outcome: OperationOutcome
  resourceType: string | null
  resourceId: string | null
  traceId: string
  changeSummary: Record<string, unknown>
  createdAt: string
}

export interface OperationLogListData {
  items: OperationLogItem[]
  pageSize: number
  nextCursor: string | null
}

const itemKeys = [
  'id',
  'actor_kind',
  'actor_id',
  'action_code',
  'outcome',
  'resource_type',
  'resource_id',
  'trace_id',
  'change_summary',
  'created_at',
] as const
const listKeys = ['items', 'page_size', 'next_cursor'] as const
const cursorKeys = ['created_at', 'id', 'v'] as const
const cursorPattern = /^[A-Za-z0-9_-]+$/
const resourceTypePattern = /^[a-z][a-z0-9_]*$/
const timestampPattern =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/
const cursorTimestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && keys.every((key) => key in value)
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === 'string' && allowed.includes(value as T)
}

function isSafeJson(value: unknown, depth = 0): boolean {
  if (depth > 8) return false
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.length <= 100 && value.every((item) => isSafeJson(item, depth + 1))
  if (!isRecord(value) || Object.keys(value).length > 100) return false
  return Object.entries(value).every(
    ([key, child]) => key.length <= 100 && isSafeJson(child, depth + 1),
  )
}

function encodeBase64Url(value: string): string {
  return btoa(value).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

function decodeCursor(value: unknown): { id: string; createdAt: string } {
  if (
    typeof value !== 'string' ||
    value.length < 1 ||
    value.length > 256 ||
    !cursorPattern.test(value)
  ) {
    throw new TypeError('invalid operation log cursor')
  }
  try {
    const base64 = value.replaceAll('-', '+').replaceAll('_', '/')
    const binary = atob(base64 + '='.repeat(-base64.length & 3))
    if (encodeBase64Url(binary) !== value) throw new TypeError('noncanonical base64url')
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    const payload: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
    if (
      !isRecord(payload) ||
      !hasExactKeys(payload, cursorKeys) ||
      payload.v !== 1 ||
      typeof payload.created_at !== 'string' ||
      !cursorTimestampPattern.test(payload.created_at) ||
      !Number.isFinite(Date.parse(payload.created_at)) ||
      typeof payload.id !== 'string' ||
      !UUID_PATTERN.test(payload.id)
    ) {
      throw new TypeError('invalid operation log cursor payload')
    }
    const canonical = JSON.stringify({ created_at: payload.created_at, id: payload.id, v: 1 })
    if (encodeBase64Url(canonical) !== value) throw new TypeError('noncanonical operation cursor')
    return { id: payload.id, createdAt: payload.created_at }
  } catch {
    throw new TypeError('invalid operation log cursor')
  }
}

export function decodeOperationLogItem(value: unknown): OperationLogItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, itemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    !isOneOf(value.actor_kind, operationActorKinds) ||
    (value.actor_id !== null &&
      (typeof value.actor_id !== 'string' || !UUID_PATTERN.test(value.actor_id))) ||
    !isOneOf(value.action_code, operationActionCodes) ||
    !isOneOf(value.outcome, operationOutcomes) ||
    (value.resource_type !== null &&
      (typeof value.resource_type !== 'string' || !resourceTypePattern.test(value.resource_type))) ||
    (value.resource_id !== null &&
      (typeof value.resource_id !== 'string' || !UUID_PATTERN.test(value.resource_id))) ||
    typeof value.trace_id !== 'string' ||
    !UUID_PATTERN.test(value.trace_id) ||
    !isRecord(value.change_summary) ||
    !isSafeJson(value.change_summary) ||
    typeof value.created_at !== 'string' ||
    !timestampPattern.test(value.created_at) ||
    !Number.isFinite(Date.parse(value.created_at))
  ) {
    throw new TypeError('invalid operation log item')
  }
  if ((value.actor_kind === 'user') !== (value.actor_id !== null)) {
    throw new TypeError('invalid operation actor shape')
  }
  if ((value.resource_type === null) !== (value.resource_id === null)) {
    throw new TypeError('invalid operation resource shape')
  }

  return {
    id: value.id,
    actorKind: value.actor_kind,
    actorId: value.actor_id,
    actionCode: value.action_code,
    outcome: value.outcome,
    resourceType: value.resource_type,
    resourceId: value.resource_id,
    traceId: value.trace_id,
    changeSummary: value.change_summary,
    createdAt: value.created_at,
  }
}

export function decodeOperationLogList(value: unknown): OperationLogListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null && typeof value.next_cursor !== 'string')
  ) {
    throw new TypeError('invalid operation log list')
  }
  const items = value.items.map(decodeOperationLogItem)
  const pageSize = Number(value.page_size)
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid operation log page size')
  }
  if (new Set(items.map((item) => item.id)).size !== items.length) {
    throw new TypeError('duplicate operation log item')
  }
  if (value.next_cursor !== null) {
    const cursor = decodeCursor(value.next_cursor)
    if (cursor.id !== items.at(-1)?.id) throw new TypeError('operation cursor does not match page')
  }
  return { items, pageSize, nextCursor: value.next_cursor }
}

export class OperationLogApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<OperationLogListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }
    if (cursor !== undefined) decodeCursor(cursor)
    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(
      `/operation-logs?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeOperationLogList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('operation log page size does not match request')
    }
    return response.data
  }
}

export const operationLogApi = new OperationLogApi()
