import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  configureApiAuthentication,
  type ApiAuthenticationSnapshot,
} from '@/services/api'
import {
  authApi,
  type AuthSession,
  type CurrentUser,
  type LoginInput,
  type PermissionCode,
  type RoleCode,
} from '@/services/auth'

export type { CurrentUser, PermissionCode, RoleCode }

export const roleLabels: Record<RoleCode, string> = {
  system_admin: '系统管理员',
  finance_reviewer: '财务审核人员',
  audit_reviewer: '审计复核人员',
  contract_admin: '合同管理员',
  read_only: '只读用户',
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  const accessToken = ref<string | null>(null)
  const initialized = ref(false)
  const remoteLogoutUnconfirmed = ref(false)
  const sessionGeneration = ref(0)
  let restorePromise: Promise<void> | null = null
  let refreshOperation: {
    controller: AbortController
    promise: Promise<boolean>
    snapshot: ApiAuthenticationSnapshot
  } | null = null
  let logoutPromise: Promise<boolean> | null = null
  let cookieCleanupPromise: Promise<void> | null = null

  const isAuthenticated = computed(() => user.value !== null && accessToken.value !== null)

  function applySession(session: AuthSession): void {
    user.value = session.user
    accessToken.value = session.accessToken
  }

  function clearSessionState(): void {
    user.value = null
    accessToken.value = null
  }

  function currentSnapshot(): ApiAuthenticationSnapshot {
    return {
      accessToken: accessToken.value,
      generation: sessionGeneration.value,
    }
  }

  function isCurrentSnapshot(snapshot: ApiAuthenticationSnapshot): boolean {
    return (
      sessionGeneration.value === snapshot.generation &&
      accessToken.value === snapshot.accessToken
    )
  }

  function invalidateSession(): void {
    sessionGeneration.value += 1
    clearSessionState()
    initialized.value = true
  }

  function invalidateSessionIfCurrent(snapshot: ApiAuthenticationSnapshot): void {
    if (isCurrentSnapshot(snapshot)) {
      invalidateSession()
    }
  }

  function clearSession(): void {
    invalidateSession()
  }

  function setAuthenticatedSession(nextUser: CurrentUser, token: string): void {
    sessionGeneration.value += 1
    user.value = nextUser
    accessToken.value = token
    initialized.value = true
  }

  async function signIn(input: LoginInput): Promise<void> {
    if (logoutPromise) {
      await logoutPromise
    }
    if (cookieCleanupPromise) {
      await cookieCleanupPromise
    } else if (refreshOperation) {
      await refreshOperation.promise
    }
    applySession(await authApi.login(input))
    sessionGeneration.value += 1
    remoteLogoutUnconfirmed.value = false
    initialized.value = true
  }

  function refreshSession(
    expectedSnapshot: ApiAuthenticationSnapshot = currentSnapshot(),
  ): Promise<boolean> {
    if (!isCurrentSnapshot(expectedSnapshot)) {
      return Promise.resolve(false)
    }
    if (refreshOperation) {
      return isSameSnapshot(refreshOperation.snapshot, expectedSnapshot)
        ? refreshOperation.promise
        : Promise.resolve(false)
    }

    const controller = new AbortController()
    const operation = (async () => {
      try {
        const session = await authApi.refresh(controller.signal)
        if (!isCurrentSnapshot(expectedSnapshot)) {
          return false
        }
        if (expectedSnapshot.accessToken === null) {
          sessionGeneration.value += 1
        }
        applySession(session)
        initialized.value = true
        return true
      } catch {
        invalidateSessionIfCurrent(expectedSnapshot)
        return false
      }
    })()
    refreshOperation = { controller, promise: operation, snapshot: expectedSnapshot }
    void operation.then(() => {
      if (refreshOperation?.promise === operation) {
        refreshOperation = null
      }
    })
    return operation
  }

  function restoreSession(): Promise<void> {
    if (initialized.value) {
      return Promise.resolve()
    }
    if (restorePromise) {
      return restorePromise
    }

    const operation = refreshSession().then(() => undefined)
    restorePromise = operation
    void operation.then(() => {
      if (restorePromise === operation) {
        restorePromise = null
      }
    })
    return operation
  }

  async function reloadCurrentUser(): Promise<void> {
    const snapshot = currentSnapshot()
    const nextUser = await authApi.getCurrentUser()
    if (isCurrentSnapshot(snapshot)) {
      user.value = nextUser
    }
  }

  function signOut(): Promise<boolean> {
    if (logoutPromise) {
      return logoutPromise
    }

    const refreshToDrain = refreshOperation
    invalidateSession()
    const logoutGeneration = sessionGeneration.value
    remoteLogoutUnconfirmed.value = true
    refreshToDrain?.controller.abort()
    const operation = (async () => {
      try {
        await authApi.logout()
        if (
          sessionGeneration.value === logoutGeneration &&
          accessToken.value === null
        ) {
          remoteLogoutUnconfirmed.value = false
        }
        return true
      } catch {
        if (
          sessionGeneration.value === logoutGeneration &&
          accessToken.value === null
        ) {
          remoteLogoutUnconfirmed.value = true
        }
        return false
      }
    })()
    logoutPromise = operation
    void operation.then(() => {
      if (logoutPromise === operation) {
        logoutPromise = null
      }
    })
    if (refreshToDrain && !cookieCleanupPromise) {
      const cleanup = Promise.all([refreshToDrain.promise, operation]).then(
        async ([, initialLogoutConfirmed]) => {
          try {
            await authApi.logout()
            if (
              !initialLogoutConfirmed &&
              sessionGeneration.value === logoutGeneration &&
              accessToken.value === null
            ) {
              remoteLogoutUnconfirmed.value = false
            }
          } catch {
            if (
              !initialLogoutConfirmed &&
              sessionGeneration.value === logoutGeneration &&
              accessToken.value === null
            ) {
              remoteLogoutUnconfirmed.value = true
            }
          }
        },
      )
      cookieCleanupPromise = cleanup
      void cleanup.then(() => {
        if (cookieCleanupPromise === cleanup) {
          cookieCleanupPromise = null
        }
      })
    }
    return operation
  }

  function hasAllPermissions(requiredPermissions: readonly PermissionCode[]): boolean {
    return requiredPermissions.every((permission) => user.value?.permissions.includes(permission))
  }

  configureApiAuthentication({
    getAccessToken: () => accessToken.value,
    getSessionGeneration: () => sessionGeneration.value,
    refreshAccessToken: refreshSession,
    onAuthenticationInvalid: (_error, snapshot) => {
      if (sessionGeneration.value === snapshot.generation) {
        invalidateSession()
      }
    },
  })

  return {
    accessToken,
    clearSession,
    hasAllPermissions,
    initialized,
    isAuthenticated,
    reloadCurrentUser,
    remoteLogoutUnconfirmed,
    restoreSession,
    setAuthenticatedSession,
    signIn,
    signOut,
    user,
  }
})

function isSameSnapshot(
  left: ApiAuthenticationSnapshot,
  right: ApiAuthenticationSnapshot,
): boolean {
  return left.generation === right.generation && left.accessToken === right.accessToken
}
