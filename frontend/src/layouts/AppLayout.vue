<script setup lang="ts">
import { computed, watch } from 'vue'
import {
  RouterLink,
  RouterView,
  useRoute,
  useRouter,
  type RouteRecordName,
} from 'vue-router'

import Breadcrumbs from '@/components/Breadcrumbs.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getEnvironmentPresentation } from '@/config/environment'
import { roleLabels, useAuthStore } from '@/stores/auth'

interface NavigationItem {
  label: string
  routeName: RouteRecordName
}

const navigationItems: readonly NavigationItem[] = [
  { label: '工作台', routeName: 'dashboard' },
  { label: '文件管理', routeName: 'files' },
  { label: '合同管理', routeName: 'contracts' },
  { label: '发票管理', routeName: 'invoices' },
  { label: '供应商管理', routeName: 'suppliers' },
  { label: '制度知识库', routeName: 'knowledge-bases' },
  { label: 'AI 问答', routeName: 'qa' },
  { label: '审核任务', routeName: 'audit-tasks' },
  { label: '用户管理', routeName: 'users' },
  { label: '操作日志', routeName: 'operation-logs' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const visibleNavigationItems = computed(() =>
  navigationItems.filter((item) => {
    const permissions = router.resolve({ name: item.routeName }).meta.requiredPermissions
    const anyPermissions = router.resolve({ name: item.routeName }).meta.requiredAnyPermissions
    return (
      (!permissions || auth.hasAllPermissions(permissions)) &&
      (!anyPermissions || anyPermissions.some((permission) => auth.user?.permissions.includes(permission)))
    )
  }),
)

const environment = getEnvironmentPresentation(import.meta.env.VITE_APP_ENV)

watch(
  () => auth.isAuthenticated,
  (authenticated, wasAuthenticated) => {
    if (wasAuthenticated && !authenticated) {
      void router.replace({ name: 'login', query: { redirect: route.fullPath } })
    }
  },
)

async function signOut(): Promise<void> {
  await auth.signOut()
}
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主内容</a>
    <header class="topbar">
      <div class="brand-block">
        <strong>FinAudit Agent</strong>
        <span>企业财务审核辅助平台</span>
      </div>
      <div class="topbar-actions">
        <StatusTag :status="environment.status" :label="environment.label" />
        <div class="user-summary">
          <strong>{{ auth.user?.displayName }}</strong>
          <span v-for="role in auth.user?.roles" :key="role">{{ roleLabels[role] }}</span>
        </div>
        <button class="button button-secondary" type="button" @click="signOut">退出登录</button>
      </div>
    </header>

    <aside class="sidebar">
      <nav aria-label="主导航">
        <RouterLink
          v-for="item in visibleNavigationItems"
          :key="String(item.routeName)"
          :to="{ name: item.routeName }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
      <p class="sidebar-note">AI 仅提供审核辅助，不替代人工最终决定。</p>
    </aside>

    <main id="main-content" class="main-area" tabindex="-1">
      <Breadcrumbs />
      <RouterView />
    </main>
  </div>
</template>
