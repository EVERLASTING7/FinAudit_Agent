import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const invoiceConfirmationStatuses = [
  'unconfirmed',
  'confirmed',
  'rejected',
] as const
export const invoiceDuplicateStatuses = [
  'not_checked',
  'unique',
  'suspected',
  'confirmed_duplicate',
  'exception_approved',
] as const
export const invoiceStatuses = ['draft', 'confirmed', 'voided', 'archived'] as const
export const invoiceDuplicateCandidateBasisStatuses = [
  'ready',
  'incomplete_identity',
  'source_voided',
] as const

export type InvoiceConfirmationStatus = (typeof invoiceConfirmationStatuses)[number]
export type InvoiceDuplicateStatus = (typeof invoiceDuplicateStatuses)[number]
export type InvoiceStatus = (typeof invoiceStatuses)[number]
export type InvoiceDuplicateCandidateBasisStatus =
  (typeof invoiceDuplicateCandidateBasisStatuses)[number]

type NullableDecimal = string | null
type NullableText = string | null

export interface InvoiceItem {
  id: string
  lineNo: number
  itemName: NullableText
  specification: NullableText
  unit: NullableText
  quantity: NullableDecimal
  unitPrice: NullableDecimal
  amountExcludingTax: NullableDecimal
  taxRate: NullableDecimal
  taxAmount: NullableDecimal
  totalAmount: NullableDecimal
  rowVersion: string
}

export interface InvoiceDetail {
  id: string
  invoiceCode: NullableText
  invoiceNumber: NullableText
  invoiceType: NullableText
  isRedInvoice: boolean | null
  invoiceDate: NullableText
  buyerName: NullableText
  buyerTaxNo: NullableText
  sellerName: NullableText
  sellerTaxNo: NullableText
  amountExcludingTax: NullableDecimal
  taxAmount: NullableDecimal
  totalAmount: NullableDecimal
  currency: string
  confirmationStatus: InvoiceConfirmationStatus
  duplicateStatus: InvoiceDuplicateStatus
  status: InvoiceStatus
  rowVersion: string
  items: InvoiceItem[]
}

export interface InvoiceListItem {
  id: string
  invoiceCode: NullableText
  invoiceNumber: NullableText
  invoiceDate: NullableText
  sellerName: NullableText
  totalAmount: NullableDecimal
  currency: string
  confirmationStatus: InvoiceConfirmationStatus
  duplicateStatus: InvoiceDuplicateStatus
  status: InvoiceStatus
}

export interface InvoiceListData {
  items: InvoiceListItem[]
  pageSize: number
  nextCursor: string | null
}

export interface InvoiceDuplicateCandidateListData {
  basisStatus: InvoiceDuplicateCandidateBasisStatus
  items: InvoiceListItem[]
  pageSize: number
  nextCursor: string | null
}

export interface InvoiceExactDuplicateIdentity {
  invoiceCode: string
  invoiceNumber: string
  sellerTaxNo: string
}

export interface InvoiceExactDuplicatePairData {
  source: InvoiceListItem
  candidate: InvoiceListItem
  exactIdentity: InvoiceExactDuplicateIdentity
}

export const invoiceFieldCodes = [
  'invoice_code',
  'invoice_number',
  'invoice_type',
  'is_red_invoice',
  'invoice_date',
  'buyer_name',
  'buyer_tax_no',
  'seller_name',
  'seller_tax_no',
  'amount_excluding_tax',
  'tax_amount',
  'total_amount',
  'currency',
] as const

export type InvoiceFieldCode = (typeof invoiceFieldCodes)[number]
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue }

export interface InvoiceEvidence {
  blockId: string
  parseVersionId: string
  pageNo: number
  quoteText: string
  bbox: Record<string, JsonValue> | null
  confidence: NullableDecimal
}

export interface InvoiceFieldEvidence {
  fieldCode: InvoiceFieldCode
  evidence: InvoiceEvidence
}

