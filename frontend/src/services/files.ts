import { ApiClient, UUID_PATTERN, apiClient, type ApiBinaryResponse } from './api'

export const fileStatuses = ['uploaded', 'validating', 'stored', 'rejected', 'archived'] as const
export const securityScanStatuses = [
  'pending',
  'clean',
  'infected',
  'scan_failed',
  'unsupported',
  'not_configured',
] as const
export const fileBusinessTypes = [
  'contract',
  'supplementary_agreement',
  'invoice',
  'policy',
] as const
export const fileJobStatuses = [
  'queued',
  'running',
  'cancel_requested',
  'succeeded',
  'failed',
  'cancelled',
] as const

export type FileStatus = (typeof fileStatuses)[number]
export type SecurityScanStatus = (typeof securityScanStatuses)[number]
export type FileBusinessType = (typeof fileBusinessTypes)[number]
export type FileJobStatus = (typeof fileJobStatuses)[number]

export interface FileRecordData {
  fileId: string
  originalName: string
  status: FileStatus
  securityScanStatus: SecurityScanStatus
  reused: boolean
  intendedBusinessType: FileBusinessType
  targetKnowledgeBaseId: string | null
  autoProcessRequested: boolean
  jobId: string
  jobStatus: FileJobStatus
  jobScope: 'full' | 'scan_only'
  nextStage: 'scan'
  rowVersion: string
}

export interface FileListItem extends FileRecordData {
  sizeBytes: string
  createdAt: string
}

export interface FileListData {
  items: FileListItem[]
  pageSize: number
  nextCursor: string | null
}

export interface FileUploadInput {
  file: File
  intendedBusinessType: FileBusinessType
  autoProcessRequested: boolean
  targetKnowledgeBaseId?: string
}

export interface FileUploadResult {
  record: FileRecordData
  traceId: string
}

export interface FileBatchError {
  code: string
  message: string
}

export interface FileBatchItem {
  index: number
  originalName: string
  outcome: 'accepted' | 'rejected'
  httpStatus: number
  replayed: boolean
  data: FileRecordData | null
  error: FileBatchError | null
}

export interface FileBatchUploadData {
  items: FileBatchItem[]
  acceptedCount: number
  rejectedCount: number
}

export interface FileBatchUploadResult {
  data: FileBatchUploadData
  traceId: string
}

export interface FileTextPreviewData {
  fileId: string
  markdownVersionId: string
  contentSha256: string
  markdownText: string
  charCount: number
  truncated: boolean
}

export interface FileOriginalArtifact {
  body: Blob
  mimeType:
    | 'application/pdf'
    | 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    | 'image/jpeg'
    | 'image/png'
  status: 'stored' | 'archived'
}

const positiveIntegerPattern = /^[1-9]\d*$/
const cursorPattern = /^[A-Za-z0-9_-]+$/
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/
const uploadKeys = [
  'file_id',
  'original_name',
  'status',
  'security_scan_status',
  'reused',
  'intended_business_type',
  'target_knowledge_base_id',
  'auto_process_requested',
  'job_id',
  'job_status',
  'job_scope',
  'next_stage',
  'row_version',
] as const
const listItemKeys = [...uploadKeys, 'size_bytes', 'created_at'] as const
const listKeys = ['items', 'page_size', 'next_cursor'] as const
const batchKeys = ['items', 'accepted_count', 'rejected_count'] as const
const batchItemKeys = [
  'index',
  'original_name',
  'outcome',
  'http_status',
  'replayed',
  'data',
  'error',
] as const
const batchErrorKeys = ['code', 'message'] as const
const textPreviewKeys = [
  'file_id',
  'markdown_version_id',
  'content_sha256',
  'markdown_text',
  'char_count',
  'truncated',
] as const
const errorCodePattern = /^[A-Z][A-Z0-9_]{0,79}$/
const sha256Pattern = /^[0-9a-f]{64}$/
const previewMimeTypes = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'image/jpeg',
  'image/png',
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value)
  return actual.length === keys.length && keys.every((key) => key in value)
}

function isOneOf<T extends string>(value: unknown, values: readonly T[]): value is T {
  return typeof value === 'string' && values.some((candidate) => candidate === value)
}

function isUtcTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return false
  const parsed = Date.parse(value)
  return Number.isFinite(parsed)
}

