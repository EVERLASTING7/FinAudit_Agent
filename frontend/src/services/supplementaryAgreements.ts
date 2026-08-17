import { ApiClient, UUID_PATTERN, apiClient } from './api'
import type { ContractFieldValueType, JsonValue } from './contracts'

export const supplementaryAgreementStatuses = [
  'draft',
  'pending_confirmation',
  'confirmed',
  'rejected',
  'archived',
] as const
export const supplementaryAgreementConfirmationStatuses = [
  'unconfirmed',
  'confirmed',
  'rejected',
] as const

export type SupplementaryAgreementStatus = (typeof supplementaryAgreementStatuses)[number]
export type SupplementaryAgreementConfirmationStatus =
  (typeof supplementaryAgreementConfirmationStatuses)[number]

export interface SupplementaryAgreementHeader {
  id: string
  agreementNo: string | null
  name: string
  signedDate: string | null
  effectiveDate: string
  status: SupplementaryAgreementStatus
  confirmationStatus: SupplementaryAgreementConfirmationStatus
}

export interface SupplementaryAgreementHeaderListData {
  items: SupplementaryAgreementHeader[]
  pageSize: number
  nextCursor: string | null
}

export interface SupplementaryAgreementChange {
  id: string
  fieldCode: string
  valueType: ContractFieldValueType
  oldValue: JsonValue
  newValue: JsonValue
  evidenceBlockId: string | null
  pageNo: number | null
  quoteText: string | null
  bbox: Record<string, JsonValue> | null
  confirmationStatus: SupplementaryAgreementConfirmationStatus
}

export interface SupplementaryAgreementDetail extends SupplementaryAgreementHeader {
  contractId: string
  changes: SupplementaryAgreementChange[]
  rowVersion: string
}

export interface SupplementaryChangeInput {
  fieldCode: string
  valueType: ContractFieldValueType
  newValue: JsonValue
  evidenceBlockId: string | null
  pageNo: number | null
  quoteText: string | null
  bbox: Record<string, JsonValue> | null
}

export interface SupplementaryChangesReplaceInput {
  rowVersion: string
  reason: string
  changes: SupplementaryChangeInput[]
}

export interface EffectiveContractField {
  fieldCode: string
  valueType: ContractFieldValueType
  originalValue: JsonValue
  effectiveValue: JsonValue
  sourceAgreementId: string | null
  sourceEffectiveDate: string | null
}

export interface EffectiveContractData {
  id: string
  baselineDate: string
  confirmationStatus: SupplementaryAgreementConfirmationStatus
  fields: EffectiveContractField[]
  appliedAgreementIds: string[]
  rowVersion: string
}

const datePattern = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/
const cursorPattern = /^[A-Za-z0-9_-]+$/
const positiveIntegerPattern = /^[1-9]\d*$/
const fieldCodePattern = /^[a-z][a-z0-9_.]{0,79}$/
const decimalPattern = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/
const itemKeys = [
  'id',
  'agreement_no',
  'name',
  'signed_date',
  'effective_date',
  'status',
  'confirmation_status',
] as const
const listKeys = ['items', 'page_size', 'next_cursor'] as const
const changeKeys = [
  'id',
  'field_code',
  'value_type',
  'old_value',
  'new_value',
  'evidence_block_id',
  'page_no',
  'quote_text',
  'bbox',
  'confirmation_status',
] as const
const detailKeys = [
  'id',
  'contract_id',
  'agreement_no',
  'name',
  'signed_date',
  'effective_date',
  'status',
  'confirmation_status',
  'changes',
  'row_version',
] as const
const effectiveFieldKeys = [
  'field_code',
  'value_type',
  'original_value',
  'effective_value',
  'source_agreement_id',
  'source_effective_date',
] as const
const effectiveKeys = [
  'id',
  'baseline_date',
  'confirmation_status',
  'fields',
  'applied_agreement_ids',
  'row_version',
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actualKeys = Object.keys(value)
  return actualKeys.length === keys.length && keys.every((key) => key in value)
}

function isCalendarDate(value: string): boolean {
  if (!datePattern.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  if (year === 0) return false
  const date = new Date(0)
  date.setUTCHours(0, 0, 0, 0)
  date.setUTCFullYear(year!, month! - 1, day)
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month! - 1 &&
    date.getUTCDate() === day
  )
}

function isNullableDate(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && isCalendarDate(value))
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === 'string' && allowed.some((candidate) => candidate === value)
}

function isCursor(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    value.length <= 256 &&
    cursorPattern.test(value)
  )
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isJsonValue)
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

