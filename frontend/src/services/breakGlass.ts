import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const breakGlassRoleCodes = [
  'system_admin',
  'finance_reviewer',
  'audit_reviewer',
  'contract_admin',
] as const
export const breakGlassStatuses = [
  'pending',
  'approved',
  'rejected',
  'revoked',
  'expired',
] as const

export type BreakGlassRoleCode = (typeof breakGlassRoleCodes)[number]
export type BreakGlassStatus = (typeof breakGlassStatuses)[number]

export interface BreakGlassData {
  id: string
  targetUserId: string
  targetRoleCode: BreakGlassRoleCode
  requestedDurationSeconds: number
  status: BreakGlassStatus
  effectiveFrom: string | null
  expiresAt: string | null
  rowVersion: string
}

export interface BreakGlassCreateInput {
  targetUserId: string
  targetRoleCode: BreakGlassRoleCode
  requestedDurationSeconds: number
  reason: string
}

const responseKeys = [
  'id',
  'target_user_id',
  'target_role_code',
  'requested_duration_seconds',
  'status',
  'effective_from',
  'expires_at',
  'row_version',
] as const
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/
const positiveIntegerPattern = /^[1-9]\d*$/

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

function isTimestampOrNull(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === 'string' &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
      Number.isFinite(Date.parse(value)))
  )
}

export function decodeBreakGlassData(value: unknown): BreakGlassData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, responseKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.target_user_id !== 'string' ||
    !UUID_PATTERN.test(value.target_user_id) ||
    !isOneOf(value.target_role_code, breakGlassRoleCodes) ||
    !Number.isInteger(value.requested_duration_seconds) ||
    Number(value.requested_duration_seconds) < 1 ||
    Number(value.requested_duration_seconds) > 14_400 ||
    !isOneOf(value.status, breakGlassStatuses) ||
    !isTimestampOrNull(value.effective_from) ||
    !isTimestampOrNull(value.expires_at) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid break-glass response')
  }
  if (
    (value.status === 'pending' || value.status === 'rejected') &&
    (value.effective_from !== null || value.expires_at !== null)
  ) {
    throw new TypeError('invalid break-glass state timestamps')
  }
  if (
    (value.status === 'approved' || value.status === 'revoked' || value.status === 'expired') &&
    (value.effective_from === null || value.expires_at === null)
  ) {
    throw new TypeError('invalid break-glass state timestamps')
  }

  return {
    id: value.id,
    targetUserId: value.target_user_id,
    targetRoleCode: value.target_role_code,
    requestedDurationSeconds: Number(value.requested_duration_seconds),
    status: value.status,
    effectiveFrom: value.effective_from,
    expiresAt: value.expires_at,
    rowVersion: value.row_version,
  }
}

function requireIdempotencyKey(value: string): void {
  if (!idempotencyKeyPattern.test(value)) throw new TypeError('invalid idempotency key')
}

function requireReason(value: string): void {
  if (value.length < 1 || value.length > 500 || value !== value.trim()) {
    throw new TypeError('invalid break-glass reason')
  }
}

function requireIdentityAndVersion(id: string, rowVersion: string): void {
  if (!UUID_PATTERN.test(id)) throw new TypeError('invalid break-glass request id')
  if (!positiveIntegerPattern.test(rowVersion)) throw new TypeError('invalid row version')
}

export class BreakGlassApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async create(
    input: BreakGlassCreateInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<BreakGlassData> {
    requireIdempotencyKey(idempotencyKey)
    if (!UUID_PATTERN.test(input.targetUserId)) throw new TypeError('invalid target user id')
    if (!breakGlassRoleCodes.includes(input.targetRoleCode)) {
      throw new TypeError('invalid target role')
    }
    if (
      !Number.isInteger(input.requestedDurationSeconds) ||
      input.requestedDurationSeconds < 1 ||
      input.requestedDurationSeconds > 14_400
    ) {
      throw new TypeError('invalid requested duration')
    }
    requireReason(input.reason)

    const response = await this.client.request('/break-glass-requests', {
      method: 'POST',
      idempotencyKey,
      signal,
      body: {
        target_user_id: input.targetUserId,
        target_role_code: input.targetRoleCode,
        requested_duration_seconds: input.requestedDurationSeconds,
        reason: input.reason,
      },
      decode: decodeBreakGlassData,
    })
    return response.data
  }

  async decide(
    requestId: string,
    decision: 'approved' | 'rejected',
    reason: string,
    rowVersion: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<BreakGlassData> {
    requireIdentityAndVersion(requestId, rowVersion)
    requireIdempotencyKey(idempotencyKey)
    requireReason(reason)
    if (decision !== 'approved' && decision !== 'rejected') {
      throw new TypeError('invalid break-glass decision')
    }

    const response = await this.client.request(
      `/break-glass-requests/${requestId}/decision`,
      {
        method: 'POST',
        idempotencyKey,
        signal,
        body: { decision, reason, row_version: rowVersion },
        decode: decodeBreakGlassData,
      },
    )
    return response.data
  }

  async revoke(
    requestId: string,
    reason: string,
    rowVersion: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<BreakGlassData> {
    requireIdentityAndVersion(requestId, rowVersion)
    requireIdempotencyKey(idempotencyKey)
    requireReason(reason)

    const response = await this.client.request(`/break-glass-requests/${requestId}/revoke`, {
      method: 'POST',
      idempotencyKey,
      signal,
      body: { reason, row_version: rowVersion },
      decode: decodeBreakGlassData,
    })
    return response.data
  }
}

export const breakGlassApi = new BreakGlassApi()
