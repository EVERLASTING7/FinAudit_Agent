import { ApiClient, UUID_PATTERN, apiClient } from './api'
import { decodeContractListItem, type ContractListItem } from './contracts'

export interface InvoicePrimaryContractData {
  primaryContract: ContractListItem | null
}

export const contractInvoiceLinkStatuses = [
  'candidate',
  'suggested',
  'confirmed_primary',
  'cancelled',
] as const
export const matchEvidenceStatuses = ['matched', 'mismatched', 'unavailable'] as const

export type ContractInvoiceLinkStatus = (typeof contractInvoiceLinkStatuses)[number]
export type MatchEvidenceStatus = (typeof matchEvidenceStatuses)[number]
export type ContractInvoiceReasonCode =
  | 'tax_no_matched'
  | 'tax_no_mismatched'
  | 'tax_no_unavailable'
  | 'name_matched'
  | 'name_mismatched'
  | 'name_unavailable'
  | 'date_in_range'
  | 'date_out_of_range'
  | 'date_unavailable'

export interface ContractInvoiceMatchReason {
  status: MatchEvidenceStatus
  code: ContractInvoiceReasonCode
}

export interface ContractInvoiceMatchReasons {
  taxNo: ContractInvoiceMatchReason
  name: ContractInvoiceMatchReason
  date: ContractInvoiceMatchReason
}

export interface ContractInvoiceCandidate {
  contract: ContractListItem
  matchReasons: ContractInvoiceMatchReasons
}

export interface ContractInvoiceCandidateListData {
  invoiceId: string
  invoiceRowVersion: string
  items: ContractInvoiceCandidate[]
}

export interface ContractInvoiceLink {
  id: string
  contractId: string
  status: ContractInvoiceLinkStatus
  matchReasons: ContractInvoiceMatchReasons
  suggestedAt: string
  confirmedAt: string | null
  cancelledAt: string | null
  cancelReason: string | null
  rowVersion: string
}

export interface ContractInvoiceHistoryData {
  invoiceId: string
  items: ContractInvoiceLink[]
}

export interface ContractInvoiceMutationData {
  invoiceId: string
  invoiceRowVersion: string
  relation: ContractInvoiceLink
  previousPrimaryRelationId: string | null
}

const dataKeys = ['primary_contract'] as const
const positiveIntegerPattern = /^[1-9]\d*$/
const idempotencyKeyPattern = /^[A-Za-z0-9._~-]{8,128}$/

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

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
  )
}

const reasonKeys = ['status', 'code'] as const
const reasonMatrix: Readonly<
  Record<'tax_no' | 'name' | 'date', Readonly<Record<MatchEvidenceStatus, ContractInvoiceReasonCode>>>
> = {
  tax_no: {
    matched: 'tax_no_matched',
    mismatched: 'tax_no_mismatched',
    unavailable: 'tax_no_unavailable',
  },
  name: {
    matched: 'name_matched',
    mismatched: 'name_mismatched',
    unavailable: 'name_unavailable',
  },
  date: {
    matched: 'date_in_range',
    mismatched: 'date_out_of_range',
    unavailable: 'date_unavailable',
  },
}

function decodeMatchReason(
  value: unknown,
  dimension: keyof typeof reasonMatrix,
): ContractInvoiceMatchReason {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, reasonKeys) ||
    !isOneOf(value.status, matchEvidenceStatuses) ||
    value.code !== reasonMatrix[dimension][value.status]
  ) {
    throw new TypeError('invalid contract invoice match reason')
  }
  return { status: value.status, code: reasonMatrix[dimension][value.status] }
}

const reasonsKeys = ['tax_no', 'name', 'date'] as const

export function decodeContractInvoiceMatchReasons(value: unknown): ContractInvoiceMatchReasons {
  if (!isRecord(value) || !hasExactKeys(value, reasonsKeys)) {
    throw new TypeError('invalid contract invoice match reasons')
  }
  return {
    taxNo: decodeMatchReason(value.tax_no, 'tax_no'),
    name: decodeMatchReason(value.name, 'name'),
    date: decodeMatchReason(value.date, 'date'),
  }
}

const candidateKeys = ['contract', 'match_reasons'] as const
const candidateListKeys = ['invoice_id', 'invoice_row_version', 'items'] as const

