import { ApiClient, UUID_PATTERN, apiClient, type ApiBinaryResponse } from './api'

export const reportStatuses = [
  'queued',
  'generating',
  'ready',
  'failed',
  'outdated',
  'archived',
] as const
export const aiDraftStatuses = ['disabled', 'succeeded', 'degraded'] as const

export type ReportStatus = (typeof reportStatuses)[number]
export type AiDraftStatus = (typeof aiDraftStatuses)[number]

export interface ReportDraftData {
  executiveSummary: string
  scopeSummary: string
  riskSummary: string
  recommendations: string[]
  warnings: string[]
}

export interface AuditReportData {
  id: string
  auditTaskId: string
  executionId: string
  reportVersion: number
  status: ReportStatus
  payloadSha256: string
  generatorVersion: string
  pdfSha256: string | null
  pdfSizeBytes: number | null
  pdfMimeType: 'application/pdf'
  xlsxSha256: string | null
  xlsxSizeBytes: number | null
  xlsxMimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  jobId: string | null
  failureCode: string | null
  rowVersion: string
  createdBy: string
  createdAt: string
  generatedAt: string | null
  outdatedAt: string | null
  archivedAt: string | null
  isOutdated: boolean
  aiDraftStatus: AiDraftStatus
  aiDraftSha256: string | null
  aiDraft: ReportDraftData | null
}

export interface AuditReportListData {
  executionId: string
  items: AuditReportData[]
}

export interface ReportArtifact {
  body: Blob
  filename: string
  isOutdated: boolean
  status: 'ready' | 'outdated' | 'archived'
}

const PDF_MIME_TYPE = 'application/pdf' as const
const XLSX_MIME_TYPE =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' as const
const readableStatuses = ['ready', 'outdated', 'archived'] as const
const hashPattern = /^[0-9a-f]{64}$/
const positiveIntegerPattern = /^[1-9]\d*$/
const reportKeys = [
  'id',
  'audit_task_id',
  'execution_id',
  'report_version',
  'status',
  'payload_sha256',
  'generator_version',
  'pdf_sha256',
  'pdf_size_bytes',
  'pdf_mime_type',
  'xlsx_sha256',
  'xlsx_size_bytes',
  'xlsx_mime_type',
  'job_id',
  'failure_code',
  'row_version',
  'created_by',
  'created_at',
  'generated_at',
  'outdated_at',
  'archived_at',
  'is_outdated',
  'ai_draft_status',
  'ai_draft_sha256',
  'ai_draft',
] as const
const listKeys = ['execution_id', 'items'] as const
const draftKeys = [
  'executive_summary',
  'scope_summary',
  'risk_summary',
  'recommendations',
  'warnings',
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
  return Number.isFinite(Date.parse(value))
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isUtcTimestamp(value)
}

function isNullableUuid(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && UUID_PATTERN.test(value))
}

function isNullableHash(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && hashPattern.test(value))
}

function isNullableSize(value: unknown): value is number | null {
  return value === null || (Number.isSafeInteger(value) && Number(value) > 0)
}

function decodeTextArray(
  value: unknown,
  label: string,
  minimum: number,
  maximum: number,
): string[] {
  if (
    !Array.isArray(value) ||
    value.length < minimum ||
    value.length > maximum ||
    !value.every((item) => typeof item === 'string' && item.length > 0)
  ) {
    throw new TypeError(`invalid ${label}`)
  }
  return [...value]
}

function decodeReportDraft(value: unknown): ReportDraftData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, draftKeys) ||
    typeof value.executive_summary !== 'string' ||
    value.executive_summary.length < 1 ||
    typeof value.scope_summary !== 'string' ||
    value.scope_summary.length < 1 ||
    typeof value.risk_summary !== 'string' ||
    value.risk_summary.length < 1
  ) {
    throw new TypeError('invalid AI report draft')
  }
  return {
    executiveSummary: value.executive_summary,
    scopeSummary: value.scope_summary,
    riskSummary: value.risk_summary,
    recommendations: decodeTextArray(value.recommendations, 'AI report recommendations', 1, 10),
    warnings: decodeTextArray(value.warnings, 'AI report warnings', 0, 10),
  }
}

