import { ApiClient, UUID_PATTERN, apiClient } from './api'
import { decodeJobAction, type JobActionProjection } from './jobs'

export const auditTaskStatuses = ['open', 'completed', 'archived'] as const
export const auditExecutionStatuses = [
  'draft',
  'validating',
  'queued',
  'running',
  'pending_finance_review',
  'pending_audit_review',
  'returned_for_correction',
  'completed',
  'failed',
  'cancelled',
  'outdated',
] as const
export const auditRuleStatuses = ['passed', 'failed', 'not_applicable', 'error'] as const
export const auditRiskLevels = ['none', 'notice', 'low', 'medium', 'high'] as const
export const auditRiskReviewStatuses = [
  'pending',
  'confirmed',
  'dismissed',
  'adjusted',
  'returned',
] as const
export const aiArtifactStatuses = ['disabled', 'succeeded', 'degraded'] as const

export type AuditTaskStatus = (typeof auditTaskStatuses)[number]
export type AuditExecutionStatus = (typeof auditExecutionStatuses)[number]
export type AuditRuleStatus = (typeof auditRuleStatuses)[number]
export type AuditRiskLevel = (typeof auditRiskLevels)[number]
export type AuditRiskReviewStatus = (typeof auditRiskReviewStatuses)[number]
export type AiArtifactStatus = (typeof aiArtifactStatuses)[number]

export interface AuditRiskExplanationCitationData {
  candidateId: string
  policyDocumentId: string
  chunkId: string
  quote: string
}

export interface AuditRiskExplanationData {
  summary: string
  reasoningSummary: string
  businessImpact: string | null
  recommendedAction: string
  citations: AuditRiskExplanationCitationData[]
  evidenceSufficient: boolean
  warnings: string[]
}

export interface AuditTaskData {
  id: string
  taskNo: string
  name: string
  description: string | null
  ownerId: string
  currentExecutionId: string | null
  status: AuditTaskStatus
  rowVersion: string
  createdAt: string
  updatedAt: string
}

export interface AuditExecutionData {
  id: string
  auditTaskId: string
  versionNo: number
  baselineDate: string
  status: AuditExecutionStatus
  snapshotSha256: string | null
  jobId: string | null
  job: JobActionProjection | null
  financeReviewerId: string | null
  financeReviewedAt: string | null
  auditReviewerId: string | null
  auditReviewedAt: string | null
  retryable: boolean
  failureCode: string | null
  cancelReason: string | null
  returnReason: string | null
  rowVersion: string
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  outdatedAt: string | null
}

export interface AuditRuleExecutionData {
  id: string
  ruleCode: string
  status: AuditRuleStatus
  actualValue: string | null
  expectedValue: string | null
  applicabilityReason: string | null
  includedItemIds: string[]
  excludedItemIds: string[]
}

export interface AuditRiskData {
  id: string
  ruleCode: string
  title: string
  originalLevel: AuditRiskLevel
  effectiveLevel: AuditRiskLevel
  reviewStatus: AuditRiskReviewStatus
  actualValue: string | null
  expectedValue: string | null
  reviewReason: string | null
  reviewedBy: string | null
  reviewedAt: string | null
  rowVersion: string
  aiExplanationStatus: AiArtifactStatus
  aiExplanation: AuditRiskExplanationData | null
}

export interface AuditTaskDetailData {
  task: AuditTaskData
  execution: AuditExecutionData
  rules: AuditRuleExecutionData[]
  risks: AuditRiskData[]
}

export interface AuditTaskListData {
  items: AuditTaskData[]
  pageSize: number
  nextCursor: string | null
}

export interface AuditTaskMutationData {
  task: AuditTaskData
  execution: AuditExecutionData
}

export interface AuditExecutionMutationData {
  execution: AuditExecutionData
}

export interface AuditRetryData {
  executionId: string
  status: 'queued'
  preservedResults: true
  executionRowVersion: string
  jobId: string
  jobStatus: 'queued'
  attemptNo: number
  scheduledAttemptNo: number
  stage: 'evaluate'
  jobRowVersion: string
}

export interface AuditCancelData {
  executionId: string
  executionStatus: 'cancelled'
  cancelledAt: string
  executionRowVersion: string
  jobId: string | null
  jobStatus: 'cancel_requested' | 'cancelled' | 'succeeded' | null
  jobRowVersion: string | null
}

export interface AuditRiskMutationData {
  risk: AuditRiskData
}

