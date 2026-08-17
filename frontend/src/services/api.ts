export interface ApiEnvelope<T> {
  code: string
  message: string
  data: T
  traceId: string
  timestamp: string
}

export interface ApiClientOptions {
  baseUrl?: string
  fetcher?: typeof fetch
  getAccessToken?: () => string | null
  getSessionGeneration?: () => number
  refreshAccessToken?: (snapshot: ApiAuthenticationSnapshot) => Promise<boolean>
  onAuthenticationInvalid?: (
    error: ApiError,
    snapshot: ApiAuthenticationSnapshot,
  ) => void
}

export interface ApiAuthenticationSnapshot {
  accessToken: string | null
  generation: number
}

export interface ApiAuthenticationController {
  getAccessToken: () => string | null
  getSessionGeneration: () => number
  refreshAccessToken: (snapshot: ApiAuthenticationSnapshot) => Promise<boolean>
  onAuthenticationInvalid: (
    error: ApiError,
    snapshot: ApiAuthenticationSnapshot,
  ) => void
}

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  headers?: HeadersInit
  body?: Record<string, unknown> | FormData
  idempotencyKey?: string
  rowVersion?: number
  signal?: AbortSignal
}

export interface DecodedApiRequestOptions<T> extends ApiRequestOptions {
  decode: (data: unknown) => T
}

export interface NoContentApiRequestOptions extends ApiRequestOptions {
  expectNoContent: true
}

export interface BinaryApiRequestOptions extends ApiRequestOptions {
  method?: 'GET'
  body?: never
  idempotencyKey?: never
  rowVersion?: never
  expectBinary: true
  accept: string
}

export interface ApiBinaryResponse {
  body: Blob
  headers: Headers
  status: number
  traceId: string
}

export interface PasswordChangeRequiredData {
  passwordChangeToken: string
  expiresIn: 300
}

interface ApiErrorOptions {
  code: string
  message: string
  status: number
  traceId: string
  data?: PasswordChangeRequiredData
  details?: unknown
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly traceId: string
  readonly data?: PasswordChangeRequiredData
  readonly details?: unknown

  constructor(options: ApiErrorOptions) {
    super(options.message)
    this.name = 'ApiError'
    this.code = options.code
    this.status = options.status
    this.traceId = options.traceId
    Object.defineProperty(this, 'data', {
      value: options.data,
      enumerable: false,
      writable: false,
      configurable: false,
    })
    this.details = options.details
  }
}

