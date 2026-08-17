import { ApiClient, UUID_PATTERN, apiClient } from './api'

export type KnowledgeBaseStatus = 'active' | 'archived'
export type QaQueryStatus = 'answered' | 'refused' | 'service_degraded'

export interface KnowledgeBase {
  id: string
  code: string
  name: string
  description: string | null
  status: KnowledgeBaseStatus
  defaultTopK: 5
  rowVersion: string
}

export interface KnowledgeBaseListData {
  items: KnowledgeBase[]
  pageSize: number
  nextCursor: string | null
}

export interface QaCitation {
  policyDocumentId: string
  policyVersion: string
  markdownVersionId: string
  chunkId: string
  blockIds: string[]
  indexVersionId: string
  pageRange: string
  titlePath: string[]
  quote: string
  contentSha256: string
}

export interface QaQueryResult {
  id: string
  knowledgeBaseId: string
  indexVersionId: string | null
  baselineDate: string
  status: QaQueryStatus
  answer: string | null
  reasonCode: string | null
  citations: QaCitation[]
  retrievedCount: number
  createdAt: string
}

export interface QaFeedback {
  id: string
  qaQueryId: string
  rating: 'helpful' | 'unhelpful'
  correctionText: string | null
  createdAt: string
}

export type KnowledgeIndexStatus = 'building' | 'ready' | 'active' | 'failed' | 'superseded' | 'archived'

