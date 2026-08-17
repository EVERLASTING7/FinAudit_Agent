import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const policyStatuses = [
  'draft',
  'submitted',
  'business_approved',
  'published',
  'superseded',
  'revoked',
  'archived',
] as const

export type PolicyStatus = (typeof policyStatuses)[number]
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

export interface PolicyDocument {
  id: string
  knowledgeBaseId: string
  sourceFileId: string
  policyCode: string
  name: string
  version: string
  issuingDepartment: string | null
  effectiveFrom: string
  effectiveTo: string | null
  scope: Record<string, JsonValue>
  status: PolicyStatus
  submittedBy: string | null
  submittedAt: string | null
  businessApprovedBy: string | null
  businessApprovedAt: string | null
  technicalPublishedBy: string | null
  technicalPublishedAt: string | null
  rowVersion: string
}

export interface PolicyChunkSet {
  id: string
  markdownVersionId: string
  versionNo: number
  status: string
  profileVersion: string
  profileHash: string
  chunkCount: number
  contentManifestHash: string
}

export interface PolicyWriteData {
  policy: PolicyDocument
  chunkSet: PolicyChunkSet | null
}

export interface PolicyListData {
  items: PolicyDocument[]
  pageSize: number
  nextCursor: string | null
}

export interface PolicyCreateInput {
  knowledgeBaseId: string
  sourceFileId: string
  policyCode: string
  name: string
  version: string
  issuingDepartment: string | null
  effectiveFrom: string
  effectiveTo: string | null
  scope: Record<string, JsonValue>
}

const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/
const CURSOR_PATTERN = /^[A-Za-z0-9_-]{1,256}$/
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const SHA256_PATTERN = /^[0-9a-f]{64}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exact(value: Record<string, unknown>, keys: readonly string[]): void {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new TypeError('unexpected policy response fields')
  }
}

function text(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new TypeError(`${field} must be a string`)
  return value
}

function uuid(value: unknown, field: string): string {
  const decoded = text(value, field)
  if (!UUID_PATTERN.test(decoded)) throw new TypeError(`${field} must be a canonical lowercase UUID`)
  return decoded
}

function nullableUuid(value: unknown, field: string): string | null {
  return value === null ? null : uuid(value, field)
}

function timestamp(value: unknown, field: string): string {
  const decoded = text(value, field)
  if (!Number.isFinite(Date.parse(decoded))) throw new TypeError(`${field} must be a timestamp`)
  return decoded
}

function nullableTimestamp(value: unknown, field: string): string | null {
  return value === null ? null : timestamp(value, field)
}

function canonicalDate(value: unknown, field: string): string {
  const decoded = text(value, field)
  const date = new Date(`${decoded}T00:00:00Z`)
  if (!DATE_PATTERN.test(decoded) || Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== decoded) {
    throw new TypeError(`${field} must use YYYY-MM-DD`)
  }
  return decoded
}

function nullableDate(value: unknown, field: string): string | null {
  return value === null ? null : canonicalDate(value, field)
}

function jsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(jsonValue)
  return isRecord(value) && Object.values(value).every(jsonValue)
}

export function decodePolicy(value: unknown): PolicyDocument {
  if (!isRecord(value)) throw new TypeError('policy must be an object')
  exact(value, [
    'id', 'knowledge_base_id', 'source_file_id', 'policy_code', 'name', 'version',
    'issuing_department', 'effective_from', 'effective_to', 'scope', 'status',
    'submitted_by', 'submitted_at', 'business_approved_by', 'business_approved_at',
    'technical_published_by', 'technical_published_at', 'row_version',
  ])
  if (typeof value.status !== 'string' || !policyStatuses.includes(value.status as PolicyStatus)) {
    throw new TypeError('policy status is invalid')
  }
  if (!isRecord(value.scope) || !jsonValue(value.scope)) throw new TypeError('scope is invalid')
  const status = value.status as PolicyStatus
  const submittedBy = nullableUuid(value.submitted_by, 'submitted_by')
  const submittedAt = nullableTimestamp(value.submitted_at, 'submitted_at')
  const approvedBy = nullableUuid(value.business_approved_by, 'business_approved_by')
  const approvedAt = nullableTimestamp(value.business_approved_at, 'business_approved_at')
  const publishedBy = nullableUuid(value.technical_published_by, 'technical_published_by')
  const publishedAt = nullableTimestamp(value.technical_published_at, 'technical_published_at')
  const submitted = submittedBy !== null && submittedAt !== null
  const approved = approvedBy !== null && approvedAt !== null
  const published = publishedBy !== null && publishedAt !== null
  if (
    (submittedBy === null) !== (submittedAt === null) ||
    (approvedBy === null) !== (approvedAt === null) ||
    (publishedBy === null) !== (publishedAt === null) ||
    (status === 'draft' && (submitted || approved || published)) ||
    (status === 'submitted' && (!submitted || approved || published)) ||
    (status === 'business_approved' && (!submitted || !approved || published)) ||
    ((status === 'published' || status === 'superseded') && (!submitted || !approved || !published))
  ) {
    throw new TypeError('policy lifecycle is inconsistent')
  }
  const rowVersion = text(value.row_version, 'row_version')
  if (!POSITIVE_INTEGER_PATTERN.test(rowVersion)) throw new TypeError('row_version is invalid')
  return {
    id: uuid(value.id, 'id'),
    knowledgeBaseId: uuid(value.knowledge_base_id, 'knowledge_base_id'),
    sourceFileId: uuid(value.source_file_id, 'source_file_id'),
    policyCode: text(value.policy_code, 'policy_code'),
    name: text(value.name, 'name'),
    version: text(value.version, 'version'),
    issuingDepartment: value.issuing_department === null ? null : text(value.issuing_department, 'issuing_department'),
    effectiveFrom: canonicalDate(value.effective_from, 'effective_from'),
    effectiveTo: nullableDate(value.effective_to, 'effective_to'),
    scope: value.scope as Record<string, JsonValue>,
    status,
    submittedBy,
    submittedAt,
    businessApprovedBy: approvedBy,
    businessApprovedAt: approvedAt,
    technicalPublishedBy: publishedBy,
    technicalPublishedAt: publishedAt,
    rowVersion,
  }
}