const API_BASE_URL = '/api/v1'
const API_VALIDATION_ORIGIN = 'https://finaudit.invalid'
export const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TERMINAL_AUTH_ERROR_CODES = new Set([
  'AUTH_TOKEN_REVOKED',
  'AUTH_REFRESH_EXPIRED',
  'AUTH_REUSE_DETECTED',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function selectSafeTraceId(
  value: unknown,
  fallbackTraceId: string,
  restrictedValue?: string,
): string {
  if (typeof value === 'string' && value !== restrictedValue && UUID_PATTERN.test(value)) {
    return value
  }
  return fallbackTraceId !== restrictedValue && UUID_PATTERN.test(fallbackTraceId)
    ? fallbackTraceId
    : ''
}

function parseEnvelope(value: unknown): ApiEnvelope<unknown> | null {
  if (
    !isRecord(value) ||
    typeof value.code !== 'string' ||
    typeof value.message !== 'string' ||
    typeof value.trace_id !== 'string' ||
    !UUID_PATTERN.test(value.trace_id) ||
    typeof value.timestamp !== 'string' ||
    !('data' in value)
  ) {
    return null
  }

  return {
    code: value.code,
    message: value.message,
    data: value.data,
    traceId: value.trace_id,
    timestamp: value.timestamp,
  }
}

function parseApiError(
  value: unknown,
  status: number,
  fallbackTraceId: string,
  requestPath: string,
  requestMethod: ApiRequestOptions['method'],
): ApiError {
  if (isRecord(value)) {
    const code = typeof value.code === 'string' ? value.code : `HTTP_${status}`
    const isPasswordChangeRequired = code === 'AUTH_PASSWORD_CHANGE_REQUIRED'
    const restrictedToken =
      isPasswordChangeRequired &&
      isRecord(value.data) &&
      typeof value.data.password_change_token === 'string'
        ? value.data.password_change_token
        : undefined
    const traceId = selectSafeTraceId(value.trace_id, fallbackTraceId, restrictedToken)
    let data: PasswordChangeRequiredData | undefined
    if (
      isPasswordChangeRequired &&
      requestPath === `${API_BASE_URL}/auth/login` &&
      requestMethod === 'POST'
    ) {
      if (status !== 403 || !isRecord(value.data)) {
        return new ApiError({
          code: 'API_RESPONSE_INVALID',
          message: '服务响应格式无效，请稍后重试。',
          status,
          traceId,
        })
      }
      if (
        typeof value.data.password_change_token !== 'string' ||
        value.data.password_change_token.length === 0 ||
        value.data.expires_in !== 300
      ) {
        return new ApiError({
          code: 'API_RESPONSE_INVALID',
          message: '服务响应格式无效，请稍后重试。',
          status,
          traceId,
        })
      }
      data = {
        passwordChangeToken: value.data.password_change_token,
        expiresIn: value.data.expires_in,
      }
    }

    return new ApiError({
      code,
      message:
        isPasswordChangeRequired
          ? '首次登录必须修改密码。'
          : typeof value.message === 'string'
            ? value.message
            : '请求未完成，请稍后重试。',
      status,
      traceId,
      data,
      details: isPasswordChangeRequired ? undefined : value.details,
    })
  }

  return new ApiError({
    code: `HTTP_${status}`,
    message: '请求未完成，请稍后重试。',
    status,
    traceId: fallbackTraceId,
  })
}

function buildApiPath(path: string): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) {
    throw new TypeError('API path 必须是以单个 / 开头的站内路径。')
  }

  const [pathname = ''] = path.split('?', 1)
  if (pathname.includes('%') || path.includes('\\') || path.includes('#')) {
    throw new TypeError('API path 必须保留在同源 /api/v1 下。')
  }

  const candidatePath =
    pathname === API_BASE_URL || pathname.startsWith(`${API_BASE_URL}/`)
      ? path
      : `${API_BASE_URL}${path}`

  let resolvedPath: URL
  try {
    resolvedPath = new URL(candidatePath, API_VALIDATION_ORIGIN)
  } catch {
    throw new TypeError('API path 必须保留在同源 /api/v1 下。')
  }

  if (
    resolvedPath.origin !== API_VALIDATION_ORIGIN ||
    (resolvedPath.pathname !== API_BASE_URL &&
      !resolvedPath.pathname.startsWith(`${API_BASE_URL}/`))
  ) {
    throw new TypeError('API path 必须保留在同源 /api/v1 下。')
  }

  return candidatePath
}

export class ApiClient {
  private readonly fetcher: typeof fetch
  private readonly getAccessToken: () => string | null
  private readonly getSessionGeneration: () => number
  private readonly refreshAccessToken?: (
    snapshot: ApiAuthenticationSnapshot,
  ) => Promise<boolean>
  private readonly onAuthenticationInvalid?: (
    error: ApiError,
    snapshot: ApiAuthenticationSnapshot,
  ) => void
  private refreshOperation: {
    promise: Promise<boolean>
    snapshot: ApiAuthenticationSnapshot
  } | null = null

  constructor(options: ApiClientOptions = {}) {
    const configuredBaseUrl = (options.baseUrl ?? API_BASE_URL).replace(/\/$/, '')
    if (configuredBaseUrl !== API_BASE_URL) {
      throw new TypeError('API base URL 必须固定为同源 /api/v1。')
    }
    this.fetcher = options.fetcher ?? globalThis.fetch.bind(globalThis)
    this.getAccessToken = options.getAccessToken ?? (() => null)
    this.getSessionGeneration = options.getSessionGeneration ?? (() => 0)
    this.refreshAccessToken = options.refreshAccessToken
    this.onAuthenticationInvalid = options.onAuthenticationInvalid
  }

