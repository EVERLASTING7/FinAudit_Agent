import { UUID_PATTERN } from './api'

export const jobStatuses = [
  'queued',
  'running',
  'cancel_requested',
  'succeeded',
  'failed',
  'cancelled',
] as const

export type JobStatus = (typeof jobStatuses)[number]

export interface JobActionProjection {
  id: string
  status: JobStatus
  stage: string | null
  attemptNo: number
  maxAttempts: number
  rowVersion: string
  retryable: boolean
}

const positiveIntegerPattern = /^[1-9]\d*$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function decodeJobAction(value: unknown): JobActionProjection {
  const keys = ['id', 'status', 'stage', 'attempt_no', 'max_attempts', 'row_version', 'retryable']
  if (
    !isRecord(value) ||
    Object.keys(value).length !== keys.length ||
    !keys.every((key) => key in value) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.status !== 'string' ||
    !jobStatuses.includes(value.status as JobStatus) ||
    (value.stage !== null &&
      (typeof value.stage !== 'string' || value.stage.length < 1 || value.stage.length > 80)) ||
    !Number.isSafeInteger(value.attempt_no) ||
    Number(value.attempt_no) < 0 ||
    !Number.isSafeInteger(value.max_attempts) ||
    Number(value.max_attempts) < 1 ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    typeof value.retryable !== 'boolean' ||
    (value.retryable && value.status !== 'failed')
  ) {
    throw new TypeError('invalid Job action projection')
  }
  return {
    id: value.id,
    status: value.status as JobStatus,
    stage: value.stage,
    attemptNo: Number(value.attempt_no),
    maxAttempts: Number(value.max_attempts),
    rowVersion: value.row_version,
    retryable: value.retryable,
  }
}