function decodeChunkSet(value: unknown): PolicyChunkSet {
  if (!isRecord(value)) throw new TypeError('chunk set must be an object')
  exact(value, ['id', 'markdown_version_id', 'version_no', 'status', 'profile_version', 'profile_hash', 'chunk_count', 'content_manifest_hash'])
  const profileHash = text(value.profile_hash, 'profile_hash')
  const manifestHash = text(value.content_manifest_hash, 'content_manifest_hash')
  if (
    !Number.isInteger(value.version_no) || Number(value.version_no) < 1 ||
    !Number.isInteger(value.chunk_count) || Number(value.chunk_count) < 1 ||
    !SHA256_PATTERN.test(profileHash) || !SHA256_PATTERN.test(manifestHash)
  ) throw new TypeError('chunk set is invalid')
  return {
    id: uuid(value.id, 'id'),
    markdownVersionId: uuid(value.markdown_version_id, 'markdown_version_id'),
    versionNo: Number(value.version_no),
    status: text(value.status, 'status'),
    profileVersion: text(value.profile_version, 'profile_version'),
    profileHash,
    chunkCount: Number(value.chunk_count),
    contentManifestHash: manifestHash,
  }
}

export function decodePolicyWrite(value: unknown): PolicyWriteData {
  if (!isRecord(value)) throw new TypeError('policy write result must be an object')
  exact(value, ['policy', 'chunk_set'])
  return {
    policy: decodePolicy(value.policy),
    chunkSet: value.chunk_set === null ? null : decodeChunkSet(value.chunk_set),
  }
}

export function decodePolicyList(value: unknown): PolicyListData {
  if (!isRecord(value)) throw new TypeError('policy list must be an object')
  exact(value, ['items', 'page_size', 'next_cursor'])
  if (!Array.isArray(value.items) || !Number.isInteger(value.page_size)) throw new TypeError('policy page is invalid')
  const pageSize = Number(value.page_size)
  if (pageSize < 1 || pageSize > 100) throw new TypeError('page_size is invalid')
  const nextCursor = value.next_cursor === null ? null : text(value.next_cursor, 'next_cursor')
  if (nextCursor !== null && !CURSOR_PATTERN.test(nextCursor)) throw new TypeError('next_cursor is invalid')
  const items = value.items.map(decodePolicy)
  const ids = items.map((item) => item.id)
  if (items.length > pageSize || (nextCursor !== null && items.length !== pageSize) || new Set(ids).size !== ids.length || ids.some((id, index) => index > 0 && ids[index - 1]! >= id)) {
    throw new TypeError('policy page shape is invalid')
  }
  return { items, pageSize, nextCursor }
}

function validateUuid(value: string, field: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${field} must be a canonical lowercase UUID`)
}

export class PolicyApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(
    pageSize = 20,
    cursor?: string,
    knowledgeBaseId?: string,
    signal?: AbortSignal,
  ): Promise<PolicyListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new TypeError('pageSize is invalid')
    if (cursor !== undefined && !CURSOR_PATTERN.test(cursor)) throw new TypeError('cursor is invalid')
    if (knowledgeBaseId !== undefined) validateUuid(knowledgeBaseId, 'knowledgeBaseId')
    const params = new URLSearchParams({ page_size: String(pageSize) })
    if (cursor !== undefined) params.set('cursor', cursor)
    if (knowledgeBaseId !== undefined) params.set('knowledge_base_id', knowledgeBaseId)
    return (await this.client.request(`/policy-documents?${params}`, { signal, decode: decodePolicyList })).data
  }

  async getDetail(policyId: string, signal?: AbortSignal): Promise<PolicyDocument> {
    validateUuid(policyId, 'policyId')
    return (await this.client.request(`/policy-documents/${policyId}`, { signal, decode: decodePolicy })).data
  }

  async create(input: PolicyCreateInput, idempotencyKey: string, signal?: AbortSignal): Promise<PolicyWriteData> {
    validateUuid(input.knowledgeBaseId, 'knowledgeBaseId')
    validateUuid(input.sourceFileId, 'sourceFileId')
    return (
      await this.client.request('/policy-documents', {
        method: 'POST', idempotencyKey, signal,
        body: {
          knowledge_base_id: input.knowledgeBaseId,
          source_file_id: input.sourceFileId,
          policy_code: input.policyCode,
          name: input.name,
          version: input.version,
          issuing_department: input.issuingDepartment,
          effective_from: input.effectiveFrom,
          effective_to: input.effectiveTo,
          scope: input.scope,
        },
        decode: decodePolicyWrite,
      })
    ).data
  }

  async transition(
    policyId: string,
    action: 'submit-review' | 'approve' | 'publish',
    rowVersion: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<PolicyWriteData> {
    validateUuid(policyId, 'policyId')
    if (!POSITIVE_INTEGER_PATTERN.test(rowVersion)) throw new TypeError('rowVersion is invalid')
    return (
      await this.client.request(`/policy-documents/${policyId}/${action}`, {
        method: 'POST', idempotencyKey, signal,
        body: { row_version: rowVersion, reason },
        decode: decodePolicyWrite,
      })
    ).data
  }
}

export const policyApi = new PolicyApi()