export interface AuditTaskCreateInput {
  taskNo: string
  name: string
  description: string | null
  baselineDate: string
  contractId: string | null
  invoiceIds: string[]
}

const positiveIntegerPattern = /^[1-9]\d*$/
const datePattern = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/
const taskNoPattern = /^[A-Z0-9][A-Z0-9._/-]*$/
const cursorPattern = /^[A-Za-z0-9_-]+$/
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/
const hashPattern = /^[0-9a-f]{64}$/

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

function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value)
}

function isNullableUuid(value: unknown): value is string | null {
  return value === null || isUuid(value)
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  )
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isTimestamp(value)
}

function isNullableText(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string' || !datePattern.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  if (year === 0) return false
  const date = new Date(0)
  date.setUTCHours(0, 0, 0, 0)
  date.setUTCFullYear(year!, month! - 1, day)
  return date.getUTCFullYear() === year && date.getUTCMonth() === month! - 1 && date.getUTCDate() === day
}

function decodeUuidArray(value: unknown): string[] {
  if (!Array.isArray(value) || !value.every(isUuid) || new Set(value).size !== value.length) {
    throw new TypeError('invalid audit UUID array')
  }
  return [...value]
}

const taskKeys = [
  'id', 'task_no', 'name', 'description', 'owner_id', 'current_execution_id', 'status',
  'row_version', 'created_at', 'updated_at',
] as const

export function decodeAuditTask(value: unknown): AuditTaskData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, taskKeys) ||
    !isUuid(value.id) ||
    typeof value.task_no !== 'string' ||
    !taskNoPattern.test(value.task_no) ||
    typeof value.name !== 'string' ||
    value.name.length < 1 ||
    !isNullableText(value.description) ||
    !isUuid(value.owner_id) ||
    !isNullableUuid(value.current_execution_id) ||
    !isOneOf(value.status, auditTaskStatuses) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    !isTimestamp(value.created_at) ||
    !isTimestamp(value.updated_at)
  ) {
    throw new TypeError('invalid audit task')
  }
  return {
    id: value.id,
    taskNo: value.task_no,
    name: value.name,
    description: value.description,
    ownerId: value.owner_id,
    currentExecutionId: value.current_execution_id,
    status: value.status,
    rowVersion: value.row_version,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  }
}

const executionKeys = [
  'id', 'audit_task_id', 'version_no', 'baseline_date', 'status', 'snapshot_sha256',
  'job_id', 'job', 'finance_reviewer_id', 'finance_reviewed_at', 'audit_reviewer_id',
  'audit_reviewed_at', 'retryable', 'failure_code', 'cancel_reason', 'return_reason',
  'row_version', 'created_at', 'started_at', 'finished_at', 'outdated_at',
] as const

export function decodeAuditExecution(value: unknown): AuditExecutionData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, executionKeys) ||
    !isUuid(value.id) ||
    !isUuid(value.audit_task_id) ||
    !Number.isSafeInteger(value.version_no) ||
    Number(value.version_no) < 1 ||
    !isCalendarDate(value.baseline_date) ||
    !isOneOf(value.status, auditExecutionStatuses) ||
    (value.snapshot_sha256 !== null && (typeof value.snapshot_sha256 !== 'string' || !hashPattern.test(value.snapshot_sha256))) ||
    !isNullableUuid(value.job_id) ||
    !isNullableUuid(value.finance_reviewer_id) ||
    !isNullableTimestamp(value.finance_reviewed_at) ||
    !isNullableUuid(value.audit_reviewer_id) ||
    !isNullableTimestamp(value.audit_reviewed_at) ||
    typeof value.retryable !== 'boolean' ||
    !isNullableText(value.failure_code) ||
    !isNullableText(value.cancel_reason) ||
    !isNullableText(value.return_reason) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    !isTimestamp(value.created_at) ||
    !isNullableTimestamp(value.started_at) ||
    !isNullableTimestamp(value.finished_at) ||
    !isNullableTimestamp(value.outdated_at)
  ) {
    throw new TypeError('invalid audit execution')
  }
  const job = value.job === null ? null : decodeJobAction(value.job)
  if (job !== null && job.id !== value.job_id) throw new TypeError('audit Job identity mismatch')
  return {
    id: value.id,
    auditTaskId: value.audit_task_id,
    versionNo: Number(value.version_no),
    baselineDate: value.baseline_date,
    status: value.status,
    snapshotSha256: value.snapshot_sha256,
    jobId: value.job_id,
    job,
    financeReviewerId: value.finance_reviewer_id,
    financeReviewedAt: value.finance_reviewed_at,
    auditReviewerId: value.audit_reviewer_id,
    auditReviewedAt: value.audit_reviewed_at,
    retryable: value.retryable,
    failureCode: value.failure_code,
    cancelReason: value.cancel_reason,
    returnReason: value.return_reason,
    rowVersion: value.row_version,
    createdAt: value.created_at,
    startedAt: value.started_at,
    finishedAt: value.finished_at,
    outdatedAt: value.outdated_at,
  }
}