export interface InvoiceEvidenceResponseData {
  invoiceId: string
  rowVersion: string
  fieldEvidence: InvoiceFieldEvidence[]
  itemEvidence: Record<string, InvoiceEvidence[]>
}

export interface InvoiceCorrectionHistoryItem {
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

export interface InvoiceCorrectionHistoryData {
  invoiceId: string
  items: InvoiceCorrectionHistoryItem[]
}

export interface InvoiceFactsInput {
  invoiceCode: NullableText
  invoiceNumber: NullableText
  invoiceType: NullableText
  isRedInvoice: boolean | null
  invoiceDate: NullableText
  buyerName: NullableText
  buyerTaxNo: NullableText
  sellerName: NullableText
  sellerTaxNo: NullableText
  amountExcludingTax: NullableDecimal
  taxAmount: NullableDecimal
  totalAmount: NullableDecimal
  currency: string
}

export interface InvoiceItemFactsInput {
  lineNo: number
  itemName: NullableText
  specification: NullableText
  unit: NullableText
  quantity: NullableDecimal
  unitPrice: NullableDecimal
  amountExcludingTax: NullableDecimal
  taxRate: NullableDecimal
  taxAmount: NullableDecimal
  totalAmount: NullableDecimal
  evidence: InvoiceEvidence[]
}

export interface InvoiceFactsReplaceInput {
  rowVersion: string
  reason: string
  facts: InvoiceFactsInput
  fieldEvidence: InvoiceFieldEvidence[]
  items: InvoiceItemFactsInput[]
}

export interface InvoiceMutationData {
  invoice: InvoiceDetail
  duplicateCandidateId: string | null
}

const decimalPattern = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/
const positiveIntegerPattern = /^[1-9]\d*$/
const datePattern = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/
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

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === 'string' && allowed.some((candidate) => candidate === value)
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  )
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean'
  ) {
    return true
  }
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isJsonValue)
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

function isJsonObject(value: unknown): value is Record<string, JsonValue> {
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

const evidenceKeys = [
  'block_id',
  'parse_version_id',
  'page_no',
  'quote_text',
  'bbox',
  'confidence',
] as const

export function decodeInvoiceEvidence(value: unknown): InvoiceEvidence {
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
    throw new TypeError('invalid invoice evidence')
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

const fieldEvidenceKeys = ['field_code', 'evidence'] as const

function decodeInvoiceFieldEvidence(value: unknown): InvoiceFieldEvidence {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, fieldEvidenceKeys) ||
    !isOneOf(value.field_code, invoiceFieldCodes)
  ) {
    throw new TypeError('invalid invoice field evidence')
  }
  return { fieldCode: value.field_code, evidence: decodeInvoiceEvidence(value.evidence) }
}

const evidenceResponseKeys = [
  'invoice_id',
  'row_version',
  'field_evidence',
  'item_evidence',
] as const

