import { ApiClient, UUID_PATTERN, apiClient } from './api'
import {
  fileBusinessTypes,
  fileJobStatuses,
  fileStatuses,
  securityScanStatuses,
  type FileBusinessType,
  type FileJobStatus,
  type FileStatus,
  type SecurityScanStatus,
} from './files'

export interface DashboardAuditTaskItem {
  id: string
  taskNo: string
  name: string
  status: 'open' | 'completed' | 'archived'
  currentExecutionId: string | null
  updatedAt: string
}

export interface DashboardAuditSection {
  openCount: number
  pendingReviewCount: number
  items: DashboardAuditTaskItem[]
}

export interface DashboardFileItem {
  fileId: string
  originalName: string
  status: FileStatus
  securityScanStatus: SecurityScanStatus
  intendedBusinessType: FileBusinessType
  jobId: string
  jobStatus: FileJobStatus
  createdAt: string
}

export interface DashboardFileSection {
  activeProcessingCount: number
  failedProcessingCount: number
  items: DashboardFileItem[]
}

export interface DashboardFailedJobItem {
  id: string
  jobType: string
  resourceType: string
  resourceId: string
  status: 'failed'
  stage: string | null
  attemptNo: number
  maxAttempts: number
  errorCode: string
  nextRetryAt: string | null
  createdAt: string
  rowVersion: string
}

export interface DashboardFailedJobSection {
  failedCount: number
  items: DashboardFailedJobItem[]
}

export interface DashboardData {
  itemLimit: number
  auditTasks: DashboardAuditSection | null
  files: DashboardFileSection | null
  failedJobs: DashboardFailedJobSection | null
}