export function decodeContractInvoiceCandidates(
  value: unknown,
): ContractInvoiceCandidateListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, candidateListKeys) ||
    typeof value.invoice_id !== 'string' ||
    !UUID_PATTERN.test(value.invoice_id) ||
    typeof value.invoice_row_version !== 'string' ||
    !positiveIntegerPattern.test(value.invoice_row_version) ||
    !Array.isArray(value.items)
  ) {
    throw new TypeError('invalid contract invoice candidates')
  }
  const items = value.items.map((item): ContractInvoiceCandidate => {
    if (!isRecord(item) || !hasExactKeys(item, candidateKeys)) {
      throw new TypeError('invalid contract invoice candidate')
    }
    return {
      contract: decodeContractListItem(item.contract),
      matchReasons: decodeContractInvoiceMatchReasons(item.match_reasons),
    }
  })
  if (new Set(items.map((item) => item.contract.id)).size !== items.length) {
    throw new TypeError('duplicate contract invoice candidate')
  }
  return {
    invoiceId: value.invoice_id,
    invoiceRowVersion: value.invoice_row_version,
    items,
  }
}

const linkKeys = [
  'id',
  'contract_id',
  'status',
  'match_reasons',
  'suggested_at',
  'confirmed_at',
  'cancelled_at',
  'cancel_reason',
  'row_version',
] as const

export function decodeContractInvoiceLink(value: unknown): ContractInvoiceLink {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, linkKeys) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.contract_id !== 'string' ||
    !UUID_PATTERN.test(value.contract_id) ||
    !isOneOf(value.status, contractInvoiceLinkStatuses) ||
    !isTimestamp(value.suggested_at) ||
    (value.confirmed_at !== null && !isTimestamp(value.confirmed_at)) ||
    (value.cancelled_at !== null && !isTimestamp(value.cancelled_at)) ||
    (value.cancel_reason !== null && typeof value.cancel_reason !== 'string') ||
    typeof value.row_version !== 'string' ||
    !positiveIntegerPattern.test(value.row_version)
  ) {
    throw new TypeError('invalid contract invoice link')
  }
  if (
    (value.status === 'confirmed_primary' &&
      (value.confirmed_at === null || value.cancelled_at !== null || value.cancel_reason !== null)) ||
    (value.status === 'cancelled' &&
      (value.cancelled_at === null || value.cancel_reason === null || value.cancel_reason.length === 0)) ||
    ((value.status === 'candidate' || value.status === 'suggested') &&
      (value.confirmed_at !== null || value.cancelled_at !== null || value.cancel_reason !== null))
  ) {
    throw new TypeError('invalid contract invoice lifecycle')
  }
  return {
    id: value.id,
    contractId: value.contract_id,
    status: value.status,
    matchReasons: decodeContractInvoiceMatchReasons(value.match_reasons),
    suggestedAt: value.suggested_at,
    confirmedAt: value.confirmed_at,
    cancelledAt: value.cancelled_at,
    cancelReason: value.cancel_reason,
    rowVersion: value.row_version,
  }
}

const historyKeys = ['invoice_id', 'items'] as const

export function decodeContractInvoiceHistory(value: unknown): ContractInvoiceHistoryData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, historyKeys) ||
    typeof value.invoice_id !== 'string' ||
    !UUID_PATTERN.test(value.invoice_id) ||
    !Array.isArray(value.items)
  ) {
    throw new TypeError('invalid contract invoice history')
  }
  const items = value.items.map(decodeContractInvoiceLink)
  if (
    new Set(items.map((item) => item.id)).size !== items.length ||
    items.filter((item) => item.status === 'confirmed_primary').length > 1
  ) {
    throw new TypeError('invalid contract invoice history relations')
  }
  return { invoiceId: value.invoice_id, items }
}

const mutationKeys = [
  'invoice_id',
  'invoice_row_version',
  'relation',
  'previous_primary_relation_id',
] as const

export function decodeContractInvoiceMutation(value: unknown): ContractInvoiceMutationData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, mutationKeys) ||
    typeof value.invoice_id !== 'string' ||
    !UUID_PATTERN.test(value.invoice_id) ||
    typeof value.invoice_row_version !== 'string' ||
    !positiveIntegerPattern.test(value.invoice_row_version) ||
    (value.previous_primary_relation_id !== null &&
      (typeof value.previous_primary_relation_id !== 'string' ||
        !UUID_PATTERN.test(value.previous_primary_relation_id)))
  ) {
    throw new TypeError('invalid contract invoice mutation')
  }
  const relation = decodeContractInvoiceLink(value.relation)
  if (value.previous_primary_relation_id === relation.id) {
    throw new TypeError('invalid previous primary relation')
  }
  return {
    invoiceId: value.invoice_id,
    invoiceRowVersion: value.invoice_row_version,
    relation,
    previousPrimaryRelationId: value.previous_primary_relation_id,
  }
}