export function decodeInvoiceEvidenceResponse(value: unknown): InvoiceEvidenceResponseData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, evidenceResponseKeys) ||
    typeof value.invoice_id !== 'string' ||
    !UUID_PATTERN.test(value.invoice_id) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    !Array.isArray(value.field_evidence) ||
    !isRecord(value.item_evidence)
  ) {
    throw new TypeError('invalid invoice evidence response')
  }
  const fieldEvidence = value.field_evidence.map(decodeInvoiceFieldEvidence)
  if (
    fieldEvidence.length > invoiceFieldCodes.length ||
    new Set(fieldEvidence.map((item) => item.fieldCode)).size !== fieldEvidence.length
  ) {
    throw new TypeError('duplicate invoice field evidence')
  }
  const itemEvidence: Record<string, InvoiceEvidence[]> = {}
  for (const [lineNo, evidence] of Object.entries(value.item_evidence)) {
    if (
      !positiveIntegerPattern.test(lineNo) ||
      Number(lineNo) > 1000 ||
      !Array.isArray(evidence) ||
      evidence.length > 20
    ) {
      throw new TypeError('invalid invoice item evidence')
    }
    itemEvidence[lineNo] = evidence.map(decodeInvoiceEvidence)
  }
  return {
    invoiceId: value.invoice_id,
    rowVersion: value.row_version,
    fieldEvidence,
    itemEvidence,
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

function decodeCorrectionHistoryItem(value: unknown): InvoiceCorrectionHistoryItem {
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
    throw new TypeError('invalid invoice correction history item')
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

const correctionHistoryKeys = ['invoice_id', 'items'] as const

export function decodeInvoiceCorrectionHistory(value: unknown): InvoiceCorrectionHistoryData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, correctionHistoryKeys) ||
    typeof value.invoice_id !== 'string' ||
    !UUID_PATTERN.test(value.invoice_id) ||
    !Array.isArray(value.items)
  ) {
    throw new TypeError('invalid invoice correction history')
  }
  const items = value.items.map(decodeCorrectionHistoryItem)
  if (new Set(items.map((item) => item.id)).size !== items.length) {
    throw new TypeError('duplicate invoice correction history item')
  }
  return { invoiceId: value.invoice_id, items }
}

const mutationKeys = ['invoice', 'duplicate_candidate_id'] as const

export function decodeInvoiceMutation(value: unknown): InvoiceMutationData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, mutationKeys) ||
    (value.duplicate_candidate_id !== null &&
      (typeof value.duplicate_candidate_id !== 'string' ||
        !UUID_PATTERN.test(value.duplicate_candidate_id)))
  ) {
    throw new TypeError('invalid invoice mutation')
  }
  const invoice = decodeInvoiceDetail(value.invoice)
  if (value.duplicate_candidate_id === invoice.id) {
    throw new TypeError('invoice cannot duplicate itself')
  }
  return { invoice, duplicateCandidateId: value.duplicate_candidate_id }
}

function requireInvoiceId(value: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError('invoice id must be a canonical lowercase UUID')
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

function encodeInvoiceEvidence(value: InvoiceEvidence): Record<string, unknown> {
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
  if (
    value !== null &&
    (value.length < 1 || value.length > maxLength || value !== value.trim())
  ) {
    throw new TypeError('invoice text fact is invalid')
  }
}

function validateFactsInput(input: InvoiceFactsReplaceInput): void {
  requireVersion(input.rowVersion)
  requireReason(input.reason)
  validateNullableFact(input.facts.invoiceCode, 50)
  validateNullableFact(input.facts.invoiceNumber, 50)
  validateNullableFact(input.facts.invoiceType, 40)
  if (input.facts.isRedInvoice !== null && typeof input.facts.isRedInvoice !== 'boolean') {
    throw new TypeError('red invoice flag is invalid')
  }
  validateNullableFact(input.facts.buyerName, 300)
  validateNullableFact(input.facts.buyerTaxNo, 32)
  validateNullableFact(input.facts.sellerName, 300)
  validateNullableFact(input.facts.sellerTaxNo, 32)
  if (input.facts.invoiceDate !== null && !isCalendarDate(input.facts.invoiceDate)) {
    throw new TypeError('invoice date is invalid')
  }
  if (!/^[A-Z]{3}$/.test(input.facts.currency)) throw new TypeError('currency is invalid')
  for (const value of [
    input.facts.amountExcludingTax,
    input.facts.taxAmount,
    input.facts.totalAmount,
  ]) {
    if (!isNullableDecimal(value)) throw new TypeError('invoice decimal fact is invalid')
  }
  if (
    input.fieldEvidence.length > invoiceFieldCodes.length ||
    new Set(input.fieldEvidence.map((item) => item.fieldCode)).size !== input.fieldEvidence.length
  ) {
    throw new TypeError('invoice field evidence is invalid')
  }
  if (input.items.length > 1000) throw new TypeError('invoice items exceed limit')
  for (const [index, item] of input.items.entries()) {
    if (
      !Number.isInteger(item.lineNo) ||
      item.lineNo < 1 ||
      item.lineNo > 1000 ||
      (index > 0 && input.items[index - 1]!.lineNo >= item.lineNo) ||
      (item.itemName !== null && item.itemName.length > 500) ||
      (item.specification !== null && item.specification.length > 300) ||
      (item.unit !== null && item.unit.length > 50) ||
      item.evidence.length > 20
    ) {
      throw new TypeError('invoice item is invalid')
    }
    for (const decimal of [
      item.quantity,
      item.unitPrice,
      item.amountExcludingTax,
      item.taxRate,
      item.taxAmount,
      item.totalAmount,
    ]) {
      if (!isNullableDecimal(decimal)) throw new TypeError('invoice item decimal is invalid')
    }
  }
}

function decodeCanonicalIdCursor(value: unknown): string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 256 ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) {
    throw new TypeError('invalid canonical id cursor')
  }

  try {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat(-value.length & 3)
    const binary = atob(padded)
    const reencoded = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    if (reencoded !== value) throw new TypeError('non-canonical base64url')

    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    const payload: unknown = JSON.parse(text)
    if (
      !isRecord(payload) ||
      !hasExactKeys(payload, ['id', 'v']) ||
      payload.v !== 1 ||
      typeof payload.id !== 'string' ||
      !UUID_PATTERN.test(payload.id) ||
      text !== JSON.stringify({ id: payload.id, v: 1 })
    ) {
      throw new TypeError('invalid canonical cursor payload')
    }
    return payload.id
  } catch {
    throw new TypeError('invalid canonical id cursor')
  }
}

