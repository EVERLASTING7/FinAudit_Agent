import 'vue-router'

import type { PermissionCode } from './stores/auth'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    title: string
    uiCode?: `UI-${string}`
    description?: string
    requiresAuth?: boolean
    requiredPermissions?: readonly PermissionCode[]
    requiredAnyPermissions?: readonly PermissionCode[]
    parent?: {
      title: string
      name: string
    }
  }
}
