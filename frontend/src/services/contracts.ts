import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const contractConfirmationStatuses = ['unconfirmed', 'confirmed', 'rejected'] as const
export const contractStatuses = ['draft', 'active', 'expired', 'terminated', 'archived'] as const

export type ContractConfirmationStatus = (typeof contractConfirmationStatuses)[number]
export type ContractStatus = (typeof contractStatuses)[number]

type NullableText = string | null
type NullableDecimal = string | null

export const contractFieldCodes = [
  'contract_no',
  'name',
  'party_a_name',
  'party_a_tax_no',
  'party_b_name',
  'party_b_tax_no',
  'amount',
  'currency',
  'signed_date',
  'effective_date',
  'expiry_date',
  'payment_method',
  'payment_terms',
] as const

export type ContractFieldCode = (typeof contractFieldCodes)[number]
export type ContractFieldValueType = 'string' | 'number' | 'date' | 'json'
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

export interface ContractListItem {
  id: string
  contractNo: NullableText
  name: string
  partyBName: NullableText
  amount: NullableDecimal
  currency: NullableText
  effectiveDate: NullableText
  expiryDate: NullableText
  confirmationStatus: ContractConfirmationStatus
  status: ContractStatus
}

export interface ContractListData {
  items: ContractListItem[]
  pageSize: number
  nextCursor: string | null
}

export interface ContractDetail extends ContractListItem {
  partyAName: NullableText
  partyATaxNo: NullableText
  partyBTaxNo: NullableText
  signedDate: NullableText
  paymentMethod: NullableText
  paymentTerms: NullableText
  rowVersion: string
}

export interface ContractEvidence {
  blockId: string
  parseVersionId: string
  pageNo: number
  quoteText: string
  bbox: Record<string, JsonValue> | null
  confidence: NullableDecimal
}

export interface ContractFieldCandidate {
  fieldCode: ContractFieldCode
  valueType: ContractFieldValueType
  candidateValue: unknown
  confirmedValue: unknown
  confirmationStatus: ContractConfirmationStatus
  evidence: ContractEvidence | null
}

export interface ContractEvidenceResponseData {
  contractId: string
  fileId: string
  rowVersion: string
  fields: ContractFieldCandidate[]
}

export interface ContractCorrectionHistoryItem {
  id: string
  fieldPath: string
  beforeValue: Record<string, JsonValue> | null
  afterValue: Record<string, JsonValue> | null
  reason: string
  actorId: string
  actorRoleCode: string
  createdAt: string
  traceId: string
}

export interface ContractCorrectionHistoryData {
  contractId: string
  items: ContractCorrectionHistoryItem[]
}

export interface ContractFactsInput {
  contractNo: NullableText
  name: NullableText
  partyAName: NullableText
  partyATaxNo: NullableText
  partyBName: NullableText
  partyBTaxNo: NullableText
  amount: NullableDecimal
  currency: NullableText
  signedDate: NullableText
  effectiveDate: NullableText
  expiryDate: NullableText
  paymentMethod: NullableText
  paymentTerms: NullableText
}

export interface ContractFactsReplaceInput {
  rowVersion: string
  reason: string
  facts: ContractFactsInput
  fieldEvidence: Array<{ fieldCode: ContractFieldCode; evidence: ContractEvidence }>
}

export interface ContractMutationData {
  contract: ContractDetail
}

const decimalPattern = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/
const positiveIntegerPattern = /^[1-9]\d*$/
const datePattern = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/
const cursorPattern = /^[A-Za-z0-9_-]+$/
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actualKeys = Object.keys(value)
  return actualKeys.length === keys.length && keys.every((key) => key in value)
}

function isNullableText(value: unknown): value is NullableText {
  return value === null || typeof value === 'string'
}

function isNullableDecimal(value: unknown): value is NullableDecimal {
  return value === null || (typeof value === 'string' && decimalPattern.test(value))
}

function isNullableCurrency(value: unknown): value is NullableText {
  return value === null || (typeof value === 'string' && /^[A-Z]{3}$/.test(value))
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

function isNullableDate(value: unknown): value is NullableText {
  return value === null || (typeof value === 'string' && isCalendarDate(value))
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === 'string' && allowed.some((candidate) => candidate === value)
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

function isTimestamp(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value))
}

const listItemKeys = [
  'id',
  'contract_no',
  'name',
  'party_b_name',
  'amount',
  'currency',
  'effective_date',
  'expiry_date',
  'confirmation_status',
  'status',
] as const