const itemKeys = [
  'id',
  'line_no',
  'item_name',
  'specification',
  'unit',
  'quantity',
  'unit_price',
  'amount_excluding_tax',
  'tax_rate',
  'tax_amount',
  'total_amount',
  'row_version',
] as const

function decodeInvoiceItem(value: unknown): InvoiceItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, itemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    !Number.isInteger(value.line_no) ||
    Number(value.line_no) <= 0 ||
    !isNullableText(value.item_name) ||
    !isNullableText(value.specification) ||
    !isNullableText(value.unit) ||
    !isNullableDecimal(value.quantity) ||
    !isNullableDecimal(value.unit_price) ||
    !isNullableDecimal(value.amount_excluding_tax) ||
    !isNullableDecimal(value.tax_rate) ||
    !isNullableDecimal(value.tax_amount) ||
    !isNullableDecimal(value.total_amount) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid invoice item')
  }

  return {
    id: value.id,
    lineNo: Number(value.line_no),
    itemName: value.item_name,
    specification: value.specification,
    unit: value.unit,
    quantity: value.quantity,
    unitPrice: value.unit_price,
    amountExcludingTax: value.amount_excluding_tax,
    taxRate: value.tax_rate,
    taxAmount: value.tax_amount,
    totalAmount: value.total_amount,
    rowVersion: value.row_version,
  }
}

const invoiceKeys = [
  'id',
  'invoice_code',
  'invoice_number',
  'invoice_type',
  'is_red_invoice',
  'invoice_date',
  'buyer_name',
  'buyer_tax_no',
  'seller_name',
  'seller_tax_no',
  'amount_excluding_tax',
  'tax_amount',
  'total_amount',
  'currency',
  'confirmation_status',
  'duplicate_status',
  'status',
  'row_version',
  'items',
] as const

