import { ApiClient, UUID_PATTERN, apiClient } from './api'

export type DocumentCorrectionFieldName =
  | 'text_content'
  | 'block_type'
  | 'reading_order'
  | 'bbox'

export type DocumentCorrectionBusinessType =
  | 'contract'
  | 'supplementary_agreement'
  | 'invoice'
  | 'policy'

export type DocumentCorrectionBlockType =
  | 'title'
  | 'paragraph'
  | 'list'
  | 'table'
  | 'quote'
  | 'asset'
  | 'other'

export interface DocumentCorrectionEvidence {
  blockId: string
  parseVersionId: string
  pageNo: number
  quoteText: string
}

export interface DocumentCorrectionBlockBbox {
  left: number
  top: number
  width: number
  height: number
}

export interface DocumentCorrectionBlock {
  blockId: string
  pageNo: number
  blockIndex: number
  blockType: DocumentCorrectionBlockType
  textContent: string
  readingOrder: number
  bbox: DocumentCorrectionBlockBbox | null
}

export interface DocumentCorrectionBlockPage {
  fileId: string
  businessType: DocumentCorrectionBusinessType
  parseVersionId: string
  items: DocumentCorrectionBlock[]
  pageSize: number
  nextCursor: string | null
}

export interface DocumentCorrectionAccepted {
  correctionId: string
  resultParseVersionId: string
  jobId: string
  status: 'queued'
}

export interface DocumentParseActivation {
  id: string
  status: 'active'
  supersededVersionId: string | null
  activatedAt: string
}

export interface CorrectDocumentBlockInput {
  fieldName: DocumentCorrectionFieldName
  afterValue: unknown
  reason: string
  sourceParseVersionId: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every((key) => key in value)
}

function requireUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${label} must be a canonical UUID`)
}

function requireReason(value: string): void {
  if (value.length < 1 || value.length > 1000 || value !== value.trim()) {
    throw new TypeError('reason must be trimmed and between 1 and 1000 characters')
  }
}

function requireIdempotencyKey(value: string): void {
  if (!/^[A-Za-z0-9._~-]{8,128}$/.test(value)) {
    throw new TypeError('invalid idempotency key')
  }
}

const CURSOR_PATTERN = /^[A-Za-z0-9_-]{1,256}$/
const businessTypes: readonly DocumentCorrectionBusinessType[] = [
  'contract',
  'supplementary_agreement',
  'invoice',
  'policy',
]
const blockTypes: readonly DocumentCorrectionBlockType[] = [
  'title',
  'paragraph',
  'list',
  'table',
  'quote',
  'asset',
  'other',
]

function nonnegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) {
    throw new TypeError(`${field} must be a nonnegative integer`)
  }
  return Number(value)
}

function decodeBbox(value: unknown): DocumentCorrectionBlockBbox | null {
  if (value === null) return null
  if (!isRecord(value) || !hasExactKeys(value, ['left', 'top', 'width', 'height'])) {
    throw new TypeError('bbox is invalid')
  }
  const left = nonnegativeInteger(value.left, 'bbox.left')
  const top = nonnegativeInteger(value.top, 'bbox.top')
  const width = nonnegativeInteger(value.width, 'bbox.width')
  const height = nonnegativeInteger(value.height, 'bbox.height')
  if (width === 0 || height === 0) throw new TypeError('bbox dimensions are invalid')
  return { left, top, width, height }
}

function decodeBlock(value: unknown): DocumentCorrectionBlock {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'block_id',
      'page_no',
      'block_index',
      'block_type',
      'text_content',
      'reading_order',
      'bbox',
    ])
  ) {
    throw new TypeError('document correction block is invalid')
  }
  if (typeof value.block_id !== 'string') throw new TypeError('block_id is invalid')
  requireUuid(value.block_id, 'block_id')
  const pageNo = nonnegativeInteger(value.page_no, 'page_no')
  if (pageNo === 0) throw new TypeError('page_no is invalid')
  const blockIndex = nonnegativeInteger(value.block_index, 'block_index')
  const readingOrder = nonnegativeInteger(value.reading_order, 'reading_order')
  if (
    typeof value.block_type !== 'string' ||
    !blockTypes.includes(value.block_type as DocumentCorrectionBlockType) ||
    typeof value.text_content !== 'string' ||
    value.text_content.length > 20_000_000
  ) {
    throw new TypeError('document correction block content is invalid')
  }
  return {
    blockId: value.block_id,
    pageNo,
    blockIndex,
    blockType: value.block_type as DocumentCorrectionBlockType,
    textContent: value.text_content,
    readingOrder,
    bbox: decodeBbox(value.bbox),
  }
}

export function decodeDocumentCorrectionBlockPage(
  value: unknown,
): DocumentCorrectionBlockPage {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'file_id',
      'business_type',
      'parse_version_id',
      'items',
      'page_size',
      'next_cursor',
    ]) ||
    typeof value.file_id !== 'string' ||
    typeof value.parse_version_id !== 'string' ||
    typeof value.business_type !== 'string' ||
    !businessTypes.includes(value.business_type as DocumentCorrectionBusinessType) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size)
  ) {
    throw new TypeError('document correction block page is invalid')
  }
  requireUuid(value.file_id, 'file_id')
  requireUuid(value.parse_version_id, 'parse_version_id')
  const pageSize = Number(value.page_size)
  if (pageSize < 1 || pageSize > 100) throw new TypeError('page_size is invalid')
  const nextCursor =
    value.next_cursor === null
      ? null
      : typeof value.next_cursor === 'string' && CURSOR_PATTERN.test(value.next_cursor)
        ? value.next_cursor
        : null
  if (value.next_cursor !== null && nextCursor === null) {
    throw new TypeError('next_cursor is invalid')
  }
  const items = value.items.map(decodeBlock)
  const identities = items.map(
    (item) => `${String(item.pageNo).padStart(12, '0')}:${String(item.blockIndex).padStart(12, '0')}:${item.blockId}`,
  )
  if (
    items.length > pageSize ||
    (nextCursor !== null && items.length !== pageSize) ||
    new Set(identities).size !== identities.length ||
    identities.some((identity, index) => index > 0 && identities[index - 1]! >= identity)
  ) {
    throw new TypeError('document correction block page shape is invalid')
  }
  return {
    fileId: value.file_id,
    businessType: value.business_type as DocumentCorrectionBusinessType,
    parseVersionId: value.parse_version_id,
    items,
    pageSize,
    nextCursor,
  }
}

function validateAfterValue(input: CorrectDocumentBlockInput): void {
  const value = input.afterValue
  if (input.fieldName === 'text_content') {
    if (typeof value !== 'string' || value.length < 1 || value.length > 1_000_000 || value.includes('\0')) {
      throw new TypeError('invalid text correction')
    }
  } else if (input.fieldName === 'block_type') {
    if (!['title', 'paragraph', 'list', 'table', 'quote', 'other'].includes(String(value))) {
      throw new TypeError('invalid block type correction')
    }
  } else if (input.fieldName === 'reading_order') {
    if (!Number.isInteger(value) || Number(value) < 0 || Number(value) > 2_147_483_647) {
      throw new TypeError('invalid reading order correction')
    }
  } else if (value !== null) {
    if (
      !isRecord(value) ||
      !hasExactKeys(value, ['left', 'top', 'width', 'height']) ||
      ![value.left, value.top, value.width, value.height].every(Number.isInteger) ||
      Number(value.left) < 0 ||
      Number(value.top) < 0 ||
      Number(value.width) <= 0 ||
      Number(value.height) <= 0
    ) {
      throw new TypeError('invalid bbox correction')
    }
  }
}

export function decodeDocumentCorrectionAccepted(value: unknown): DocumentCorrectionAccepted {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      'correction_id',
      'result_parse_version_id',
      'job_id',
      'status',
    ]) ||
    typeof value.correction_id !== 'string' ||
    !UUID_PATTERN.test(value.correction_id) ||
    typeof value.result_parse_version_id !== 'string' ||
    !UUID_PATTERN.test(value.result_parse_version_id) ||
    typeof value.job_id !== 'string' ||
    !UUID_PATTERN.test(value.job_id) ||
    value.status !== 'queued'
  ) {
    throw new TypeError('invalid document correction response')
  }
  return {
    correctionId: value.correction_id,
    resultParseVersionId: value.result_parse_version_id,
    jobId: value.job_id,
    status: value.status,
  }
}

export function decodeDocumentParseActivation(value: unknown): DocumentParseActivation {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['id', 'status', 'superseded_version_id', 'activated_at']) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    value.status !== 'active' ||
    (value.superseded_version_id !== null &&
      (typeof value.superseded_version_id !== 'string' ||
        !UUID_PATTERN.test(value.superseded_version_id))) ||
    typeof value.activated_at !== 'string' ||
    !/(?:Z|[+-]\d{2}:\d{2})$/.test(value.activated_at) ||
    Number.isNaN(Date.parse(value.activated_at))
  ) {
    throw new TypeError('invalid document parse activation response')
  }
  return {
    id: value.id,
    status: value.status,
    supersededVersionId: value.superseded_version_id,
    activatedAt: value.activated_at,
  }
}

export class DocumentCorrectionApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async listBlocks(
    fileId: string,
    pageSize = 50,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<DocumentCorrectionBlockPage> {
    requireUuid(fileId, 'file id')
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('pageSize is invalid')
    }
    if (cursor !== undefined && !CURSOR_PATTERN.test(cursor)) {
      throw new TypeError('cursor is invalid')
    }
    const params = new URLSearchParams({ page_size: String(pageSize) })
    if (cursor !== undefined) params.set('cursor', cursor)
    const response = await this.client.request(
      `/files/${fileId}/document-correction-blocks?${params}`,
      { signal, decode: decodeDocumentCorrectionBlockPage },
    )
    if (response.data.fileId !== fileId) {
      throw new TypeError('document correction file identity mismatch')
    }
    return response.data
  }

  async correctBlock(
    blockId: string,
    input: CorrectDocumentBlockInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<DocumentCorrectionAccepted> {
    requireUuid(blockId, 'block id')
    requireUuid(input.sourceParseVersionId, 'source parse version id')
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    validateAfterValue(input)
    const response = await this.client.request(`/document-blocks/${blockId}/correct`, {
      method: 'POST',
      body: {
        field_name: input.fieldName,
        after_value: input.afterValue,
        reason: input.reason,
        source_parse_version_id: input.sourceParseVersionId,
      },
      idempotencyKey,
      signal,
      decode: decodeDocumentCorrectionAccepted,
    })
    return response.data
  }

  async activateParse(
    parseVersionId: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<DocumentParseActivation> {
    requireUuid(parseVersionId, 'parse version id')
    requireReason(reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(
      `/document-parse-versions/${parseVersionId}/activate`,
      {
        method: 'POST',
        body: { reason },
        idempotencyKey,
        signal,
        decode: decodeDocumentParseActivation,
      },
    )
    if (response.data.id !== parseVersionId) {
      throw new TypeError('activated parse version does not match request')
    }
    return response.data
  }
}

export const documentCorrectionApi = new DocumentCorrectionApi()