  request(path: string, options: NoContentApiRequestOptions): Promise<void>
  request(path: string, options: BinaryApiRequestOptions): Promise<ApiBinaryResponse>
  request(path: string, options?: ApiRequestOptions): Promise<ApiEnvelope<unknown>>
  request<T>(path: string, options: DecodedApiRequestOptions<T>): Promise<ApiEnvelope<T>>
  request<T>(
    path: string,
    options:
      | ApiRequestOptions
      | BinaryApiRequestOptions
      | DecodedApiRequestOptions<T>
      | NoContentApiRequestOptions = {},
  ): Promise<ApiBinaryResponse | ApiEnvelope<unknown> | ApiEnvelope<T> | void> {
    return this.executeRequest(path, options, false)
  }

  private async executeRequest<T>(
    path: string,
    options:
      | ApiRequestOptions
      | BinaryApiRequestOptions
      | DecodedApiRequestOptions<T>
      | NoContentApiRequestOptions,
    hasRetriedAuthentication: boolean,
  ): Promise<ApiBinaryResponse | ApiEnvelope<unknown> | ApiEnvelope<T> | void> {
    const requestPath = buildApiPath(path)
    const requestMethod = options.method ?? 'GET'

    const headers = new Headers(options.headers)
    const expectBinary = 'expectBinary' in options && options.expectBinary === true
    headers.set('Accept', expectBinary ? options.accept : 'application/json')

    const requestSnapshot: ApiAuthenticationSnapshot = {
      accessToken: this.getAccessToken(),
      generation: this.getSessionGeneration(),
    }
    const token = requestSnapshot.accessToken
    if (token) {
      headers.set('Authorization', `Bearer ${token}`)
    }
    if (options.idempotencyKey) {
      headers.set('Idempotency-Key', options.idempotencyKey)
    }

    let body: BodyInit | undefined
    if (options.body instanceof FormData) {
      // 浏览器必须自行生成包含 boundary 的 multipart Content-Type。
      headers.delete('Content-Type')
      if (options.rowVersion !== undefined) {
        throw new TypeError('FormData 请求应由调用方显式写入 row_version。')
      }
      body = options.body
    } else if (options.body) {
      const jsonBody =
        options.rowVersion === undefined
          ? options.body
          : { ...options.body, row_version: options.rowVersion }
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(jsonBody)
    } else if (options.rowVersion !== undefined) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify({ row_version: options.rowVersion })
    }