export function decodeAuditRetry(value: unknown): AuditRetryData {
  const keys = [
    'execution_id', 'status', 'preserved_results', 'execution_row_version', 'job_id',
    'job_status', 'attempt_no', 'scheduled_attempt_no', 'stage', 'job_row_version',
  ]
  if (
    !isRecord(value) ||
    !hasExactKeys(value, keys) ||
    !isUuid(value.execution_id) ||
    value.status !== 'queued' ||
    value.preserved_results !== true ||
    typeof value.execution_row_version !== 'string' ||
    !positiveIntegerPattern.test(value.execution_row_version) ||
    !isUuid(value.job_id) ||
    value.job_status !== 'queued' ||
    !Number.isSafeInteger(value.attempt_no) ||
    Number(value.attempt_no) < 1 ||
    value.scheduled_attempt_no !== Number(value.attempt_no) + 1 ||
    value.stage !== 'evaluate' ||
    typeof value.job_row_version !== 'string' ||
    !positiveIntegerPattern.test(value.job_row_version)
  ) {
    throw new TypeError('invalid audit retry response')
  }
  return {
    executionId: value.execution_id,
    status: 'queued',
    preservedResults: true,
    executionRowVersion: value.execution_row_version,
    jobId: value.job_id,
    jobStatus: 'queued',
    attemptNo: Number(value.attempt_no),
    scheduledAttemptNo: Number(value.scheduled_attempt_no),
    stage: 'evaluate',
    jobRowVersion: value.job_row_version,
  }
}

export function decodeAuditCancel(value: unknown): AuditCancelData {
  const keys = [
    'execution_id', 'execution_status', 'cancelled_at', 'execution_row_version',
    'job_id', 'job_status', 'job_row_version',
  ]
  if (
    !isRecord(value) ||
    !hasExactKeys(value, keys) ||
    !isUuid(value.execution_id) ||
    value.execution_status !== 'cancelled' ||
    !isTimestamp(value.cancelled_at) ||
    typeof value.execution_row_version !== 'string' ||
    !positiveIntegerPattern.test(value.execution_row_version) ||
    !isNullableUuid(value.job_id) ||
    (value.job_status !== null &&
      !['cancel_requested', 'cancelled', 'succeeded'].includes(String(value.job_status))) ||
    (value.job_row_version !== null &&
      (typeof value.job_row_version !== 'string' ||
        !positiveIntegerPattern.test(value.job_row_version))) ||
    new Set([
      value.job_id === null,
      value.job_status === null,
      value.job_row_version === null,
    ]).size !== 1
  ) {
    throw new TypeError('invalid audit cancel response')
  }
  return {
    executionId: value.execution_id,
    executionStatus: 'cancelled',
    cancelledAt: value.cancelled_at,
    executionRowVersion: value.execution_row_version,
    jobId: value.job_id,
    jobStatus: value.job_status as AuditCancelData['jobStatus'],
    jobRowVersion: value.job_row_version,
  }
}

const ruleKeys = [
  'id', 'rule_code', 'status', 'actual_value', 'expected_value', 'applicability_reason',
  'included_item_ids', 'excluded_item_ids',
] as const

function decodeAuditRule(value: unknown): AuditRuleExecutionData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ruleKeys) ||
    !isUuid(value.id) ||
    typeof value.rule_code !== 'string' ||
    value.rule_code.length < 1 ||
    !isOneOf(value.status, auditRuleStatuses) ||
    !isNullableText(value.actual_value) ||
    !isNullableText(value.expected_value) ||
    !isNullableText(value.applicability_reason)
  ) {
    throw new TypeError('invalid audit rule execution')
  }
  return {
    id: value.id,
    ruleCode: value.rule_code,
    status: value.status,
    actualValue: value.actual_value,
    expectedValue: value.expected_value,
    applicabilityReason: value.applicability_reason,
    includedItemIds: decodeUuidArray(value.included_item_ids),
    excludedItemIds: decodeUuidArray(value.excluded_item_ids),
  }
}