function isJsonObject(value: unknown): value is Record<string, JsonValue> {
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

function isTypedValue(value: JsonValue, valueType: ContractFieldValueType): boolean {
  if (value === null) return true
  if (valueType === 'string') return typeof value === 'string'
  if (valueType === 'number') return typeof value === 'string' && decimalPattern.test(value)
  if (valueType === 'date') return typeof value === 'string' && isCalendarDate(value)
  return typeof value === 'boolean' || Array.isArray(value) || isJsonObject(value)
}

function requireUuid(name: string, value: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${name} must be a canonical lowercase UUID`)
}

function requireVersion(value: string): void {
  if (!positiveIntegerPattern.test(value)) throw new TypeError('row version must be positive')
}

function requireReason(value: string): void {
  if (value.length < 1 || value.length > 1000 || value !== value.trim()) {
    throw new TypeError('reason must be trimmed and between 1 and 1000 characters')
  }
}

function requireIdempotencyKey(value: string): void {
  if (!idempotencyKeyPattern.test(value)) throw new TypeError('invalid idempotency key')
}

export function decodeSupplementaryAgreementHeader(value: unknown): SupplementaryAgreementHeader {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, itemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    (value.agreement_no !== null && typeof value.agreement_no !== 'string') ||
    typeof value.name !== 'string' ||
    !isNullableDate(value.signed_date) ||
    typeof value.effective_date !== 'string' ||
    !isCalendarDate(value.effective_date) ||
    !isOneOf(value.status, supplementaryAgreementStatuses) ||
    !isOneOf(value.confirmation_status, supplementaryAgreementConfirmationStatuses)
  ) {
    throw new TypeError('invalid supplementary agreement header')
  }

  return {
    id: value.id,
    agreementNo: value.agreement_no,
    name: value.name,
    signedDate: value.signed_date,
    effectiveDate: value.effective_date,
    status: value.status,
    confirmationStatus: value.confirmation_status,
  }
}

export function decodeSupplementaryAgreementHeaderList(
  value: unknown,
): SupplementaryAgreementHeaderListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null && !isCursor(value.next_cursor))
  ) {
    throw new TypeError('invalid supplementary agreement header list')
  }

  const items = value.items.map(decodeSupplementaryAgreementHeader)
  const pageSize = Number(value.page_size)
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid supplementary agreement header list page size')
  }

  const ids = new Set<string>()
  for (const [index, item] of items.entries()) {
    if (ids.has(item.id)) throw new TypeError('duplicate supplementary agreement header')
    ids.add(item.id)
    if (index === 0) continue
    const previous = items[index - 1]!
    if (
      previous.effectiveDate < item.effectiveDate ||
      (previous.effectiveDate === item.effectiveDate && previous.id <= item.id)
    ) {
      throw new TypeError('invalid supplementary agreement header list order')
    }
  }

  return { items, pageSize, nextCursor: value.next_cursor }
}

export function decodeSupplementaryAgreementChange(
  value: unknown,
): SupplementaryAgreementChange {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, changeKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.field_code !== 'string' ||
    !fieldCodePattern.test(value.field_code) ||
    !isOneOf(value.value_type, ['string', 'number', 'date', 'json'] as const) ||
    !isJsonValue(value.old_value) ||
    !isJsonValue(value.new_value) ||
    !isTypedValue(value.old_value, value.value_type) ||
    !isTypedValue(value.new_value, value.value_type) ||
    (value.evidence_block_id !== null &&
      (typeof value.evidence_block_id !== 'string' || !UUID_PATTERN.test(value.evidence_block_id))) ||
    (value.page_no !== null && (!Number.isInteger(value.page_no) || Number(value.page_no) < 1)) ||
    (value.quote_text !== null && typeof value.quote_text !== 'string') ||
    (value.bbox !== null && !isJsonObject(value.bbox)) ||
    !isOneOf(value.confirmation_status, supplementaryAgreementConfirmationStatuses)
  ) {
    throw new TypeError('invalid supplementary agreement change')
  }
  const evidenceParts = [value.evidence_block_id, value.page_no, value.quote_text]
  if (
    (evidenceParts.some((item) => item !== null) && evidenceParts.some((item) => item === null)) ||
    (value.bbox !== null && value.evidence_block_id === null) ||
    (typeof value.quote_text === 'string' &&
      (value.quote_text.length < 1 ||
        value.quote_text.length > 4000 ||
        value.quote_text !== value.quote_text.trim()))
  ) {
    throw new TypeError('invalid supplementary agreement change evidence')
  }

  return {
    id: value.id,
    fieldCode: value.field_code,
    valueType: value.value_type,
    oldValue: value.old_value,
    newValue: value.new_value,
    evidenceBlockId: value.evidence_block_id,
    pageNo: value.page_no === null ? null : Number(value.page_no),
    quoteText: value.quote_text,
    bbox: value.bbox,
    confirmationStatus: value.confirmation_status,
  }
}

export function decodeSupplementaryAgreementDetail(
  value: unknown,
): SupplementaryAgreementDetail {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, detailKeys) ||
    typeof value.contract_id !== 'string' ||
    !UUID_PATTERN.test(value.contract_id) ||
    !Array.isArray(value.changes) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid supplementary agreement detail')
  }
  const header = decodeSupplementaryAgreementHeader(
    Object.fromEntries(itemKeys.map((key) => [key, value[key]])),
  )
  const changes = value.changes.map(decodeSupplementaryAgreementChange)
  const codes = changes.map((change) => change.fieldCode)
  if (codes.some((code, index) => index > 0 && codes[index - 1]! >= code)) {
    throw new TypeError('supplementary agreement changes must be unique and sorted')
  }
  return {
    ...header,
    contractId: value.contract_id,
    changes,
    rowVersion: value.row_version,
  }
}

export function decodeEffectiveContractData(value: unknown): EffectiveContractData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, effectiveKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.baseline_date !== 'string' ||
    !isCalendarDate(value.baseline_date) ||
    !isOneOf(value.confirmation_status, supplementaryAgreementConfirmationStatuses) ||
    !Array.isArray(value.fields) ||
    !Array.isArray(value.applied_agreement_ids) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid effective contract data')
  }

  const fields: EffectiveContractField[] = value.fields.map((field) => {
    if (
      !isRecord(field) ||
      !hasExactKeys(field, effectiveFieldKeys) ||
      typeof field.field_code !== 'string' ||
      !fieldCodePattern.test(field.field_code) ||
      !isOneOf(field.value_type, ['string', 'number', 'date', 'json'] as const) ||
      !isJsonValue(field.original_value) ||
      !isJsonValue(field.effective_value) ||
      !isTypedValue(field.original_value, field.value_type) ||
      !isTypedValue(field.effective_value, field.value_type) ||
      (field.source_agreement_id !== null &&
        (typeof field.source_agreement_id !== 'string' ||
          !UUID_PATTERN.test(field.source_agreement_id))) ||
      !isNullableDate(field.source_effective_date) ||
      (field.source_agreement_id === null) !== (field.source_effective_date === null)
    ) {
      throw new TypeError('invalid effective contract field')
    }
    return {
      fieldCode: field.field_code,
      valueType: field.value_type,
      originalValue: field.original_value,
      effectiveValue: field.effective_value,
      sourceAgreementId: field.source_agreement_id,
      sourceEffectiveDate: field.source_effective_date,
    }
  })
  if (fields.some((field, index) => index > 0 && fields[index - 1]!.fieldCode >= field.fieldCode)) {
    throw new TypeError('effective contract fields must be unique and sorted')
  }
  if (
    !value.applied_agreement_ids.every(
      (item): item is string => typeof item === 'string' && UUID_PATTERN.test(item),
    ) ||
    new Set(value.applied_agreement_ids).size !== value.applied_agreement_ids.length
  ) {
    throw new TypeError('invalid applied supplementary agreement ids')
  }
  return {
    id: value.id,
    baselineDate: value.baseline_date,
    confirmationStatus: value.confirmation_status,
    fields,
    appliedAgreementIds: [...value.applied_agreement_ids],
    rowVersion: value.row_version,
  }
}

function validateChangeInput(change: SupplementaryChangeInput): void {
  if (!fieldCodePattern.test(change.fieldCode)) throw new TypeError('invalid field code')
  if (!isOneOf(change.valueType, ['string', 'number', 'date', 'json'] as const)) {
    throw new TypeError('invalid field value type')
  }
  if (!isJsonValue(change.newValue) || !isTypedValue(change.newValue, change.valueType)) {
    throw new TypeError('invalid supplementary agreement new value')
  }
  if (change.evidenceBlockId !== null) requireUuid('evidence block id', change.evidenceBlockId)
  if (
    change.pageNo !== null &&
    (!Number.isInteger(change.pageNo) || change.pageNo < 1)
  ) {
    throw new TypeError('page number must be a positive integer')
  }
  if (
    change.quoteText !== null &&
    (change.quoteText.length < 1 ||
      change.quoteText.length > 4000 ||
      change.quoteText !== change.quoteText.trim())
  ) {
    throw new TypeError('quote text must be trimmed and between 1 and 4000 characters')
  }
  const evidenceParts = [change.evidenceBlockId, change.pageNo, change.quoteText]
  if (evidenceParts.some((item) => item !== null) && evidenceParts.some((item) => item === null)) {
    throw new TypeError('evidence block, page and quote must be provided together')
  }
  if (change.bbox !== null && change.evidenceBlockId === null) {
    throw new TypeError('bbox requires complete evidence')
  }
  if (change.bbox !== null && !isJsonObject(change.bbox)) throw new TypeError('invalid bbox')
}

export class SupplementaryAgreementApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async listHeaders(
    contractId: string,
    pageSize = 20,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<SupplementaryAgreementHeaderListData> {
    if (!UUID_PATTERN.test(contractId)) {
      throw new TypeError('contract id must be a canonical lowercase UUID')
    }
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }
    if (cursor !== undefined && !isCursor(cursor)) {
      throw new TypeError('cursor must be a canonical base64url string')
    }

    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(
      `/contracts/${contractId}/supplementary-agreements?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeSupplementaryAgreementHeaderList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('supplementary agreement header list page size does not match request')
    }
    return response.data
  }

  async getDetail(
    contractId: string,
    agreementId: string,
    signal?: AbortSignal,
  ): Promise<SupplementaryAgreementDetail> {
    requireUuid('contract id', contractId)
    requireUuid('agreement id', agreementId)
    const response = await this.client.request(
      `/contracts/${contractId}/supplementary-agreements/${agreementId}`,
      { signal, decode: decodeSupplementaryAgreementDetail },
    )
    if (response.data.contractId !== contractId || response.data.id !== agreementId) {
      throw new TypeError('supplementary agreement detail identity mismatch')
    }
    return response.data
  }

  async replaceChanges(
    contractId: string,
    agreementId: string,
    input: SupplementaryChangesReplaceInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SupplementaryAgreementDetail> {
    requireUuid('contract id', contractId)
    requireUuid('agreement id', agreementId)
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    if (input.changes.length < 1 || input.changes.length > 100) {
      throw new TypeError('changes must contain between 1 and 100 items')
    }
    if (new Set(input.changes.map((change) => change.fieldCode)).size !== input.changes.length) {
      throw new TypeError('changes must contain unique field codes')
    }
    input.changes.forEach(validateChangeInput)
    const response = await this.client.request(
      `/contracts/${contractId}/supplementary-agreements/${agreementId}/changes`,
      {
        method: 'PUT',
        body: {
          row_version: input.rowVersion,
          reason: input.reason,
          changes: input.changes.map((change) => ({
            field_code: change.fieldCode,
            value_type: change.valueType,
            new_value: change.newValue,
            evidence_block_id: change.evidenceBlockId,
            page_no: change.pageNo,
            quote_text: change.quoteText,
            bbox: change.bbox,
          })),
        },
        idempotencyKey,
        signal,
        decode: decodeSupplementaryAgreementDetail,
      },
    )
    if (response.data.contractId !== contractId || response.data.id !== agreementId) {
      throw new TypeError('supplementary agreement mutation identity mismatch')
    }
    return response.data
  }

  async decide(
    contractId: string,
    agreementId: string,
    input: { rowVersion: string; decision: 'confirmed' | 'rejected'; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SupplementaryAgreementDetail> {
    requireUuid('contract id', contractId)
    requireUuid('agreement id', agreementId)
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(
      `/contracts/${contractId}/supplementary-agreements/${agreementId}/decision`,
      {
        method: 'POST',
        body: {
          row_version: input.rowVersion,
          decision: input.decision,
          reason: input.reason,
        },
        idempotencyKey,
        signal,
        decode: decodeSupplementaryAgreementDetail,
      },
    )
    if (response.data.contractId !== contractId || response.data.id !== agreementId) {
      throw new TypeError('supplementary agreement mutation identity mismatch')
    }
    return response.data
  }

  async getEffectiveFields(
    contractId: string,
    baselineDate: string,
    signal?: AbortSignal,
  ): Promise<EffectiveContractData> {
    requireUuid('contract id', contractId)
    if (!isCalendarDate(baselineDate)) throw new TypeError('baseline date must be a calendar date')
    const response = await this.client.request(
      `/contracts/${contractId}/effective-fields?baseline_date=${encodeURIComponent(baselineDate)}`,
      { signal, decode: decodeEffectiveContractData },
    )
    if (response.data.id !== contractId || response.data.baselineDate !== baselineDate) {
      throw new TypeError('effective contract identity mismatch')
    }
    return response.data
  }
}

export const supplementaryAgreementApi = new SupplementaryAgreementApi()