function decodeFileRecord(value: unknown, keys: readonly string[]): FileRecordData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, keys) ||
    typeof value.file_id !== 'string' ||
    !UUID_PATTERN.test(value.file_id) ||
    typeof value.original_name !== 'string' ||
    value.original_name.length < 1 ||
    value.original_name.length > 500 ||
    !isOneOf(value.status, fileStatuses) ||
    !isOneOf(value.security_scan_status, securityScanStatuses) ||
    typeof value.reused !== 'boolean' ||
    !isOneOf(value.intended_business_type, fileBusinessTypes) ||
    (value.target_knowledge_base_id !== null &&
      (typeof value.target_knowledge_base_id !== 'string' ||
        !UUID_PATTERN.test(value.target_knowledge_base_id))) ||
    typeof value.auto_process_requested !== 'boolean' ||
    typeof value.job_id !== 'string' ||
    !UUID_PATTERN.test(value.job_id) ||
    !isOneOf(value.job_status, fileJobStatuses) ||
    (value.job_scope !== 'full' && value.job_scope !== 'scan_only') ||
    value.next_stage !== 'scan' ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid file record')
  }
  if (
    (value.intended_business_type === 'policy') !==
      (value.target_knowledge_base_id !== null) ||
    value.auto_process_requested !== (value.job_scope === 'full')
  ) {
    throw new TypeError('invalid file intent projection')
  }

  return {
    fileId: value.file_id,
    originalName: value.original_name,
    status: value.status,
    securityScanStatus: value.security_scan_status,
    reused: value.reused,
    intendedBusinessType: value.intended_business_type,
    targetKnowledgeBaseId: value.target_knowledge_base_id,
    autoProcessRequested: value.auto_process_requested,
    jobId: value.job_id,
    jobStatus: value.job_status,
    jobScope: value.job_scope,
    nextStage: value.next_stage,
    rowVersion: value.row_version,
  }
}

export function decodeFileUpload(value: unknown): FileRecordData {
  return decodeFileRecord(value, uploadKeys)
}

export function decodeFileListItem(value: unknown): FileListItem {
  const record = decodeFileRecord(value, listItemKeys)
  if (
    !isRecord(value) ||
    typeof value.size_bytes !== 'string' ||
    !positiveIntegerPattern.test(value.size_bytes) ||
    !isUtcTimestamp(value.created_at)
  ) {
    throw new TypeError('invalid file list item')
  }
  return { ...record, sizeBytes: value.size_bytes, createdAt: value.created_at }
}

export function decodeFileList(value: unknown): FileListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null &&
      (typeof value.next_cursor !== 'string' ||
        value.next_cursor.length < 1 ||
        value.next_cursor.length > 256 ||
        !cursorPattern.test(value.next_cursor)))
  ) {
    throw new TypeError('invalid file list')
  }
  const items = value.items.map(decodeFileListItem)
  const pageSize = Number(value.page_size)
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid file list page size')
  }
  if (new Set(items.map((item) => item.fileId)).size !== items.length) {
    throw new TypeError('duplicate file list item')
  }
  return { items, pageSize, nextCursor: value.next_cursor }
}

function decodeBatchError(value: unknown): FileBatchError {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, batchErrorKeys) ||
    typeof value.code !== 'string' ||
    !errorCodePattern.test(value.code) ||
    typeof value.message !== 'string' ||
    value.message.length < 1 ||
    value.message.length > 200
  ) {
    throw new TypeError('invalid file batch error')
  }
  return { code: value.code, message: value.message }
}

function decodeBatchItem(value: unknown): FileBatchItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, batchItemKeys) ||
    !Number.isInteger(value.index) ||
    Number(value.index) < 0 ||
    Number(value.index) > 999 ||
    typeof value.original_name !== 'string' ||
    value.original_name.length < 1 ||
    value.original_name.length > 500 ||
    (value.outcome !== 'accepted' && value.outcome !== 'rejected') ||
    !Number.isInteger(value.http_status) ||
    Number(value.http_status) < 200 ||
    Number(value.http_status) > 599 ||
    typeof value.replayed !== 'boolean'
  ) {
    throw new TypeError('invalid file batch item')
  }
  const data = value.data === null ? null : decodeFileUpload(value.data)
  const error = value.error === null ? null : decodeBatchError(value.error)
  if (
    (value.outcome === 'accepted' &&
      (value.http_status !== 202 || data === null || error !== null)) ||
    (value.outcome === 'rejected' && (data !== null || error === null || value.replayed))
  ) {
    throw new TypeError('invalid file batch outcome')
  }
  return {
    index: Number(value.index),
    originalName: value.original_name,
    outcome: value.outcome,
    httpStatus: Number(value.http_status),
    replayed: value.replayed,
    data,
    error,
  }
}

