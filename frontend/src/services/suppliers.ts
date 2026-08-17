import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const supplierSourceTypes = ['contract', 'invoice', 'manual'] as const
export const supplierConfirmationStatuses = ['unconfirmed', 'confirmed', 'rejected'] as const
export const supplierStatuses = ['candidate', 'active', 'inactive'] as const

export type SupplierSourceType = (typeof supplierSourceTypes)[number]
export type SupplierConfirmationStatus = (typeof supplierConfirmationStatuses)[number]
export type SupplierStatus = (typeof supplierStatuses)[number]

export interface Supplier {
  id: string
  standardName: string
  taxNumber: string | null
  sourceType: SupplierSourceType
  sourceContractId: string | null
  sourceInvoiceId: string | null
  confirmationStatus: SupplierConfirmationStatus
  status: SupplierStatus
  confirmedBy: string | null
  confirmedAt: string | null
  rowVersion: string
}

export interface SupplierListData {
  items: Supplier[]
  pageSize: number
  nextCursor: string | null
}

export interface SupplierSourceResolveInput {
  sourceType: 'contract' | 'invoice'
  sourceId: string
  rowVersion: string
}

export interface SupplierResolveData {
  supplier: Supplier
  sourceRowVersion: string
  created: boolean
  reused: boolean
}

export interface SupplierCandidateUpdateInput {
  rowVersion: string
  reason: string
  standardName?: string
  taxNumber?: string
  decision?: 'confirmed' | 'rejected'
}

export interface SupplierMutationData {
  supplier: Supplier
  candidateId: string
  candidateRowVersion: string
  sourceRowVersion: string
  correctionId: string
  reused: boolean
}

const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/
const CURSOR_PATTERN = /^[A-Za-z0-9_-]{1,256}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function assertExactKeys(value: Record<string, unknown>, keys: readonly string[]): void {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new TypeError('unexpected supplier response fields')
  }
}

function requireString(value: unknown, field: string): string {
  if (typeof value !== 'string') throw new TypeError(`${field} must be a string`)
  return value
}

function requireUuid(value: unknown, field: string): string {
  const decoded = requireString(value, field)
  if (!UUID_PATTERN.test(decoded)) throw new TypeError(`${field} must be a canonical lowercase UUID`)
  return decoded
}

function nullableUuid(value: unknown, field: string): string | null {
  return value === null ? null : requireUuid(value, field)
}

function positiveInteger(value: unknown, field: string): string {
  const decoded = requireString(value, field)
  if (!POSITIVE_INTEGER_PATTERN.test(decoded)) throw new TypeError(`${field} must be a positive integer string`)
  return decoded
}

function enumValue<T extends string>(value: unknown, values: readonly T[], field: string): T {
  if (typeof value !== 'string' || !values.includes(value as T)) {
    throw new TypeError(`${field} is invalid`)
  }
  return value as T
}

export function decodeSupplier(value: unknown): Supplier {
  if (!isRecord(value)) throw new TypeError('supplier must be an object')
  assertExactKeys(value, [
    'id',
    'standard_name',
    'tax_number',
    'source_type',
    'source_contract_id',
    'source_invoice_id',
    'confirmation_status',
    'status',
    'confirmed_by',
    'confirmed_at',
    'row_version',
  ])

  const sourceType = enumValue(value.source_type, supplierSourceTypes, 'source_type')
  const confirmationStatus = enumValue(
    value.confirmation_status,
    supplierConfirmationStatuses,
    'confirmation_status',
  )
  const status = enumValue(value.status, supplierStatuses, 'status')
  const sourceContractId = nullableUuid(value.source_contract_id, 'source_contract_id')
  const sourceInvoiceId = nullableUuid(value.source_invoice_id, 'source_invoice_id')
  const confirmedBy = nullableUuid(value.confirmed_by, 'confirmed_by')
  const confirmedAt = value.confirmed_at === null ? null : requireString(value.confirmed_at, 'confirmed_at')
  const standardName = requireString(value.standard_name, 'standard_name')
  const taxNumber = value.tax_number === null ? null : requireString(value.tax_number, 'tax_number')

  const expectedSourceReferences = {
    contract: [true, false],
    invoice: [false, true],
    manual: [false, false],
  } as const
  const expectedStatus = {
    unconfirmed: 'candidate',
    confirmed: 'active',
    rejected: 'inactive',
  } as const
  const observedSourceReferences = [sourceContractId !== null, sourceInvoiceId !== null]
  const expectedReferences = expectedSourceReferences[sourceType]
  if (
    observedSourceReferences[0] !== expectedReferences[0] ||
    observedSourceReferences[1] !== expectedReferences[1] ||
    status !== expectedStatus[confirmationStatus] ||
    ((confirmedBy === null || confirmedAt === null) !== (confirmationStatus === 'unconfirmed')) ||
    standardName.length < 1 ||
    standardName.length > 300 ||
    (taxNumber !== null && (taxNumber.length < 1 || taxNumber.length > 32)) ||
    (confirmedAt !== null && !Number.isFinite(Date.parse(confirmedAt)))
  ) {
    throw new TypeError('supplier state is inconsistent')
  }

  return {
    id: requireUuid(value.id, 'id'),
    standardName,
    taxNumber,
    sourceType,
    sourceContractId,
    sourceInvoiceId,
    confirmationStatus,
    status,
    confirmedBy,
    confirmedAt,
    rowVersion: positiveInteger(value.row_version, 'row_version'),
  }
}