export function decodeInvoiceDetail(value: unknown): InvoiceDetail {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, invoiceKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    !isNullableText(value.invoice_code) ||
    !isNullableText(value.invoice_number) ||
    !isNullableText(value.invoice_type) ||
    (value.is_red_invoice !== null && typeof value.is_red_invoice !== 'boolean') ||
    !isNullableText(value.invoice_date) ||
    (value.invoice_date !== null && !isCalendarDate(value.invoice_date)) ||
    !isNullableText(value.buyer_name) ||
    !isNullableText(value.buyer_tax_no) ||
    !isNullableText(value.seller_name) ||
    !isNullableText(value.seller_tax_no) ||
    !isNullableDecimal(value.amount_excluding_tax) ||
    !isNullableDecimal(value.tax_amount) ||
    !isNullableDecimal(value.total_amount) ||
    typeof value.currency !== 'string' ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    !isOneOf(value.confirmation_status, invoiceConfirmationStatuses) ||
    !isOneOf(value.duplicate_status, invoiceDuplicateStatuses) ||
    !isOneOf(value.status, invoiceStatuses) ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version) ||
    !Array.isArray(value.items)
  ) {
    throw new TypeError('invalid invoice detail')
  }

  const items = value.items.map(decodeInvoiceItem)
  const itemIds = new Set<string>()
  const lineNumbers = new Set<number>()
  for (const [index, item] of items.entries()) {
    if (
      itemIds.has(item.id) ||
      lineNumbers.has(item.lineNo) ||
      (index > 0 && items[index - 1]!.lineNo >= item.lineNo)
    ) {
      throw new TypeError('invalid invoice item order')
    }
    itemIds.add(item.id)
    lineNumbers.add(item.lineNo)
  }

  return {
    id: value.id,
    invoiceCode: value.invoice_code,
    invoiceNumber: value.invoice_number,
    invoiceType: value.invoice_type,
    isRedInvoice: value.is_red_invoice,
    invoiceDate: value.invoice_date,
    buyerName: value.buyer_name,
    buyerTaxNo: value.buyer_tax_no,
    sellerName: value.seller_name,
    sellerTaxNo: value.seller_tax_no,
    amountExcludingTax: value.amount_excluding_tax,
    taxAmount: value.tax_amount,
    totalAmount: value.total_amount,
    currency: value.currency,
    confirmationStatus: value.confirmation_status,
    duplicateStatus: value.duplicate_status,
    status: value.status,
    rowVersion: value.row_version,
    items,
  }
}

const invoiceListItemKeys = [
  'id',
  'invoice_code',
  'invoice_number',
  'invoice_date',
  'seller_name',
  'total_amount',
  'currency',
  'confirmation_status',
  'duplicate_status',
  'status',
] as const

export function decodeInvoiceListItem(value: unknown): InvoiceListItem {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, invoiceListItemKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    !isNullableText(value.invoice_code) ||
    !isNullableText(value.invoice_number) ||
    !isNullableText(value.invoice_date) ||
    (value.invoice_date !== null && !isCalendarDate(value.invoice_date)) ||
    !isNullableText(value.seller_name) ||
    !isNullableDecimal(value.total_amount) ||
    typeof value.currency !== 'string' ||
    !/^[A-Z]{3}$/.test(value.currency) ||
    !isOneOf(value.confirmation_status, invoiceConfirmationStatuses) ||
    !isOneOf(value.duplicate_status, invoiceDuplicateStatuses) ||
    !isOneOf(value.status, invoiceStatuses)
  ) {
    throw new TypeError('invalid invoice list item')
  }

  return {
    id: value.id,
    invoiceCode: value.invoice_code,
    invoiceNumber: value.invoice_number,
    invoiceDate: value.invoice_date,
    sellerName: value.seller_name,
    totalAmount: value.total_amount,
    currency: value.currency,
    confirmationStatus: value.confirmation_status,
    duplicateStatus: value.duplicate_status,
    status: value.status,
  }
}

const invoiceExactDuplicatePairKeys = ['source', 'candidate', 'exact_identity'] as const
const invoiceExactDuplicateIdentityKeys = [
  'invoice_code',
  'invoice_number',
  'seller_tax_no',
] as const