export function decodeAuditReport(value: unknown): AuditReportData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, reportKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.audit_task_id !== 'string' ||
    !UUID_PATTERN.test(value.audit_task_id) ||
    typeof value.execution_id !== 'string' ||
    !UUID_PATTERN.test(value.execution_id) ||
    !Number.isSafeInteger(value.report_version) ||
    Number(value.report_version) < 1 ||
    !isOneOf(value.status, reportStatuses) ||
    typeof value.payload_sha256 !== 'string' ||
    !hashPattern.test(value.payload_sha256) ||
    typeof value.generator_version !== 'string' ||
    value.generator_version.length < 1 ||
    !isNullableHash(value.pdf_sha256) ||
    !isNullableSize(value.pdf_size_bytes) ||
    value.pdf_mime_type !== PDF_MIME_TYPE ||
    !isNullableHash(value.xlsx_sha256) ||
    !isNullableSize(value.xlsx_size_bytes) ||
    value.xlsx_mime_type !== XLSX_MIME_TYPE ||
    !isNullableUuid(value.job_id) ||
    (value.failure_code !== null &&
      (typeof value.failure_code !== 'string' || value.failure_code.length < 1)) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    typeof value.created_by !== 'string' ||
    !UUID_PATTERN.test(value.created_by) ||
    !isUtcTimestamp(value.created_at) ||
    !isNullableTimestamp(value.generated_at) ||
    !isNullableTimestamp(value.outdated_at) ||
    !isNullableTimestamp(value.archived_at) ||
    typeof value.is_outdated !== 'boolean' ||
    !isOneOf(value.ai_draft_status, aiDraftStatuses) ||
    !isNullableHash(value.ai_draft_sha256)
  ) {
    throw new TypeError('invalid audit report')
  }

  const aiDraft = value.ai_draft === null ? null : decodeReportDraft(value.ai_draft)
  const hasAiDraft = aiDraft !== null && value.ai_draft_sha256 !== null
  if (
    (value.ai_draft_status === 'succeeded') !== hasAiDraft ||
    (aiDraft === null) !== (value.ai_draft_sha256 === null)
  ) {
    throw new TypeError('invalid audit report AI draft state')
  }

  const hasPdfHash = value.pdf_sha256 !== null
  const hasPdfSize = value.pdf_size_bytes !== null
  const hasXlsxHash = value.xlsx_sha256 !== null
  const hasXlsxSize = value.xlsx_size_bytes !== null
  const hasPdf = hasPdfHash && hasPdfSize
  const hasXlsx = hasXlsxHash && hasXlsxSize
  const isReadable = isOneOf(value.status, readableStatuses)
  if (
    hasPdfHash !== hasPdfSize ||
    hasXlsxHash !== hasXlsxSize ||
    hasPdf !== hasXlsx ||
    isReadable !== (hasPdf && value.generated_at !== null) ||
    value.is_outdated !== (value.outdated_at !== null) ||
    (value.status === 'outdated' && !value.is_outdated) ||
    (value.status === 'failed') !== (value.failure_code !== null)
  ) {
    throw new TypeError('invalid audit report state')
  }

  return {
    id: value.id,
    auditTaskId: value.audit_task_id,
    executionId: value.execution_id,
    reportVersion: Number(value.report_version),
    status: value.status,
    payloadSha256: value.payload_sha256,
    generatorVersion: value.generator_version,
    pdfSha256: value.pdf_sha256,
    pdfSizeBytes: value.pdf_size_bytes,
    pdfMimeType: value.pdf_mime_type,
    xlsxSha256: value.xlsx_sha256,
    xlsxSizeBytes: value.xlsx_size_bytes,
    xlsxMimeType: value.xlsx_mime_type,
    jobId: value.job_id,
    failureCode: value.failure_code,
    rowVersion: value.row_version,
    createdBy: value.created_by,
    createdAt: value.created_at,
    generatedAt: value.generated_at,
    outdatedAt: value.outdated_at,
    archivedAt: value.archived_at,
    isOutdated: value.is_outdated,
    aiDraftStatus: value.ai_draft_status,
    aiDraftSha256: value.ai_draft_sha256,
    aiDraft,
  }
}