const riskKeys = [
  'id', 'rule_code', 'title', 'original_level', 'effective_level', 'review_status',
  'actual_value', 'expected_value', 'review_reason', 'reviewed_by', 'reviewed_at', 'row_version',
  'ai_explanation_status', 'ai_explanation',
] as const

const riskExplanationKeys = [
  'summary', 'reasoning_summary', 'business_impact', 'recommended_action', 'citations',
  'evidence_sufficient', 'warnings',
] as const

const riskExplanationCitationKeys = [
  'candidate_id', 'policy_document_id', 'chunk_id', 'quote',
] as const

function decodeTextArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw new TypeError(`invalid ${label}`)
  }
  return [...value]
}

function decodeRiskExplanationCitation(value: unknown): AuditRiskExplanationCitationData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, riskExplanationCitationKeys) ||
    !isUuid(value.candidate_id) ||
    !isUuid(value.policy_document_id) ||
    !isUuid(value.chunk_id) ||
    typeof value.quote !== 'string'
  ) {
    throw new TypeError('invalid audit risk explanation citation')
  }
  return {
    candidateId: value.candidate_id,
    policyDocumentId: value.policy_document_id,
    chunkId: value.chunk_id,
    quote: value.quote,
  }
}

function decodeRiskExplanation(value: unknown): AuditRiskExplanationData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, riskExplanationKeys) ||
    typeof value.summary !== 'string' ||
    typeof value.reasoning_summary !== 'string' ||
    !isNullableText(value.business_impact) ||
    typeof value.recommended_action !== 'string' ||
    !Array.isArray(value.citations) ||
    typeof value.evidence_sufficient !== 'boolean'
  ) {
    throw new TypeError('invalid audit risk explanation')
  }
  return {
    summary: value.summary,
    reasoningSummary: value.reasoning_summary,
    businessImpact: value.business_impact,
    recommendedAction: value.recommended_action,
    citations: value.citations.map(decodeRiskExplanationCitation),
    evidenceSufficient: value.evidence_sufficient,
    warnings: decodeTextArray(value.warnings, 'audit risk explanation warnings'),
  }
}

export function decodeAuditRisk(value: unknown): AuditRiskData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, riskKeys) ||
    !isUuid(value.id) ||
    typeof value.rule_code !== 'string' ||
    value.rule_code.length < 1 ||
    typeof value.title !== 'string' ||
    value.title.length < 1 ||
    !isOneOf(value.original_level, auditRiskLevels) ||
    !isOneOf(value.effective_level, auditRiskLevels) ||
    !isOneOf(value.review_status, auditRiskReviewStatuses) ||
    !isNullableText(value.actual_value) ||
    !isNullableText(value.expected_value) ||
    !isNullableText(value.review_reason) ||
    !isNullableUuid(value.reviewed_by) ||
    !isNullableTimestamp(value.reviewed_at) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    !isOneOf(value.ai_explanation_status, aiArtifactStatuses)
  ) {
    throw new TypeError('invalid audit risk')
  }
  const aiExplanation = value.ai_explanation === null
    ? null
    : decodeRiskExplanation(value.ai_explanation)
  if ((value.ai_explanation_status === 'succeeded') !== (aiExplanation !== null)) {
    throw new TypeError('invalid audit risk AI explanation state')
  }
  return {
    id: value.id,
    ruleCode: value.rule_code,
    title: value.title,
    originalLevel: value.original_level,
    effectiveLevel: value.effective_level,
    reviewStatus: value.review_status,
    actualValue: value.actual_value,
    expectedValue: value.expected_value,
    reviewReason: value.review_reason,
    reviewedBy: value.reviewed_by,
    reviewedAt: value.reviewed_at,
    rowVersion: value.row_version,
    aiExplanationStatus: value.ai_explanation_status,
    aiExplanation,
  }
}

export function decodeAuditTaskDetail(value: unknown): AuditTaskDetailData {
  if (!isRecord(value) || !hasExactKeys(value, ['task', 'execution', 'rules', 'risks']) || !Array.isArray(value.rules) || !Array.isArray(value.risks)) {
    throw new TypeError('invalid audit task detail')
  }
  const task = decodeAuditTask(value.task)
  const execution = decodeAuditExecution(value.execution)
  const rules = value.rules.map(decodeAuditRule)
  const risks = value.risks.map(decodeAuditRisk)
  if (execution.auditTaskId !== task.id || task.currentExecutionId !== execution.id) {
    throw new TypeError('audit task detail identity mismatch')
  }
  return { task, execution, rules, risks }
}

