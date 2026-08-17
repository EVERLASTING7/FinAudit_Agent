import { ApiClient, UUID_PATTERN, apiClient } from './api'

export const roleCodes = [
  'system_admin',
  'finance_reviewer',
  'audit_reviewer',
  'contract_admin',
  'read_only',
] as const

export type RoleCode = (typeof roleCodes)[number]

export const permissionCodes = [
  'users.manage',
  'temporary_roles.request',
  'temporary_roles.decide',
  'system.configure',
  'operations.read',
  'jobs.recover',
  'files.read',
  'files.upload',
  'files.manage',
  'financial.read',
  'contracts.manage',
  'invoices.manage',
  'suppliers.correct',
  'links.suggest',
  'links.manage_primary',
  'knowledge.use',
  'knowledge.submit',
  'knowledge.approve',
  'knowledge.publish',
  'audits.read',
  'audits.create',
  'risks.review_non_high',
  'risks.review_high',
  'audits.complete',
  'reports.read',
  'reports.export',
] as const

export type PermissionCode = (typeof permissionCodes)[number]

export interface CurrentUser {
  id: string
  displayName: string
  roles: RoleCode[]
  permissions: PermissionCode[]
}

export interface AuthSession {
  accessToken: string
  tokenType: 'Bearer'
  expiresIn: 900
  user: CurrentUser
}

export interface LoginInput {
  username: string
  password: string
  rememberMe: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isOneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === 'string' && allowed.some((candidate) => candidate === value)
}

function decodeUniqueCodes<T extends string>(value: unknown, allowed: readonly T[]): T[] {
  if (!Array.isArray(value) || !value.every((item) => isOneOf(item, allowed))) {
    throw new TypeError('invalid authentication code list')
  }
  if (new Set(value).size !== value.length) {
    throw new TypeError('duplicate authentication code')
  }
  const codes = [...value]
  if (codes.some((code, index) => index > 0 && codes[index - 1]! > code)) {
    throw new TypeError('authentication code list is not sorted')
  }
  return codes
}

export function decodeCurrentUser(value: unknown): CurrentUser {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    !UUID_PATTERN.test(value.id) ||
    typeof value.display_name !== 'string' ||
    value.display_name.length === 0
  ) {
    throw new TypeError('invalid current user')
  }

  return {
    id: value.id,
    displayName: value.display_name,
    roles: decodeUniqueCodes(value.roles, roleCodes),
    permissions: decodeUniqueCodes(value.permissions, permissionCodes),
  }
}

export function decodeAuthSession(value: unknown): AuthSession {
  if (
    !isRecord(value) ||
    typeof value.access_token !== 'string' ||
    value.access_token.length === 0 ||
    value.token_type !== 'Bearer' ||
    value.expires_in !== 900
  ) {
    throw new TypeError('invalid authentication session')
  }

  return {
    accessToken: value.access_token,
    tokenType: value.token_type,
    expiresIn: value.expires_in,
    user: decodeCurrentUser(value.user),
  }
}

export class AuthApi {
  constructor(
    private readonly authenticatedClient: ApiClient = apiClient,
    private readonly anonymousClient: ApiClient = new ApiClient(),
  ) {}

  async login(input: LoginInput): Promise<AuthSession> {
    const response = await this.anonymousClient.request('/auth/login', {
      method: 'POST',
      body: {
        username: input.username,
        password: input.password,
        remember_me: input.rememberMe,
      },
      decode: decodeAuthSession,
    })
    return response.data
  }

  async refresh(signal?: AbortSignal): Promise<AuthSession> {
    const response = await this.anonymousClient.request('/auth/refresh', {
      method: 'POST',
      signal,
      decode: decodeAuthSession,
    })
    return response.data
  }

  async logout(): Promise<void> {
    await this.anonymousClient.request('/auth/logout', {
      method: 'POST',
      expectNoContent: true,
    })
  }

  async getCurrentUser(): Promise<CurrentUser> {
    const response = await this.authenticatedClient.request('/auth/me', {
      decode: decodeCurrentUser,
    })
    return response.data
  }

  async changePassword(passwordChangeToken: string, newPassword: string): Promise<void> {
    if (!passwordChangeToken) {
      throw new TypeError('password change token is required')
    }
    await this.anonymousClient.request('/auth/password/change', {
      method: 'POST',
      headers: { Authorization: `Bearer ${passwordChangeToken}` },
      body: { new_password: newPassword },
      expectNoContent: true,
    })
  }
}

export const authApi = new AuthApi()