export function decodeSupplierList(value: unknown): SupplierListData {
  if (!isRecord(value)) throw new TypeError('supplier list must be an object')
  assertExactKeys(value, ['items', 'page_size', 'next_cursor'])
  if (!Array.isArray(value.items)) throw new TypeError('items must be an array')
  if (!Number.isInteger(value.page_size) || Number(value.page_size) < 1 || Number(value.page_size) > 100) {
    throw new TypeError('page_size is invalid')
  }
  const pageSize = Number(value.page_size)
  const nextCursor = value.next_cursor === null ? null : requireString(value.next_cursor, 'next_cursor')
  if (nextCursor !== null && !CURSOR_PATTERN.test(nextCursor)) throw new TypeError('next_cursor is invalid')
  const items = value.items.map(decodeSupplier)
  if (items.length > pageSize || (nextCursor !== null && items.length !== pageSize)) {
    throw new TypeError('supplier page shape is invalid')
  }
  const ids = items.map((item) => item.id)
  if (new Set(ids).size !== ids.length || ids.some((id, index) => index > 0 && ids[index - 1]! >= id)) {
    throw new TypeError('supplier page ordering is invalid')
  }
  return { items, pageSize, nextCursor }
}

export function decodeSupplierResolve(value: unknown): SupplierResolveData {
  if (!isRecord(value)) throw new TypeError('supplier resolve result must be an object')
  assertExactKeys(value, ['supplier', 'source_row_version', 'created', 'reused'])
  if (typeof value.created !== 'boolean' || typeof value.reused !== 'boolean') {
    throw new TypeError('supplier resolve flags are invalid')
  }
  return {
    supplier: decodeSupplier(value.supplier),
    sourceRowVersion: positiveInteger(value.source_row_version, 'source_row_version'),
    created: value.created,
    reused: value.reused,
  }
}

export function decodeSupplierMutation(value: unknown): SupplierMutationData {
  if (!isRecord(value)) throw new TypeError('supplier mutation result must be an object')
  assertExactKeys(value, [
    'supplier',
    'candidate_id',
    'candidate_row_version',
    'source_row_version',
    'correction_id',
    'reused',
  ])
  if (typeof value.reused !== 'boolean') throw new TypeError('reused must be a boolean')
  return {
    supplier: decodeSupplier(value.supplier),
    candidateId: requireUuid(value.candidate_id, 'candidate_id'),
    candidateRowVersion: positiveInteger(value.candidate_row_version, 'candidate_row_version'),
    sourceRowVersion: positiveInteger(value.source_row_version, 'source_row_version'),
    correctionId: requireUuid(value.correction_id, 'correction_id'),
    reused: value.reused,
  }
}

function validateUuid(value: string, field: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${field} must be a canonical lowercase UUID`)
}

function validateRowVersion(value: string): void {
  if (!POSITIVE_INTEGER_PATTERN.test(value)) throw new TypeError('rowVersion must be a positive integer string')
}

export class SupplierApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(pageSize = 20, cursor?: string, signal?: AbortSignal): Promise<SupplierListData> {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new TypeError('pageSize is invalid')
    if (cursor !== undefined && !CURSOR_PATTERN.test(cursor)) throw new TypeError('cursor is invalid')
    const params = new URLSearchParams({ page_size: String(pageSize) })
    if (cursor !== undefined) params.set('cursor', cursor)
    return (
      await this.client.request(`/suppliers?${params.toString()}`, {
        signal,
        decode: decodeSupplierList,
      })
    ).data
  }

  async getDetail(supplierId: string, signal?: AbortSignal): Promise<Supplier> {
    validateUuid(supplierId, 'supplierId')
    return (
      await this.client.request(`/suppliers/${supplierId}`, {
        signal,
        decode: decodeSupplier,
      })
    ).data
  }

  async resolveSource(
    input: SupplierSourceResolveInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SupplierResolveData> {
    validateUuid(input.sourceId, 'sourceId')
    validateRowVersion(input.rowVersion)
    return (
      await this.client.request('/suppliers/source-candidates', {
        method: 'POST',
        idempotencyKey,
        signal,
        body: {
          source_type: input.sourceType,
          source_id: input.sourceId,
          row_version: input.rowVersion,
        },
        decode: decodeSupplierResolve,
      })
    ).data
  }

  async updateCandidate(
    supplierId: string,
    input: SupplierCandidateUpdateInput,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<SupplierMutationData> {
    validateUuid(supplierId, 'supplierId')
    validateRowVersion(input.rowVersion)
    const body: Record<string, unknown> = {
      row_version: input.rowVersion,
      reason: input.reason,
    }
    if (input.standardName !== undefined) body.standard_name = input.standardName
    if (input.taxNumber !== undefined) body.tax_number = input.taxNumber
    if (input.decision !== undefined) body.decision = input.decision
    return (
      await this.client.request(`/suppliers/${supplierId}`, {
        method: 'PATCH',
        idempotencyKey,
        signal,
        body,
        decode: decodeSupplierMutation,
      })
    ).data
  }
}

export const supplierApi = new SupplierApi()