export function decodeAuditTaskList(value: unknown): AuditTaskListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['items', 'page_size', 'next_cursor']) ||
    !Array.isArray(value.items) ||
    !Number.isSafeInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null && (typeof value.next_cursor !== 'string' || !cursorPattern.test(value.next_cursor)))
  ) {
    throw new TypeError('invalid audit task list')
  }
  const items = value.items.map(decodeAuditTask)
  if (items.length > Number(value.page_size) || new Set(items.map((item) => item.id)).size !== items.length) {
    throw new TypeError('invalid audit task list page')
  }
  return { items, pageSize: Number(value.page_size), nextCursor: value.next_cursor }
}

export function decodeAuditTaskMutation(value: unknown): AuditTaskMutationData {
  if (!isRecord(value) || !hasExactKeys(value, ['task', 'execution'])) throw new TypeError('invalid audit task mutation')
  const task = decodeAuditTask(value.task)
  const execution = decodeAuditExecution(value.execution)
  if (execution.auditTaskId !== task.id || task.currentExecutionId !== execution.id) throw new TypeError('audit task mutation identity mismatch')
  return { task, execution }
}

export function decodeAuditExecutionMutation(value: unknown): AuditExecutionMutationData {
  if (!isRecord(value) || !hasExactKeys(value, ['execution'])) throw new TypeError('invalid audit execution mutation')
  return { execution: decodeAuditExecution(value.execution) }
}

export function decodeAuditRiskMutation(value: unknown): AuditRiskMutationData {
  if (!isRecord(value) || !hasExactKeys(value, ['risk'])) throw new TypeError('invalid audit risk mutation')
  return { risk: decodeAuditRisk(value.risk) }
}

function requireUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${label} must be a canonical lowercase UUID`)
}

function requireVersion(value: string): void {
  if (!positiveIntegerPattern.test(value)) throw new TypeError('row version must be positive')
}

function requireReason(value: string): void {
  if (value.length < 1 || value.length > 1000 || value !== value.trim()) throw new TypeError('reason must be trimmed and between 1 and 1000 characters')
}

function requireIdempotencyKey(value: string): void {
  if (!idempotencyKeyPattern.test(value)) throw new TypeError('invalid idempotency key')
}

function validateCreateInput(input: AuditTaskCreateInput): void {
  if (!taskNoPattern.test(input.taskNo) || input.taskNo.length > 80) throw new TypeError('invalid audit task number')
  if (input.name.length < 1 || input.name.length > 300 || input.name !== input.name.trim()) throw new TypeError('invalid audit task name')
  if (input.description !== null && (input.description.length < 1 || input.description.length > 4000 || input.description !== input.description.trim())) throw new TypeError('invalid audit task description')
  if (!isCalendarDate(input.baselineDate)) throw new TypeError('invalid audit baseline date')
  if (input.contractId !== null) requireUuid(input.contractId, 'contract id')
  if (input.invoiceIds.length < 1 || input.invoiceIds.length > 100 || new Set(input.invoiceIds).size !== input.invoiceIds.length) throw new TypeError('invalid audit invoice ids')
  input.invoiceIds.forEach((id) => requireUuid(id, 'invoice id'))
  if (input.invoiceIds.some((id, index) => index > 0 && input.invoiceIds[index - 1]! >= id)) throw new TypeError('audit invoice ids must be sorted')
}

export class AuditApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<AuditTaskListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new TypeError('invalid audit page size')
    if (cursor !== undefined && (cursor.length < 1 || cursor.length > 256 || !cursorPattern.test(cursor))) throw new TypeError('invalid audit cursor')
    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(`/audit-tasks?page_size=${pageSize}${cursorQuery}`, { signal, decode: decodeAuditTaskList })
    if (response.data.pageSize !== pageSize) throw new TypeError('audit page size mismatch')
    return response.data
  }

  async getTask(taskId: string, signal?: AbortSignal): Promise<AuditTaskDetailData> {
    requireUuid(taskId, 'task id')
    const response = await this.client.request(`/audit-tasks/${taskId}`, { signal, decode: decodeAuditTaskDetail })
    if (response.data.task.id !== taskId) throw new TypeError('audit task id mismatch')
    return response.data
  }

  async createTask(input: AuditTaskCreateInput, idempotencyKey: string, signal?: AbortSignal): Promise<AuditTaskMutationData> {
    validateCreateInput(input)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request('/audit-tasks', {
      method: 'POST',
      body: {
        task_no: input.taskNo,
        name: input.name,
        description: input.description,
        baseline_date: input.baselineDate,
        contract_id: input.contractId,
        invoice_ids: input.invoiceIds,
      },
      idempotencyKey,
      signal,
      decode: decodeAuditTaskMutation,
    })
    return response.data
  }

  async createExecution(taskId: string, input: { taskRowVersion: string; baselineDate: string; reason: string }, idempotencyKey: string, signal?: AbortSignal): Promise<AuditTaskMutationData> {
    requireUuid(taskId, 'task id')
    requireVersion(input.taskRowVersion)
    if (!isCalendarDate(input.baselineDate)) throw new TypeError('invalid audit baseline date')
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/audit-tasks/${taskId}/executions`, {
      method: 'POST',
      body: { task_row_version: input.taskRowVersion, baseline_date: input.baselineDate, reason: input.reason },
      idempotencyKey,
      signal,
      decode: decodeAuditTaskMutation,
    })
    return response.data
  }

  async reviewRisk(riskId: string, lane: 'non-high' | 'high', input: { rowVersion: string; decision: 'confirmed' | 'dismissed' | 'adjusted'; effectiveLevel: AuditRiskLevel | null; reason: string }, idempotencyKey: string, signal?: AbortSignal): Promise<AuditRiskMutationData> {
    requireUuid(riskId, 'risk id')
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    if ((input.decision === 'adjusted') !== (input.effectiveLevel !== null)) throw new TypeError('invalid adjusted audit risk decision')
    const response = await this.client.request(`/audit-risks/${riskId}/reviews/${lane}`, {
      method: 'POST',
      body: { row_version: input.rowVersion, decision: input.decision, effective_level: input.effectiveLevel, reason: input.reason },
      idempotencyKey,
      signal,
      decode: decodeAuditRiskMutation,
    })
    if (response.data.risk.id !== riskId) throw new TypeError('audit risk id mismatch')
    return response.data
  }

  async financeReview(executionId: string, input: { rowVersion: string; decision: 'submit' | 'return'; reason: string }, idempotencyKey: string, signal?: AbortSignal): Promise<AuditExecutionMutationData> {
    return this.executionDecision(executionId, 'finance-review', input, idempotencyKey, signal)
  }

  async auditReview(executionId: string, input: { rowVersion: string; decision: 'complete' | 'return'; reason: string }, idempotencyKey: string, signal?: AbortSignal): Promise<AuditExecutionMutationData> {
    return this.executionDecision(executionId, 'audit-review', input, idempotencyKey, signal)
  }

  async retryExecution(
    executionId: string,
    input: { executionRowVersion: string; jobRowVersion: string; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AuditRetryData> {
    requireUuid(executionId, 'execution id')
    requireVersion(input.executionRowVersion)
    requireVersion(input.jobRowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/audit-executions/${executionId}/retry`, {
      method: 'POST',
      body: {
        execution_row_version: input.executionRowVersion,
        job_row_version: input.jobRowVersion,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeAuditRetry,
    })
    if (response.data.executionId !== executionId) throw new TypeError('audit retry id mismatch')
    return response.data
  }

  async cancelExecution(
    executionId: string,
    input: { executionRowVersion: string; jobRowVersion: string | null; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AuditCancelData> {
    requireUuid(executionId, 'execution id')
    requireVersion(input.executionRowVersion)
    if (input.jobRowVersion !== null) requireVersion(input.jobRowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/audit-executions/${executionId}/cancel`, {
      method: 'POST',
      body: {
        execution_row_version: input.executionRowVersion,
        job_row_version: input.jobRowVersion,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeAuditCancel,
    })
    if (response.data.executionId !== executionId) throw new TypeError('audit cancel id mismatch')
    return response.data
  }

  private async executionDecision(executionId: string, path: 'finance-review' | 'audit-review', input: { rowVersion: string; decision: string; reason: string }, idempotencyKey: string, signal?: AbortSignal): Promise<AuditExecutionMutationData> {
    requireUuid(executionId, 'execution id')
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/audit-executions/${executionId}/${path}`, {
      method: 'POST',
      body: { row_version: input.rowVersion, decision: input.decision, reason: input.reason },
      idempotencyKey,
      signal,
      decode: decodeAuditExecutionMutation,
    })
    if (response.data.execution.id !== executionId) throw new TypeError('audit execution id mismatch')
    return response.data
  }
}

export const auditApi = new AuditApi()