export function decodeContractListItem(value: unknown): ContractListItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listItemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    !isNullableText(value.contract_no) ||
    typeof value.name !== 'string' ||
    !isNullableText(value.party_b_name) ||
    !isNullableDecimal(value.amount) ||
    !isNullableCurrency(value.currency) ||
    !isNullableDate(value.effective_date) ||
    !isNullableDate(value.expiry_date) ||
    !isOneOf(value.confirmation_status, contractConfirmationStatuses) ||
    !isOneOf(value.status, contractStatuses)
  ) {
    throw new TypeError('invalid contract list item')
  }

  return {
    id: value.id,
    contractNo: value.contract_no,
    name: value.name,
    partyBName: value.party_b_name,
    amount: value.amount,
    currency: value.currency,
    effectiveDate: value.effective_date,
    expiryDate: value.expiry_date,
    confirmationStatus: value.confirmation_status,
    status: value.status,
  }
}

const listKeys = ['items', 'page_size', 'next_cursor'] as const

export function decodeContractList(value: unknown): ContractListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null &&
      (typeof value.next_cursor !== 'string' ||
        value.next_cursor.length === 0 ||
        value.next_cursor.length > 256 ||
        !cursorPattern.test(value.next_cursor)))
  ) {
    throw new TypeError('invalid contract list')
  }

  const items = value.items.map(decodeContractListItem)
  const pageSize = Number(value.page_size)
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid contract list page size')
  }
  const ids = new Set<string>()
  for (const [index, item] of items.entries()) {
    if (ids.has(item.id)) throw new TypeError('duplicate contract list item')
    ids.add(item.id)
    if (index === 0) continue
    const previous = items[index - 1]!
    const datesOutOfOrder =
      (previous.effectiveDate === null && item.effectiveDate !== null) ||
      (previous.effectiveDate !== null &&
        item.effectiveDate !== null &&
        previous.effectiveDate < item.effectiveDate)
    if (datesOutOfOrder || (previous.effectiveDate === item.effectiveDate && previous.id <= item.id)) {
      throw new TypeError('invalid contract list order')
    }
  }

  return { items, pageSize, nextCursor: value.next_cursor }
}

const detailKeys = [
  'id',
  'contract_no',
  'name',
  'party_a_name',
  'party_a_tax_no',
  'party_b_name',
  'party_b_tax_no',
  'amount',
  'currency',
  'signed_date',
  'effective_date',
  'expiry_date',
  'payment_method',
  'payment_terms',
  'confirmation_status',
  'status',
  'row_version',
] as const

export function decodeContractDetail(value: unknown): ContractDetail {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, detailKeys) ||
    !isNullableText(value.party_a_name) ||
    !isNullableText(value.party_a_tax_no) ||
    !isNullableText(value.party_b_tax_no) ||
    !isNullableDate(value.signed_date) ||
    !isNullableText(value.payment_method) ||
    !isNullableText(value.payment_terms) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid contract detail')
  }

  const base = decodeContractListItem(
    Object.fromEntries(listItemKeys.map((key) => [key, value[key]])),
  )
  return {
    ...base,
    partyAName: value.party_a_name,
    partyATaxNo: value.party_a_tax_no,
    partyBTaxNo: value.party_b_tax_no,
    signedDate: value.signed_date,
    paymentMethod: value.payment_method,
    paymentTerms: value.payment_terms,
    rowVersion: value.row_version,
  }
}

const evidenceKeys = [
  'block_id',
  'parse_version_id',
  'page_no',
  'quote_text',
  'bbox',
  'confidence',
] as const

export function decodeContractEvidence(value: unknown): ContractEvidence {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, evidenceKeys) ||
    typeof value.block_id !== 'string' ||
    !UUID_PATTERN.test(value.block_id) ||
    typeof value.parse_version_id !== 'string' ||
    !UUID_PATTERN.test(value.parse_version_id) ||
    !Number.isInteger(value.page_no) ||
    Number(value.page_no) < 1 ||
    typeof value.quote_text !== 'string' ||
    value.quote_text.length < 1 ||
    value.quote_text.length > 4000 ||
    (value.bbox !== null && !isJsonObject(value.bbox)) ||
    !isNullableDecimal(value.confidence)
  ) {
    throw new TypeError('invalid contract evidence')
  }
  return {
    blockId: value.block_id,
    parseVersionId: value.parse_version_id,
    pageNo: Number(value.page_no),
    quoteText: value.quote_text,
    bbox: value.bbox,
    confidence: value.confidence,
  }
}

const fieldCandidateKeys = [
  'field_code',
  'value_type',
  'candidate_value',
  'confirmed_value',
  'confirmation_status',
  'evidence',
] as const