export function decodeFileBatch(value: unknown): FileBatchUploadData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, batchKeys) ||
    !Array.isArray(value.items) ||
    value.items.length < 1 ||
    value.items.length > 100 ||
    !Number.isInteger(value.accepted_count) ||
    !Number.isInteger(value.rejected_count)
  ) {
    throw new TypeError('invalid file batch')
  }
  const items = value.items.map(decodeBatchItem)
  const acceptedCount = items.filter((item) => item.outcome === 'accepted').length
  const rejectedCount = items.length - acceptedCount
  if (
    items.some((item, index) => item.index !== index) ||
    value.accepted_count !== acceptedCount ||
    value.rejected_count !== rejectedCount
  ) {
    throw new TypeError('invalid file batch counts')
  }
  return { items, acceptedCount, rejectedCount }
}

export function decodeFileTextPreview(value: unknown): FileTextPreviewData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, textPreviewKeys) ||
    typeof value.file_id !== 'string' ||
    !UUID_PATTERN.test(value.file_id) ||
    typeof value.markdown_version_id !== 'string' ||
    !UUID_PATTERN.test(value.markdown_version_id) ||
    typeof value.content_sha256 !== 'string' ||
    !sha256Pattern.test(value.content_sha256) ||
    typeof value.markdown_text !== 'string' ||
    !Number.isSafeInteger(value.char_count) ||
    Number(value.char_count) < 0 ||
    typeof value.truncated !== 'boolean' ||
    value.markdown_text.length > Number(value.char_count) ||
    value.truncated !== (value.markdown_text.length < Number(value.char_count))
  ) {
    throw new TypeError('invalid file text preview')
  }
  return {
    fileId: value.file_id,
    markdownVersionId: value.markdown_version_id,
    contentSha256: value.content_sha256,
    markdownText: value.markdown_text,
    charCount: Number(value.char_count),
    truncated: value.truncated,
  }
}

function requireCursor(cursor: string): void {
  if (cursor.length < 1 || cursor.length > 256 || !cursorPattern.test(cursor)) {
    throw new TypeError('cursor must be a canonical base64url string')
  }
}

function requireIdempotencyKey(value: string): void {
  if (!idempotencyKeyPattern.test(value)) throw new TypeError('invalid idempotency key')
}

function requireReason(value: string): void {
  if (
    value.length < 3 ||
    value.length > 500 ||
    value.trim() !== value ||
    /[\u0000-\u001f\u007f]/.test(value)
  ) {
    throw new TypeError('reason must be a trimmed safe string between 3 and 500 characters')
  }
}

async function sha256(blob: Blob): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function validateOriginalArtifact(
  response: ApiBinaryResponse,
  file: FileListItem,
): Promise<FileOriginalArtifact> {
  if (!('body' in response)) throw new TypeError('invalid file preview response')
  const contentType = response.headers.get('content-type')?.split(';', 1)[0] ?? ''
  const etag = response.headers.get('etag') ?? ''
  const status = response.headers.get('x-file-status')
  const disposition = response.headers.get('content-disposition') ?? ''
  if (
    response.status !== 200 ||
    !isOneOf(contentType, previewMimeTypes) ||
    (status !== 'stored' && status !== 'archived') ||
    response.headers.get('x-file-id') !== file.fileId ||
    !disposition.startsWith('inline; filename="file-') ||
    !disposition.includes("; filename*=UTF-8''") ||
    !/^"[0-9a-f]{64}"$/.test(etag) ||
    response.body.size !== Number(file.sizeBytes) ||
    (await sha256(response.body)) !== etag.slice(1, -1)
  ) {
    throw new TypeError('invalid file preview artifact')
  }
  return { body: response.body, mimeType: contentType, status }
}