export function decodeAuditReportList(value: unknown): AuditReportListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    typeof value.execution_id !== 'string' ||
    !UUID_PATTERN.test(value.execution_id) ||
    !Array.isArray(value.items)
  ) {
    throw new TypeError('invalid audit report list')
  }
  const items = value.items.map(decodeAuditReport)
  if (
    items.some((item) => item.executionId !== value.execution_id) ||
    new Set(items.map((item) => item.id)).size !== items.length
  ) {
    throw new TypeError('invalid audit report list identity')
  }
  return { executionId: value.execution_id, items }
}

function requireUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${label} must be a canonical lowercase UUID`)
}

async function sha256(blob: Blob): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function validateArtifact(
  response: ApiBinaryResponse,
  report: AuditReportData,
  format: 'pdf' | 'xlsx',
): Promise<ReportArtifact> {
  if (!('body' in response)) throw new TypeError('invalid report artifact response')
  const isPdf = format === 'pdf'
  const expectedHash = isPdf ? report.pdfSha256 : report.xlsxSha256
  const expectedSize = isPdf ? report.pdfSizeBytes : report.xlsxSizeBytes
  const expectedMime = isPdf ? PDF_MIME_TYPE : XLSX_MIME_TYPE
  if (expectedHash === null || expectedSize === null) {
    throw new TypeError('report artifact metadata is incomplete')
  }
  const expectedFilename = isPdf
    ? `audit-report-${report.id}-v${report.reportVersion}.pdf`
    : `audit-report-${report.id}-v${report.reportVersion}-risks.xlsx`
  const expectedDisposition = `${isPdf ? 'inline' : 'attachment'}; filename="${expectedFilename}"`
  const contentType = response.headers.get('content-type')?.split(';', 1)[0] ?? ''
  const etag = response.headers.get('etag')
  const outdated = response.headers.get('x-report-outdated')
  const status = response.headers.get('x-report-status')
  if (
    response.status !== 200 ||
    contentType !== expectedMime ||
    response.headers.get('content-disposition') !== expectedDisposition ||
    etag !== `"${expectedHash}"` ||
    (outdated !== 'true' && outdated !== 'false') ||
    !isOneOf(status, readableStatuses) ||
    response.body.size !== expectedSize ||
    (await sha256(response.body)) !== expectedHash
  ) {
    throw new TypeError('invalid report artifact')
  }
  return {
    body: response.body,
    filename: expectedFilename,
    isOutdated: outdated === 'true',
    status,
  }
}

export class ReportApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async get(reportId: string, signal?: AbortSignal): Promise<AuditReportData> {
    requireUuid(reportId, 'report id')
    const response = await this.client.request(`/audit-reports/${reportId}`, {
      signal,
      decode: decodeAuditReport,
    })
    if (response.data.id !== reportId) throw new TypeError('report response id mismatch')
    return response.data
  }

  async list(executionId: string, signal?: AbortSignal): Promise<AuditReportListData> {
    requireUuid(executionId, 'execution id')
    const response = await this.client.request(`/audit-executions/${executionId}/reports`, {
      signal,
      decode: decodeAuditReportList,
    })
    if (response.data.executionId !== executionId) {
      throw new TypeError('report list execution id mismatch')
    }
    return response.data
  }

  async previewPdf(report: AuditReportData, signal?: AbortSignal): Promise<ReportArtifact> {
    requireUuid(report.id, 'report id')
    const response = await this.client.request(`/audit-reports/${report.id}/preview`, {
      method: 'GET',
      signal,
      expectBinary: true,
      accept: PDF_MIME_TYPE,
    })
    return validateArtifact(response, report, 'pdf')
  }

  async downloadXlsx(report: AuditReportData, signal?: AbortSignal): Promise<ReportArtifact> {
    requireUuid(report.id, 'report id')
    const response = await this.client.request(`/audit-reports/${report.id}/download`, {
      method: 'GET',
      signal,
      expectBinary: true,
      accept: XLSX_MIME_TYPE,
    })
    return validateArtifact(response, report, 'xlsx')
  }
}

export const reportApi = new ReportApi()