function decodeContractFieldCandidate(value: unknown): ContractFieldCandidate {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, fieldCandidateKeys) ||
    !isOneOf(value.field_code, contractFieldCodes) ||
    !isOneOf(value.value_type, ['string', 'number', 'date', 'json'] as const) ||
    !isJsonValue(value.candidate_value) ||
    !isJsonValue(value.confirmed_value) ||
    !isOneOf(value.confirmation_status, contractConfirmationStatuses)
  ) {
    throw new TypeError('invalid contract field candidate')
  }
  return {
    fieldCode: value.field_code,
    valueType: value.value_type,
    candidateValue: value.candidate_value,
    confirmedValue: value.confirmed_value,
    confirmationStatus: value.confirmation_status,
    evidence: value.evidence === null ? null : decodeContractEvidence(value.evidence),
  }
}

const evidenceResponseKeys = ['contract_id', 'file_id', 'row_version', 'fields'] as const

export function decodeContractEvidenceResponse(value: unknown): ContractEvidenceResponseData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, evidenceResponseKeys) ||
    typeof value.contract_id !== 'string' ||
    !UUID_PATTERN.test(value.contract_id) ||
    typeof value.file_id !== 'string' ||
    !UUID_PATTERN.test(value.file_id) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    !Array.isArray(value.fields)
  ) {
    throw new TypeError('invalid contract evidence response')
  }
  const fields = value.fields.map(decodeContractFieldCandidate)
  if (
    fields.length !== contractFieldCodes.length ||
    fields.some((item, index) => item.fieldCode !== contractFieldCodes[index])
  ) {
    throw new TypeError('invalid contract field order')
  }
  return {
    contractId: value.contract_id,
    fileId: value.file_id,
    rowVersion: value.row_version,
    fields,
  }
}

const correctionHistoryItemKeys = [
  'id',
  'field_path',
  'before_value',
  'after_value',
  'reason',
  'actor_id',
  'actor_role_code',
  'created_at',
  'trace_id',
] as const

function decodeContractCorrectionHistoryItem(value: unknown): ContractCorrectionHistoryItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, correctionHistoryItemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.field_path !== 'string' ||
    value.field_path.length < 1 ||
    (value.before_value !== null && !isJsonObject(value.before_value)) ||
    (value.after_value !== null && !isJsonObject(value.after_value)) ||
    typeof value.reason !== 'string' ||
    value.reason.length < 1 ||
    typeof value.actor_id !== 'string' ||
    !UUID_PATTERN.test(value.actor_id) ||
    typeof value.actor_role_code !== 'string' ||
    value.actor_role_code.length < 1 ||
    !isTimestamp(value.created_at) ||
    typeof value.trace_id !== 'string' ||
    !UUID_PATTERN.test(value.trace_id)
  ) {
    throw new TypeError('invalid contract correction history item')
  }
  return {
    id: value.id,
    fieldPath: value.field_path,
    beforeValue: value.before_value,
    afterValue: value.after_value,
    reason: value.reason,
    actorId: value.actor_id,
    actorRoleCode: value.actor_role_code,
    createdAt: value.created_at,
    traceId: value.trace_id,
  }
}

export function decodeContractCorrectionHistory(value: unknown): ContractCorrectionHistoryData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['contract_id', 'items']) ||
    typeof value.contract_id !== 'string' ||
    !UUID_PATTERN.test(value.contract_id) ||
    !Array.isArray(value.items)
  ) {
    throw new TypeError('invalid contract correction history')
  }
  const items = value.items.map(decodeContractCorrectionHistoryItem)
  if (new Set(items.map((item) => item.id)).size !== items.length) {
    throw new TypeError('duplicate contract correction history item')
  }
  return { contractId: value.contract_id, items }
}

export function decodeContractMutation(value: unknown): ContractMutationData {
  if (!isRecord(value) || !hasExactKeys(value, ['contract'])) {
    throw new TypeError('invalid contract mutation')
  }
  return { contract: decodeContractDetail(value.contract) }
}