export class FileApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<FileListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }
    if (cursor !== undefined) requireCursor(cursor)
    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(`/files?page_size=${pageSize}${cursorQuery}`, {
      signal,
      decode: decodeFileList,
    })
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('file list page size does not match request')
    }
    return response.data
  }

  async get(fileId: string, signal?: AbortSignal): Promise<FileListItem> {
    if (!UUID_PATTERN.test(fileId)) {
      throw new TypeError('file id must be a canonical lowercase UUID')
    }
    const response = await this.client.request(`/files/${fileId}`, {
      signal,
      decode: decodeFileListItem,
    })
    if (response.data.fileId !== fileId) throw new TypeError('file response id mismatch')
    return response.data
  }

  async upload(
    input: FileUploadInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<FileUploadResult> {
    requireIdempotencyKey(idempotencyKey)
    if (!(input.file instanceof File) || input.file.size < 1) {
      throw new TypeError('file must be non-empty')
    }
    if (!isOneOf(input.intendedBusinessType, fileBusinessTypes)) {
      throw new TypeError('invalid file business type')
    }
    const target = input.targetKnowledgeBaseId ?? ''
    if (
      (input.intendedBusinessType === 'policy' && !UUID_PATTERN.test(target)) ||
      (input.intendedBusinessType !== 'policy' && target !== '')
    ) {
      throw new TypeError('invalid knowledge base target')
    }
    const body = new FormData()
    body.set('file', input.file, input.file.name)
    body.set('intended_business_type', input.intendedBusinessType)
    body.set('auto_process_requested', input.autoProcessRequested ? 'true' : 'false')
    if (target) body.set('target_knowledge_base_id', target)

    const response = await this.client.request('/files', {
      method: 'POST',
      body,
      idempotencyKey,
      signal,
      decode: decodeFileUpload,
    })
    return { record: response.data, traceId: response.traceId }
  }

  async uploadBatch(
    input: Omit<FileUploadInput, 'file'> & { files: File[] },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<FileBatchUploadResult> {
    requireIdempotencyKey(idempotencyKey)
    if (
      !Array.isArray(input.files) ||
      input.files.length < 1 ||
      input.files.length > 20 ||
      input.files.some((file) => !(file instanceof File) || file.size < 1)
    ) {
      throw new TypeError('batch must contain between 1 and 20 non-empty files')
    }
    if (!isOneOf(input.intendedBusinessType, fileBusinessTypes)) {
      throw new TypeError('invalid file business type')
    }
    const target = input.targetKnowledgeBaseId ?? ''
    if (
      (input.intendedBusinessType === 'policy' && !UUID_PATTERN.test(target)) ||
      (input.intendedBusinessType !== 'policy' && target !== '')
    ) {
      throw new TypeError('invalid knowledge base target')
    }
    const body = new FormData()
    input.files.forEach((file) => body.append('files', file, file.name))
    body.set('intended_business_type', input.intendedBusinessType)
    body.set('auto_process_requested', input.autoProcessRequested ? 'true' : 'false')
    if (target) body.set('target_knowledge_base_id', target)
    const response = await this.client.request('/files/batch', {
      method: 'POST',
      body,
      idempotencyKey,
      signal,
      decode: decodeFileBatch,
    })
    return { data: response.data, traceId: response.traceId }
  }

  async previewOriginal(file: FileListItem, signal?: AbortSignal): Promise<FileOriginalArtifact> {
    if (!UUID_PATTERN.test(file.fileId)) throw new TypeError('invalid file id')
    const response = await this.client.request(`/files/${file.fileId}/preview`, {
      method: 'GET',
      signal,
      expectBinary: true,
      accept: previewMimeTypes.join(','),
    })
    return validateOriginalArtifact(response, file)
  }

  async textPreview(
    fileId: string,
    maxChars = 100_000,
    signal?: AbortSignal,
  ): Promise<FileTextPreviewData> {
    if (!UUID_PATTERN.test(fileId)) throw new TypeError('invalid file id')
    if (!Number.isInteger(maxChars) || maxChars < 1_000 || maxChars > 200_000) {
      throw new TypeError('maxChars must be between 1000 and 200000')
    }
    const response = await this.client.request(
      `/files/${fileId}/text-preview?max_chars=${maxChars}`,
      { signal, decode: decodeFileTextPreview },
    )
    if (response.data.fileId !== fileId) throw new TypeError('file preview id mismatch')
    return response.data
  }

  async archive(
    fileId: string,
    rowVersion: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<FileListItem> {
    return this.mutate(fileId, 'archive', rowVersion, reason, idempotencyKey, undefined, signal)
  }

  async retry(
    fileId: string,
    rowVersion: string,
    jobId: string,
    reason: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<FileListItem> {
    if (!UUID_PATTERN.test(jobId)) throw new TypeError('invalid job id')
    return this.mutate(fileId, 'retry', rowVersion, reason, idempotencyKey, jobId, signal)
  }

  private async mutate(
    fileId: string,
    action: 'archive' | 'retry',
    rowVersion: string,
    reason: string,
    idempotencyKey: string,
    jobId?: string,
    signal?: AbortSignal,
  ): Promise<FileListItem> {
    if (!UUID_PATTERN.test(fileId) || !positiveIntegerPattern.test(rowVersion)) {
      throw new TypeError('invalid file mutation identity')
    }
    requireReason(reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/files/${fileId}/${action}`, {
      method: 'POST',
      body: {
        row_version: rowVersion,
        reason,
        ...(jobId === undefined ? {} : { job_id: jobId }),
      },
      idempotencyKey,
      signal,
      decode: decodeFileListItem,
    })
    if (response.data.fileId !== fileId) throw new TypeError('file mutation id mismatch')
    return response.data
  }
}

export const fileApi = new FileApi()