    try {
      const response = await this.fetcher(requestPath, {
        method: requestMethod,
        headers,
        body,
        signal: options.signal,
        credentials: 'same-origin',
      })
      const fallbackTraceId = selectSafeTraceId(response.headers.get('x-trace-id'), '')
      const expectNoContent =
        'expectNoContent' in options && options.expectNoContent === true
      if (response.status === 204) {
        if (expectNoContent) {
          return
        }
        throw new ApiError({
          code: 'API_RESPONSE_INVALID',
          message: '服务响应格式无效，请稍后重试。',
          status: response.status,
          traceId: fallbackTraceId,
        })
      }

      if (response.ok && expectBinary) {
        return {
          body: await response.blob(),
          headers: response.headers,
          status: response.status,
          traceId: fallbackTraceId,
        }
      }

      let payload: unknown = null
      try {
        payload = await response.json()
      } catch {
        // 统一响应解析失败后，由下方生成脱敏错误。
      }

      if (!response.ok) {
        const apiError = parseApiError(
          payload,
          response.status,
          fallbackTraceId,
          requestPath,
          requestMethod,
        )
        const isTerminalAuthenticationError = TERMINAL_AUTH_ERROR_CODES.has(apiError.code)
        const currentSnapshot: ApiAuthenticationSnapshot = {
          accessToken: this.getAccessToken(),
          generation: this.getSessionGeneration(),
        }
        const isSameSession = currentSnapshot.generation === requestSnapshot.generation
        const canReplayRequest = requestMethod === 'GET' || Boolean(options.idempotencyKey)
        // 未经幂等保护的写请求不得自动重放，避免认证响应晚于业务副作用时重复写入。
        if (
          response.status === 401 &&
          Boolean(token) &&
          !hasRetriedAuthentication &&
          !isTerminalAuthenticationError &&
          isSameSession &&
          Boolean(currentSnapshot.accessToken) &&
          currentSnapshot.accessToken !== token &&
          canReplayRequest &&
          !options.signal?.aborted
        ) {
          return this.executeRequest(path, options, true)
        }
        if (
          response.status === 401 &&
          Boolean(token) &&
          !hasRetriedAuthentication &&
          !isTerminalAuthenticationError &&
          isSameSession &&
          currentSnapshot.accessToken === token &&
          !options.signal?.aborted &&
          this.refreshAccessToken
        ) {
          const refreshed = await this.refreshAccessTokenOnce(requestSnapshot)
          const replayStillOwnsSession =
            this.getSessionGeneration() === requestSnapshot.generation &&
            Boolean(this.getAccessToken())
          if (refreshed && replayStillOwnsSession) {
            if (canReplayRequest && !options.signal?.aborted) {
              return this.executeRequest(path, options, true)
            }
            throw apiError
          }
        }
        const finalSnapshot: ApiAuthenticationSnapshot = {
          accessToken: this.getAccessToken(),
          generation: this.getSessionGeneration(),
        }
        const requestStillOwnsToken =
          finalSnapshot.generation === requestSnapshot.generation &&
          finalSnapshot.accessToken === requestSnapshot.accessToken
        const terminalErrorStillOwnsSession =
          isTerminalAuthenticationError &&
          finalSnapshot.generation === requestSnapshot.generation
        if (
          terminalErrorStillOwnsSession ||
          (requestStillOwnsToken && response.status === 401 && Boolean(token))
        ) {
          this.onAuthenticationInvalid?.(apiError, requestSnapshot)
        }
        throw apiError
      }

      const envelope = parseEnvelope(payload)
      if (expectNoContent) {
        throw new ApiError({
          code: 'API_RESPONSE_INVALID',
          message: '服务响应格式无效，请稍后重试。',
          status: response.status,
          traceId: envelope?.traceId ?? fallbackTraceId,
        })
      }
      if (!envelope || envelope.code !== 'OK') {
        throw new ApiError({
          code: 'API_RESPONSE_INVALID',
          message: '服务响应格式无效，请稍后重试。',
          status: response.status,
          traceId: envelope?.traceId ?? fallbackTraceId,
        })
      }

      if ('decode' in options) {
        try {
          return { ...envelope, data: options.decode(envelope.data) }
        } catch {
          throw new ApiError({
            code: 'API_RESPONSE_INVALID',
            message: '服务响应数据格式无效，请稍后重试。',
            status: response.status,
            traceId: envelope.traceId,
          })
        }
      }
      return envelope
    } catch (error: unknown) {
      if (error instanceof ApiError) {
        throw error
      }
      throw new ApiError({
        code: 'NETWORK_ERROR',
        message: '网络连接失败，请检查网络后重试。',
        status: 0,
        traceId: '',
      })
    }
  }

  private refreshAccessTokenOnce(snapshot: ApiAuthenticationSnapshot): Promise<boolean> {
    if (!this.refreshAccessToken) {
      return Promise.resolve(false)
    }
    if (this.refreshOperation) {
      if (
        this.refreshOperation.snapshot.generation === snapshot.generation &&
        this.refreshOperation.snapshot.accessToken === snapshot.accessToken
      ) {
        return this.refreshOperation.promise
      }
      return this.refreshOperation.promise.then(() => this.refreshAccessTokenOnce(snapshot))
    }

    const operation = Promise.resolve()
      .then(() => this.refreshAccessToken?.(snapshot) ?? false)
      .catch(() => false)
    this.refreshOperation = { promise: operation, snapshot }
    void operation.then(() => {
      if (this.refreshOperation?.promise === operation) {
        this.refreshOperation = null
      }
    })
    return operation
  }
}

let authenticationController: ApiAuthenticationController | null = null

export function configureApiAuthentication(controller: ApiAuthenticationController): void {
  authenticationController = controller
}

export const apiClient = new ApiClient({
  getAccessToken: () => authenticationController?.getAccessToken() ?? null,
  getSessionGeneration: () => authenticationController?.getSessionGeneration() ?? 0,
  refreshAccessToken: (snapshot) =>
    authenticationController?.refreshAccessToken(snapshot) ?? Promise.resolve(false),
  onAuthenticationInvalid: (error, snapshot) =>
    authenticationController?.onAuthenticationInvalid(error, snapshot),
})