const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exact(value: Record<string, unknown>, keys: readonly string[]): void {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new TypeError('unexpected dashboard response fields')
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

function timestamp(value: unknown, field: string): string {
  const decoded = text(value, field)
  if (!Number.isFinite(Date.parse(decoded))) throw new TypeError(`${field} must be a timestamp`)
  return decoded
}

function count(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw new TypeError(`${field} must be a nonnegative integer`)
  return Number(value)
}

function decodeAuditItem(value: unknown): DashboardAuditTaskItem {
  if (!isRecord(value)) throw new TypeError('audit item must be an object')
  exact(value, ['id', 'task_no', 'name', 'status', 'current_execution_id', 'updated_at'])
  if (value.status !== 'open' && value.status !== 'completed' && value.status !== 'archived') throw new TypeError('audit status is invalid')
  return {
    id: uuid(value.id, 'id'),
    taskNo: text(value.task_no, 'task_no'),
    name: text(value.name, 'name'),
    status: value.status,
    currentExecutionId: value.current_execution_id === null ? null : uuid(value.current_execution_id, 'current_execution_id'),
    updatedAt: timestamp(value.updated_at, 'updated_at'),
  }
}

function decodeAuditSection(value: unknown): DashboardAuditSection {
  if (!isRecord(value)) throw new TypeError('audit section must be an object')
  exact(value, ['open_count', 'pending_review_count', 'items'])
  if (!Array.isArray(value.items)) throw new TypeError('audit items must be an array')
  return {
    openCount: count(value.open_count, 'open_count'),
    pendingReviewCount: count(value.pending_review_count, 'pending_review_count'),
    items: value.items.map(decodeAuditItem),
  }
}

function decodeFileItem(value: unknown): DashboardFileItem {
  if (!isRecord(value)) throw new TypeError('file item must be an object')
  exact(value, ['file_id', 'original_name', 'status', 'security_scan_status', 'intended_business_type', 'job_id', 'job_status', 'created_at'])
  if (!fileStatuses.includes(value.status as FileStatus) || !securityScanStatuses.includes(value.security_scan_status as SecurityScanStatus) || !fileBusinessTypes.includes(value.intended_business_type as FileBusinessType) || !fileJobStatuses.includes(value.job_status as FileJobStatus)) {
    throw new TypeError('file dashboard status is invalid')
  }
  return {
    fileId: uuid(value.file_id, 'file_id'),
    originalName: text(value.original_name, 'original_name'),
    status: value.status as FileStatus,
    securityScanStatus: value.security_scan_status as SecurityScanStatus,
    intendedBusinessType: value.intended_business_type as FileBusinessType,
    jobId: uuid(value.job_id, 'job_id'),
    jobStatus: value.job_status as FileJobStatus,
    createdAt: timestamp(value.created_at, 'created_at'),
  }
}

function decodeFileSection(value: unknown): DashboardFileSection {
  if (!isRecord(value)) throw new TypeError('file section must be an object')
  exact(value, ['active_processing_count', 'failed_processing_count', 'items'])
  if (!Array.isArray(value.items)) throw new TypeError('file items must be an array')
  return {
    activeProcessingCount: count(value.active_processing_count, 'active_processing_count'),
    failedProcessingCount: count(value.failed_processing_count, 'failed_processing_count'),
    items: value.items.map(decodeFileItem),
  }
}

function decodeFailedJobItem(value: unknown): DashboardFailedJobItem {
  if (!isRecord(value)) throw new TypeError('failed job item must be an object')
  exact(value, ['id', 'job_type', 'resource_type', 'resource_id', 'status', 'stage', 'attempt_no', 'max_attempts', 'error_code', 'next_retry_at', 'created_at', 'row_version'])
  const attemptNo = count(value.attempt_no, 'attempt_no')
  const maxAttempts = count(value.max_attempts, 'max_attempts')
  const rowVersion = text(value.row_version, 'row_version')
  if (value.status !== 'failed' || maxAttempts < 1 || attemptNo > maxAttempts || !POSITIVE_INTEGER_PATTERN.test(rowVersion)) {
    throw new TypeError('failed job state is invalid')
  }
  return {
    id: uuid(value.id, 'id'),
    jobType: text(value.job_type, 'job_type'),
    resourceType: text(value.resource_type, 'resource_type'),
    resourceId: uuid(value.resource_id, 'resource_id'),
    status: 'failed',
    stage: value.stage === null ? null : text(value.stage, 'stage'),
    attemptNo,
    maxAttempts,
    errorCode: text(value.error_code, 'error_code'),
    nextRetryAt: value.next_retry_at === null ? null : timestamp(value.next_retry_at, 'next_retry_at'),
    createdAt: timestamp(value.created_at, 'created_at'),
    rowVersion,
  }
}

function decodeFailedJobSection(value: unknown): DashboardFailedJobSection {
  if (!isRecord(value)) throw new TypeError('failed job section must be an object')
  exact(value, ['failed_count', 'items'])
  if (!Array.isArray(value.items)) throw new TypeError('failed job items must be an array')
  return { failedCount: count(value.failed_count, 'failed_count'), items: value.items.map(decodeFailedJobItem) }
}

export function decodeDashboard(value: unknown): DashboardData {
  if (!isRecord(value)) throw new TypeError('dashboard must be an object')
  exact(value, ['item_limit', 'audit_tasks', 'files', 'failed_jobs'])
  if (!Number.isInteger(value.item_limit) || Number(value.item_limit) < 1 || Number(value.item_limit) > 20) throw new TypeError('item_limit is invalid')
  const itemLimit = Number(value.item_limit)
  const auditTasks = value.audit_tasks === null ? null : decodeAuditSection(value.audit_tasks)
  const files = value.files === null ? null : decodeFileSection(value.files)
  const failedJobs = value.failed_jobs === null ? null : decodeFailedJobSection(value.failed_jobs)
  if ([auditTasks, files, failedJobs].some((section) => section !== null && section.items.length > itemLimit)) throw new TypeError('dashboard section exceeds item_limit')
  return { itemLimit, auditTasks, files, failedJobs }
}

export class DashboardApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async get(itemLimit = 5, signal?: AbortSignal): Promise<DashboardData> {
    if (!Number.isInteger(itemLimit) || itemLimit < 1 || itemLimit > 20) throw new TypeError('itemLimit is invalid')
    return (await this.client.request(`/dashboard?item_limit=${itemLimit}`, { signal, decode: decodeDashboard })).data
  }
}

export const dashboardApi = new DashboardApi()