export interface KnowledgeIndexVersion {
  id: string
  knowledgeBaseId: string
  versionNo: number
  status: KnowledgeIndexStatus
  collectionName: string
  embeddingAdapterId: string
  embeddingModelId: string
  vectorDimension: number
  distance: string
  memberCount: number
  manifestSha256: string
  consistency: Record<string, unknown>
  failureCode: string | null
  rowVersion: string
  jobId: string | null
  jobStatus: string | null
  createdAt: string
  activatedAt: string | null
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
    throw new TypeError('unexpected knowledge response fields')
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

function canonicalDate(value: unknown, field: string): string {
  const decoded = text(value, field)
  const date = new Date(`${decoded}T00:00:00Z`)
  if (!DATE_PATTERN.test(decoded) || Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== decoded) {
    throw new TypeError(`${field} must use YYYY-MM-DD`)
  }
  return decoded
}

export function decodeKnowledgeBase(value: unknown): KnowledgeBase {
  if (!isRecord(value)) throw new TypeError('knowledge base must be an object')
  exact(value, ['id', 'code', 'name', 'description', 'status', 'default_top_k', 'row_version'])
  if (value.status !== 'active' && value.status !== 'archived') throw new TypeError('status is invalid')
  if (value.default_top_k !== 5) throw new TypeError('default_top_k must be 5')
  const rowVersion = text(value.row_version, 'row_version')
  if (!POSITIVE_INTEGER_PATTERN.test(rowVersion)) throw new TypeError('row_version is invalid')
  return {
    id: uuid(value.id, 'id'),
    code: text(value.code, 'code'),
    name: text(value.name, 'name'),
    description: value.description === null ? null : text(value.description, 'description'),
    status: value.status,
    defaultTopK: 5,
    rowVersion,
  }
}

export function decodeKnowledgeBaseList(value: unknown): KnowledgeBaseListData {
  if (!isRecord(value)) throw new TypeError('knowledge base list must be an object')
  exact(value, ['items', 'page_size', 'next_cursor'])
  if (!Array.isArray(value.items) || !Number.isInteger(value.page_size)) throw new TypeError('knowledge base page is invalid')
  const pageSize = Number(value.page_size)
  if (pageSize < 1 || pageSize > 100) throw new TypeError('page_size is invalid')
  const nextCursor = value.next_cursor === null ? null : text(value.next_cursor, 'next_cursor')
  if (nextCursor !== null && !CURSOR_PATTERN.test(nextCursor)) throw new TypeError('next_cursor is invalid')
  const items = value.items.map(decodeKnowledgeBase)
  const ids = items.map((item) => item.id)
  if (
    items.length > pageSize ||
    (nextCursor !== null && items.length !== pageSize) ||
    new Set(ids).size !== ids.length ||
    ids.some((id, index) => index > 0 && ids[index - 1]! >= id)
  ) {
    throw new TypeError('knowledge base page shape is invalid')
  }
  return { items, pageSize, nextCursor }
}

function decodeCitation(value: unknown): QaCitation {
  if (!isRecord(value)) throw new TypeError('citation must be an object')
  exact(value, [
    'policy_document_id', 'policy_version', 'markdown_version_id', 'chunk_id', 'block_ids',
    'index_version_id', 'page_range', 'title_path', 'quote', 'content_sha256',
  ])
  if (!Array.isArray(value.block_ids) || value.block_ids.length < 1 || !Array.isArray(value.title_path)) {
    throw new TypeError('citation source arrays are invalid')
  }
  const contentSha256 = text(value.content_sha256, 'content_sha256')
  if (!SHA256_PATTERN.test(contentSha256)) throw new TypeError('content_sha256 is invalid')
  return {
    policyDocumentId: uuid(value.policy_document_id, 'policy_document_id'),
    policyVersion: text(value.policy_version, 'policy_version'),
    markdownVersionId: uuid(value.markdown_version_id, 'markdown_version_id'),
    chunkId: uuid(value.chunk_id, 'chunk_id'),
    blockIds: value.block_ids.map((item) => uuid(item, 'block_id')),
    indexVersionId: uuid(value.index_version_id, 'index_version_id'),
    pageRange: text(value.page_range, 'page_range'),
    titlePath: value.title_path.map((item) => text(item, 'title_path')),
    quote: text(value.quote, 'quote'),
    contentSha256,
  }
}

export function decodeQaQuery(value: unknown): QaQueryResult {
  if (!isRecord(value)) throw new TypeError('qa query must be an object')
  exact(value, [
    'id', 'knowledge_base_id', 'index_version_id', 'baseline_date', 'status', 'answer',
    'reason_code', 'citations', 'retrieved_count', 'created_at',
  ])
  if (!['answered', 'refused', 'service_degraded'].includes(String(value.status))) {
    throw new TypeError('qa status is invalid')
  }
  if (!Array.isArray(value.citations) || !Number.isInteger(value.retrieved_count) || Number(value.retrieved_count) < 0) {
    throw new TypeError('qa result shape is invalid')
  }
  const status = value.status as QaQueryStatus
  const answer = value.answer === null ? null : text(value.answer, 'answer')
  const reasonCode = value.reason_code === null ? null : text(value.reason_code, 'reason_code')
  const citations = value.citations.map(decodeCitation)
  const retrievedCount = Number(value.retrieved_count)
  if (
    (status === 'answered' && (answer === null || reasonCode !== null || citations.length < 1 || retrievedCount < 1)) ||
    (status !== 'answered' && (answer !== null || reasonCode === null || citations.length !== 0))
  ) {
    throw new TypeError('qa status projection is inconsistent')
  }
  return {
    id: uuid(value.id, 'id'),
    knowledgeBaseId: uuid(value.knowledge_base_id, 'knowledge_base_id'),
    indexVersionId: nullableUuid(value.index_version_id, 'index_version_id'),
    baselineDate: canonicalDate(value.baseline_date, 'baseline_date'),
    status,
    answer,
    reasonCode,
    citations,
    retrievedCount,
    createdAt: timestamp(value.created_at, 'created_at'),
  }
}

export function decodeQaFeedback(value: unknown): QaFeedback {
  if (!isRecord(value)) throw new TypeError('qa feedback must be an object')
  exact(value, ['id', 'qa_query_id', 'rating', 'correction_text', 'created_at'])
  if (value.rating !== 'helpful' && value.rating !== 'unhelpful') throw new TypeError('rating is invalid')
  return {
    id: uuid(value.id, 'id'),
    qaQueryId: uuid(value.qa_query_id, 'qa_query_id'),
    rating: value.rating,
    correctionText: value.correction_text === null ? null : text(value.correction_text, 'correction_text'),
    createdAt: timestamp(value.created_at, 'created_at'),
  }
}

export function decodeKnowledgeIndex(value: unknown): KnowledgeIndexVersion {
  if (!isRecord(value)) throw new TypeError('knowledge index must be an object')
  exact(value, [
    'id', 'knowledge_base_id', 'version_no', 'status', 'collection_name',
    'embedding_adapter_id', 'embedding_model_id', 'vector_dimension', 'distance',
    'member_count', 'manifest_sha256', 'consistency', 'failure_code', 'row_version',
    'job_id', 'job_status', 'created_at', 'activated_at',
  ])
  const statuses: readonly KnowledgeIndexStatus[] = ['building', 'ready', 'active', 'failed', 'superseded', 'archived']
  if (typeof value.status !== 'string' || !statuses.includes(value.status as KnowledgeIndexStatus)) throw new TypeError('index status is invalid')
  if (!Number.isInteger(value.version_no) || Number(value.version_no) < 1 || !Number.isInteger(value.vector_dimension) || Number(value.vector_dimension) < 1 || !Number.isInteger(value.member_count) || Number(value.member_count) < 1 || !isRecord(value.consistency)) {
    throw new TypeError('index numeric fields are invalid')
  }
  const manifestSha256 = text(value.manifest_sha256, 'manifest_sha256')
  const rowVersion = text(value.row_version, 'row_version')
  if (!SHA256_PATTERN.test(manifestSha256) || !POSITIVE_INTEGER_PATTERN.test(rowVersion)) throw new TypeError('index identity is invalid')
  return {
    id: uuid(value.id, 'id'),
    knowledgeBaseId: uuid(value.knowledge_base_id, 'knowledge_base_id'),
    versionNo: Number(value.version_no),
    status: value.status as KnowledgeIndexStatus,
    collectionName: text(value.collection_name, 'collection_name'),
    embeddingAdapterId: text(value.embedding_adapter_id, 'embedding_adapter_id'),
    embeddingModelId: text(value.embedding_model_id, 'embedding_model_id'),
    vectorDimension: Number(value.vector_dimension),
    distance: text(value.distance, 'distance'),
    memberCount: Number(value.member_count),
    manifestSha256,
    consistency: value.consistency,
    failureCode: value.failure_code === null ? null : text(value.failure_code, 'failure_code'),
    rowVersion,
    jobId: nullableUuid(value.job_id, 'job_id'),
    jobStatus: value.job_status === null ? null : text(value.job_status, 'job_status'),
    createdAt: timestamp(value.created_at, 'created_at'),
    activatedAt: value.activated_at === null ? null : timestamp(value.activated_at, 'activated_at'),
  }
}

function validateUuid(value: string, field: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${field} must be a canonical lowercase UUID`)
}

export class KnowledgeApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<KnowledgeBaseListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new TypeError('pageSize is invalid')
    if (cursor !== undefined && !CURSOR_PATTERN.test(cursor)) throw new TypeError('cursor is invalid')
    const params = new URLSearchParams({ page_size: String(pageSize) })
    if (cursor !== undefined) params.set('cursor', cursor)
    return (await this.client.request(`/knowledge-bases?${params}`, { signal, decode: decodeKnowledgeBaseList })).data
  }

  async getDetail(knowledgeBaseId: string, signal?: AbortSignal): Promise<KnowledgeBase> {
    validateUuid(knowledgeBaseId, 'knowledgeBaseId')
    return (await this.client.request(`/knowledge-bases/${knowledgeBaseId}`, { signal, decode: decodeKnowledgeBase })).data
  }

  async query(
    knowledgeBaseId: string,
    input: { question: string; baselineDate: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QaQueryResult> {
    validateUuid(knowledgeBaseId, 'knowledgeBaseId')
    canonicalDate(input.baselineDate, 'baselineDate')
    return (
      await this.client.request(`/knowledge-bases/${knowledgeBaseId}/qa-queries`, {
        method: 'POST',
        idempotencyKey,
        signal,
        body: { question: input.question, baseline_date: input.baselineDate },
        decode: decodeQaQuery,
      })
    ).data
  }

  async feedback(
    queryId: string,
    input: { rating: 'helpful' | 'unhelpful'; correctionText?: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<QaFeedback> {
    validateUuid(queryId, 'queryId')
    return (
      await this.client.request(`/qa-queries/${queryId}/feedback`, {
        method: 'POST',
        idempotencyKey,
        signal,
        body: {
          rating: input.rating,
          correction_text: input.correctionText ?? null,
        },
        decode: decodeQaFeedback,
      })
    ).data
  }

  async buildIndex(
    knowledgeBaseId: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeIndexVersion> {
    validateUuid(knowledgeBaseId, 'knowledgeBaseId')
    return (
      await this.client.request(`/knowledge-bases/${knowledgeBaseId}/index-versions`, {
        method: 'POST', idempotencyKey, signal, body: {}, decode: decodeKnowledgeIndex,
      })
    ).data
  }

  async getIndex(
    knowledgeBaseId: string,
    indexVersionId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeIndexVersion> {
    validateUuid(knowledgeBaseId, 'knowledgeBaseId')
    validateUuid(indexVersionId, 'indexVersionId')
    return (
      await this.client.request(`/knowledge-bases/${knowledgeBaseId}/index-versions/${indexVersionId}`, {
        signal, decode: decodeKnowledgeIndex,
      })
    ).data
  }

  async activateIndex(
    knowledgeBaseId: string,
    indexVersionId: string,
    rowVersion: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeIndexVersion> {
    validateUuid(knowledgeBaseId, 'knowledgeBaseId')
    validateUuid(indexVersionId, 'indexVersionId')
    if (!POSITIVE_INTEGER_PATTERN.test(rowVersion)) throw new TypeError('rowVersion is invalid')
    return (
      await this.client.request(`/knowledge-bases/${knowledgeBaseId}/index-versions/${indexVersionId}/activate`, {
        method: 'POST', idempotencyKey, signal,
        body: { row_version: rowVersion, reason },
        decode: decodeKnowledgeIndex,
      })
    ).data
  }
}

export const knowledgeApi = new KnowledgeApi()
