import { ApiClient, UUID_PATTERN, apiClient } from './api'
import { decodeInvoiceListItem, type InvoiceListItem } from './invoices'

export interface ContractPrimaryInvoiceListData {
  items: InvoiceListItem[]
  pageSize: number
  nextCursor: string | null
}

const cursorPattern = /^[A-Za-z0-9_-]+$/
const listKeys = ['items', 'page_size', 'next_cursor'] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actualKeys = Object.keys(value)
  return actualKeys.length === keys.length && keys.every((key) => key in value)
}

function isCursor(value: unknown): value is string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 256 ||
    !cursorPattern.test(value)
  ) {
    return false
  }
  try {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat(-value.length & 3)
    const binary = atob(padded)
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
    const reencoded = btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
    if (reencoded !== value) return false

    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    const payload: unknown = JSON.parse(text)
    if (
      !isRecord(payload) ||
      !hasExactKeys(payload, ['id', 'v']) ||
      payload.v !== 1 ||
      typeof payload.id !== 'string' ||
      !UUID_PATTERN.test(payload.id)
    ) {
      return false
    }
    return text === JSON.stringify({ id: payload.id, v: 1 })
  } catch {
    return false
  }
}

export function decodeContractPrimaryInvoiceList(
  value: unknown,
): ContractPrimaryInvoiceListData {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, listKeys) ||
    !Array.isArray(value.items) ||
    !Number.isInteger(value.page_size) ||
    Number(value.page_size) < 1 ||
    Number(value.page_size) > 100 ||
    (value.next_cursor !== null && !isCursor(value.next_cursor))
  ) {
    throw new TypeError('invalid contract primary invoice list')
  }

  const items = value.items.map(decodeInvoiceListItem)
  const pageSize = Number(value.page_size)
  if (items.length > pageSize || (value.next_cursor !== null && items.length !== pageSize)) {
    throw new TypeError('invalid contract primary invoice list page size')
  }
  for (let index = 1; index < items.length; index += 1) {
    if (items[index - 1]!.id >= items[index]!.id) {
      throw new TypeError('invalid contract primary invoice list order')
    }
  }

  return { items, pageSize, nextCursor: value.next_cursor }
}

export class ContractPrimaryInvoiceApi {
  constructor(private readonly client: ApiClient = apiClient) {}

  async list(
    contractId: string,
    pageSize = 20,
    cursor?: string,
    signal?: AbortSignal,
  ): Promise<ContractPrimaryInvoiceListData> {
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
      `/contracts/${contractId}/primary-invoices?page_size=${pageSize}${cursorQuery}`,
      { signal, decode: decodeContractPrimaryInvoiceList },
    )
    if (response.data.pageSize !== pageSize) {
      throw new TypeError('contract primary invoice list page size does not match request')
    }
    return response.data
  }
}

export const contractPrimaryInvoiceApi = new ContractPrimaryInvoiceApi()