function requireContractId(value: string): void {
  if (!UUID_PATTERN.test(value)) {
    throw new TypeError('contract id must be a canonical lowercase UUID')
  }
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

function encodeContractEvidence(value: ContractEvidence): Record<string, unknown> {
  return {
    block_id: value.blockId,
    parse_version_id: value.parseVersionId,
    page_no: value.pageNo,
    quote_text: value.quoteText,
    bbox: value.bbox,
    confidence: value.confidence,
  }
}

function validateNullableFact(value: NullableText, maxLength: number): void {
  if (value !== null && (value.length < 1 || value.length > maxLength || value !== value.trim())) {
    throw new TypeError('contract text fact is invalid')
  }
}

function validateFactsInput(input: ContractFactsReplaceInput): void {
  requireVersion(input.rowVersion)
  requireReason(input.reason)
  validateNullableFact(input.facts.contractNo, 100)
  validateNullableFact(input.facts.name, 300)
  validateNullableFact(input.facts.partyAName, 300)
  validateNullableFact(input.facts.partyATaxNo, 32)
  validateNullableFact(input.facts.partyBName, 300)
  validateNullableFact(input.facts.partyBTaxNo, 32)
  validateNullableFact(input.facts.paymentMethod, 100)
  validateNullableFact(input.facts.paymentTerms, 4000)
  if (!isNullableDecimal(input.facts.amount)) throw new TypeError('contract amount is invalid')
  if (!isNullableCurrency(input.facts.currency)) throw new TypeError('contract currency is invalid')
  for (const value of [input.facts.signedDate, input.facts.effectiveDate, input.facts.expiryDate]) {
    if (!isNullableDate(value)) throw new TypeError('contract date is invalid')
  }
  if (
    input.facts.effectiveDate !== null &&
    input.facts.expiryDate !== null &&
    input.facts.expiryDate < input.facts.effectiveDate
  ) {
    throw new TypeError('contract expiry date precedes effective date')
  }
  if (
    input.fieldEvidence.length > contractFieldCodes.length ||
    new Set(input.fieldEvidence.map((item) => item.fieldCode)).size !== input.fieldEvidence.length
  ) {
    throw new TypeError('contract field evidence is invalid')
  }
}

export class ContractApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<ContractListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }
    if (
      cursor !== undefined &&
      (cursor.length === 0 || cursor.length > 256 || !cursorPattern.test(cursor))
    ) {
      throw new TypeError('cursor must be a canonical base64url string')
    }
    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(
      `/contracts?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeContractList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('contract list page size does not match request')
    }
    return response.data
  }

  async getDetail(contractId: string, signal?: AbortSignal): Promise<ContractDetail> {
    requireContractId(contractId)
    const response = await this.client.request(`/contracts/${contractId}`, {
      signal,
      decode: decodeContractDetail,
    })
    return response.data
  }

  async getEvidence(
    contractId: string,
    signal?: AbortSignal,
  ): Promise<ContractEvidenceResponseData> {
    requireContractId(contractId)
    const response = await this.client.request(`/contracts/${contractId}/evidence`, {
      signal,
      decode: decodeContractEvidenceResponse,
    })
    if (response.data.contractId !== contractId) throw new TypeError('contract evidence id mismatch')
    return response.data
  }

  async getHistory(
    contractId: string,
    signal?: AbortSignal,
  ): Promise<ContractCorrectionHistoryData> {
    requireContractId(contractId)
    const response = await this.client.request(`/contracts/${contractId}/history`, {
      signal,
      decode: decodeContractCorrectionHistory,
    })
    if (response.data.contractId !== contractId) throw new TypeError('contract history id mismatch')
    return response.data
  }

  async replaceFacts(
    contractId: string,
    input: ContractFactsReplaceInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ContractMutationData> {
    requireContractId(contractId)
    validateFactsInput(input)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/contracts/${contractId}/facts`, {
      method: 'PUT',
      body: {
        row_version: input.rowVersion,
        reason: input.reason,
        facts: {
          contract_no: input.facts.contractNo,
          name: input.facts.name,
          party_a_name: input.facts.partyAName,
          party_a_tax_no: input.facts.partyATaxNo,
          party_b_name: input.facts.partyBName,
          party_b_tax_no: input.facts.partyBTaxNo,
          amount: input.facts.amount,
          currency: input.facts.currency,
          signed_date: input.facts.signedDate,
          effective_date: input.facts.effectiveDate,
          expiry_date: input.facts.expiryDate,
          payment_method: input.facts.paymentMethod,
          payment_terms: input.facts.paymentTerms,
        },
        field_evidence: input.fieldEvidence.map((item) => ({
          field_code: item.fieldCode,
          evidence: encodeContractEvidence(item.evidence),
        })),
      },
      idempotencyKey,
      signal,
      decode: decodeContractMutation,
    })
    if (response.data.contract.id !== contractId) throw new TypeError('contract mutation id mismatch')
    return response.data
  }

  async decide(
    contractId: string,
    input: { rowVersion: string; decision: 'confirmed' | 'rejected'; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ContractMutationData> {
    requireContractId(contractId)
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/contracts/${contractId}/decision`, {
      method: 'POST',
      body: {
        row_version: input.rowVersion,
        decision: input.decision,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeContractMutation,
    })
    if (response.data.contract.id !== contractId) throw new TypeError('contract mutation id mismatch')
    return response.data
  }
}

export const contractApi = new ContractApi()