export function decodeInvoiceExactDuplicatePair(
  value: unknown,
): InvoiceExactDuplicatePairData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, invoiceExactDuplicatePairKeys) ||
    !isRecord(value.exact_identity) ||
    !hasExactKeys(value.exact_identity, invoiceExactDuplicateIdentityKeys) ||
    typeof value.exact_identity.invoice_code !== 'string' ||
    typeof value.exact_identity.invoice_number !== 'string' ||
    typeof value.exact_identity.seller_tax_no !== 'string'
  ) {
    throw new TypeError('invalid invoice exact duplicate pair')
  }

  const source = decodeInvoiceListItem(value.source)
  const candidate = decodeInvoiceListItem(value.candidate)
  if (
    source.id === candidate.id ||
    source.status === 'voided' ||
    candidate.status === 'voided' ||
    source.invoiceCode !== value.exact_identity.invoice_code ||
    candidate.invoiceCode !== value.exact_identity.invoice_code ||
    source.invoiceNumber !== value.exact_identity.invoice_number ||
    candidate.invoiceNumber !== value.exact_identity.invoice_number
  ) {
    throw new TypeError('inconsistent invoice exact duplicate pair')
  }

  return {
    source,
    candidate,
    exactIdentity: {
      invoiceCode: value.exact_identity.invoice_code,
      invoiceNumber: value.exact_identity.invoice_number,
      sellerTaxNo: value.exact_identity.seller_tax_no,
    },
  }
}

const invoiceListKeys = ['items', 'page_size', 'next_cursor'] as const

export function decodeInvoiceList(value: unknown): InvoiceListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, invoiceListKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null &&
      (typeof value.next_cursor !== 'string' ||
        value.next_cursor.length === 0 ||
        value.next_cursor.length > 256 ||
        !/^[A-Za-z0-9_-]+$/.test(value.next_cursor)))
  ) {
    throw new TypeError('invalid invoice list')
  }

  const items = value.items.map(decodeInvoiceListItem)
  if (items.length > Number(value.page_size)) {
    throw new TypeError('invalid invoice list page size')
  }
  if (value.next_cursor !== null && items.length !== Number(value.page_size)) {
    throw new TypeError('invoice list cursor requires a full page')
  }
  const itemIds = new Set<string>()
  for (const [index, item] of items.entries()) {
    if (itemIds.has(item.id)) {
      throw new TypeError('duplicate invoice list item')
    }
    itemIds.add(item.id)
    if (index === 0) continue
    const previous = items[index - 1]!
    const datesOutOfOrder =
      (previous.invoiceDate === null && item.invoiceDate !== null) ||
      (previous.invoiceDate !== null &&
        item.invoiceDate !== null &&
        previous.invoiceDate < item.invoiceDate)
    const sameDate = previous.invoiceDate === item.invoiceDate
    if (datesOutOfOrder || (sameDate && previous.id <= item.id)) {
      throw new TypeError('invalid invoice list order')
    }
  }

  return {
    items,
    pageSize: Number(value.page_size),
    nextCursor: value.next_cursor,
  }
}

const duplicateCandidateListKeys = [
  'basis_status',
  'items',
  'page_size',
  'next_cursor',
] as const

export function decodeInvoiceDuplicateCandidateList(
  value: unknown,
): InvoiceDuplicateCandidateListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, duplicateCandidateListKeys) ||
    !isOneOf(value.basis_status, invoiceDuplicateCandidateBasisStatuses) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null && typeof value.next_cursor !== 'string')
  ) {
    throw new TypeError('invalid invoice duplicate candidate list')
  }

  const items = value.items.map(decodeInvoiceListItem)
  const pageSize = Number(value.page_size)
  const nextCursorId =
    value.next_cursor === null ? null : decodeCanonicalIdCursor(value.next_cursor)

  if (items.some((item) => item.status === 'voided')) {
    throw new TypeError('voided invoice cannot be a duplicate candidate')
  }
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid invoice duplicate candidate page size')
  }
  if (value.basis_status !== 'ready' && (items.length !== 0 || value.next_cursor !== null)) {
    throw new TypeError('inactive duplicate candidate basis must return an empty page')
  }
  for (let index = 1; index < items.length; index += 1) {
    if (items[index - 1]!.id >= items[index]!.id) {
      throw new TypeError('invalid invoice duplicate candidate order')
    }
  }
  if (nextCursorId !== null && items.at(-1)?.id !== nextCursorId) {
    throw new TypeError('duplicate candidate cursor must match the last item')
  }

  return {
    basisStatus: value.basis_status,
    items,
    pageSize,
    nextCursor: value.next_cursor,
  }
}