function requireId(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) throw new TypeError(`${label} must be a canonical lowercase UUID`)
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

export function decodeInvoicePrimaryContract(value: unknown): InvoicePrimaryContractData {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== dataKeys.length ||
    !dataKeys.every((key) => key in value)
  ) {
    throw new TypeError('invalid invoice primary contract')
  }

  return {
    primaryContract:
      value.primary_contract === null
        ? null
        : decodeContractListItem(value.primary_contract),
  }
}

export class InvoicePrimaryContractApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async get(
    invoiceId: string,
    signal?: AbortSignal,
  ): Promise<InvoicePrimaryContractData> {
    if (!UUID_PATTERN.test(invoiceId)) {
      throw new TypeError('invoice id must be a canonical lowercase UUID')
    }
    const response = await this.client.request(
      `/invoices/${invoiceId}/primary-contract`,
      { signal, decode: decodeInvoicePrimaryContract },
    )
    return response.data
  }

  async listCandidates(
    invoiceId: string,
    signal?: AbortSignal,
  ): Promise<ContractInvoiceCandidateListData> {
    requireId(invoiceId, 'invoice id')
    const response = await this.client.request(`/invoices/${invoiceId}/contract-candidates`, {
      signal,
      decode: decodeContractInvoiceCandidates,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice candidate id mismatch')
    return response.data
  }

  async getHistory(
    invoiceId: string,
    signal?: AbortSignal,
  ): Promise<ContractInvoiceHistoryData> {
    requireId(invoiceId, 'invoice id')
    const response = await this.client.request(`/invoices/${invoiceId}/contract-link-history`, {
      signal,
      decode: decodeContractInvoiceHistory,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice history id mismatch')
    return response.data
  }

  async suggest(
    invoiceId: string,
    input: { contractId: string; invoiceRowVersion: string; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ContractInvoiceMutationData> {
    requireId(invoiceId, 'invoice id')
    requireId(input.contractId, 'contract id')
    requireVersion(input.invoiceRowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/contract-link-suggestions`, {
      method: 'POST',
      body: {
        contract_id: input.contractId,
        invoice_row_version: input.invoiceRowVersion,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeContractInvoiceMutation,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice mutation id mismatch')
    return response.data
  }

  async setPrimary(
    invoiceId: string,
    input: {
      suggestionId: string
      invoiceRowVersion: string
      relationRowVersion: string
      reason: string
    },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ContractInvoiceMutationData> {
    requireId(invoiceId, 'invoice id')
    requireId(input.suggestionId, 'suggestion id')
    requireVersion(input.invoiceRowVersion)
    requireVersion(input.relationRowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/primary-contract`, {
      method: 'PUT',
      body: {
        suggestion_id: input.suggestionId,
        invoice_row_version: input.invoiceRowVersion,
        relation_row_version: input.relationRowVersion,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeContractInvoiceMutation,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice mutation id mismatch')
    return response.data
  }

  async cancelPrimary(
    invoiceId: string,
    input: { invoiceRowVersion: string; relationRowVersion: string; reason: string },
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<ContractInvoiceMutationData> {
    requireId(invoiceId, 'invoice id')
    requireVersion(input.invoiceRowVersion)
    requireVersion(input.relationRowVersion)
    requireReason(input.reason)
    requireIdempotencyKey(idempotencyKey)
    const response = await this.client.request(`/invoices/${invoiceId}/primary-contract/cancel`, {
      method: 'POST',
      body: {
        invoice_row_version: input.invoiceRowVersion,
        relation_row_version: input.relationRowVersion,
        reason: input.reason,
      },
      idempotencyKey,
      signal,
      decode: decodeContractInvoiceMutation,
    })
    if (response.data.invoiceId !== invoiceId) throw new TypeError('invoice mutation id mismatch')
    return response.data
  }
}

export const invoicePrimaryContractApi = new InvoicePrimaryContractApi()