export class InvoiceApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async getDetail(invoiceId: string, signal?: AbortSignal): Promise<InvoiceDetail> {
    if (!UUID_PATTERN.test(invoiceId)) {
      throw new TypeError('invoice id must be a canonical lowercase UUID')
    }
    const response = await this.client.request(`/invoices/${invoiceId}`, {
      signal,
      decode: decodeInvoiceDetail,
    })
    return response.data
  }

  async list(
    pageSize = 20,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<InvoiceListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }
    if (
      cursor !== undefined &&
      (cursor.length === 0 || cursor.length > 256 || !/^[A-Za-z0-9_-]+$/.test(cursor))
    ) {
      throw new TypeError('cursor must be a canonical base64url string')
    }
    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(
      `/invoices?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeInvoiceList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('invoice list page size does not match request')
    }
    return response.data
  }

  async listDuplicateCandidates(
    invoiceId: string,
    pageSize = 20,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<InvoiceDuplicateCandidateListData> {
    if (!UUID_PATTERN.test(invoiceId)) {
      throw new TypeError('invoice id must be a canonical lowercase UUID')
    }
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
      throw new TypeError('page size must be an integer between 1 and 100')
    }

    let cursorId: string | undefined
    if (cursor !== undefined) {
      try {
        cursorId = decodeCanonicalIdCursor(cursor)
      } catch {
        throw new TypeError('cursor must be a canonical base64url JSON object')
      }
    }

    const cursorQuery = cursor === undefined ? '' : `&cursor=${encodeURIComponent(cursor)}`
    const response = await this.client.request(
      `/invoices/${invoiceId}/duplicate-candidates?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeInvoiceDuplicateCandidateList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('invoice duplicate candidate page size does not match request')
    }
    if (
      response.data.items.some(
        (item) => item.id === invoiceId || (cursorId !== undefined && item.id <= cursorId),
      )
    ) {
      throw new TypeError('invoice duplicate candidate page violates its cursor boundary')
    }
    return response.data
  }

  async getExactDuplicatePair(
    invoiceId: string,
    candidateId: string,
    signal?: AbortSignal,
  ): Promise<InvoiceExactDuplicatePairData> {
    if (!UUID_PATTERN.test(invoiceId) || !UUID_PATTERN.test(candidateId)) {
      throw new TypeError('invoice ids must be canonical lowercase UUIDs')
    }
    const response = await this.client.request(
      `/invoices/${invoiceId}/duplicate-candidates/${candidateId}`,
      { signal, decode: decodeInvoiceExactDuplicatePair },
    )
    if (response.data.source.id !== invoiceId || response.data.candidate.id !== candidateId) {
      throw new TypeError('invoice exact duplicate pair does not match request')
    }
    return response.data
  }

  async getEvidence(
    invoiceId: string,
    signal?: AbortSignal,
  ): Promise<InvoiceEvidenceResponseData> {
    requireInvoiceId(invoiceId)
    const response = await this.client.request(`/invoices/${invoiceId}/evidence`, {
      signal,
      decode: decodeInvoiceEvidenceResponse,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice evidence id mismatch')
    return response.data
  }

  async getHistory(
    invoiceId: string,
    signal?: AbortSignal,
  ): Promise<InvoiceCorrectionHistoryData> {
    requireInvoiceId(invoiceId)
    const response = await this.client.request(`/invoices/${invoiceId}/history`, {
      signal,
      decode: decodeInvoiceCorrectionHistory,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice history id mismatch')
    return response.data
  }

  async replaceFacts(
    invoiceId: string,
    input: InvoiceFactsReplaceInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<InvoiceMutationData> {
    requireInvoiceId(invoiceId)
    validateFactsInput(input)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/facts`, {
      method: 'PUT',
      body: {
        row_version: input.rowVersion,
        reason: input.reason,
        facts: {
          invoice_code: input.facts.invoiceCode,
          invoice_number: input.facts.invoiceNumber,
          invoice_type: input.facts.invoiceType,
          is_red_invoice: input.facts.isRedInvoice,
          invoice_date: input.facts.invoiceDate,
          buyer_name: input.facts.buyerName,
          buyer_tax_no: input.facts.buyerTaxNo,
          seller_name: input.facts.sellerName,
          seller_tax_no: input.facts.sellerTaxNo,
          amount_excluding_tax: input.facts.amountExcludingTax,
          tax_amount: input.facts.taxAmount,
          total_amount: input.facts.totalAmount,
          currency: input.facts.currency,
        },
        field_evidence: input.fieldEvidence.map((item) => ({
          field_code: item.fieldCode,
          evidence: encodeInvoiceEvidence(item.evidence),
        })),
        items: input.items.map((item) => ({
          line_no: item.lineNo,
          item_name: item.itemName,
          specification: item.specification,
          unit: item.unit,
          quantity: item.quantity,
          unit_price: item.unitPrice,
          amount_excluding_tax: item.amountExcludingTax,
          tax_rate: item.taxRate,
          tax_amount: item.taxAmount,
          total_amount: item.totalAmount,
          evidence: item.evidence.map(encodeInvoiceEvidence),
        })),
      },
      idempotencyKey,
      signal,
      decode: decodeInvoiceMutation,
    })
    if (response.data.invoice.id !== invoiceId) throw new TypeError('invoice mutation id mismatch')
    return response.data
  }

  async decide(
    invoiceId: string,
    input: { rowVersion: string; decision: 'confirmed' | 'rejected'; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<InvoiceMutationData> {
    requireInvoiceId(invoiceId)
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/decision`, {
      method: 'POST',
      body: {
        row_version: input.rowVersion,
        decision: input.decision,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeInvoiceMutation,
    })
    if (response.data.invoice.id !== invoiceId) throw new TypeError('invoice mutation id mismatch')
    return response.data
  }

  async checkDuplicate(
    invoiceId: string,
    input: { rowVersion: string; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<InvoiceMutationData> {
    requireInvoiceId(invoiceId)
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/duplicate-check`, {
      method: 'POST',
      body: { row_version: input.rowVersion, reason: input.reason },
      idempotencyKey,
      signal,
      decode: decodeInvoiceMutation,
    })
    if (response.data.invoice.id !== invoiceId) throw new TypeError('invoice mutation id mismatch')
    return response.data
  }

  async decideDuplicate(
    invoiceId: string,
    input: {
      rowVersion: string
      candidateId: string
      decision: 'confirmed_duplicate' | 'exception_approved'
      reason: string
    },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<InvoiceMutationData> {
    requireInvoiceId(invoiceId)
    requireInvoiceId(input.candidateId)
    if (invoiceId === input.candidateId) throw new TypeError('invoice cannot duplicate itself')
    requireVersion(input.rowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/duplicate-decision`, {
      method: 'POST',
      body: {
        row_version: input.rowVersion,
        candidate_id: input.candidateId,
        decision: input.decision,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeInvoiceMutation,
    })
    if (
      response.data.invoice.id !== invoiceId ||
      response.data.duplicateCandidateId !== input.candidateId
    ) {
      throw new TypeError('invoice duplicate mutation mismatch')
    }
    return response.data
  }
}

export const invoiceApi = new InvoiceApi()
