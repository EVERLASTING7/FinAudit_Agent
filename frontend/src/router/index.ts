import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'

import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', uiCode: 'UI-001' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    meta: { title: '首页', requiresAuth: true },
    children: [
      { path: '', redirect: { name: 'dashboard' } },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: {
          title: '工作台',
          uiCode: 'UI-002',
          description: '角色待办、风险摘要与异步任务入口',
        },
      },
      {
        path: 'files',
        name: 'files',
        component: () => import('@/views/FileListView.vue'),
        meta: {
          title: '文件管理',
          uiCode: 'UI-003',
          description: '文件上传、处理状态与版本入口',
          requiredPermissions: ['files.read'],
        },
      },
      {
        path: 'files/:fileId',
        name: 'file-detail',
        component: () => import('@/views/FileDetailView.vue'),
        meta: {
          title: '文件详情',
          uiCode: 'UI-003',
          description: '文件预览、解析与 Markdown 版本入口',
          requiredAnyPermissions: ['files.read', 'system.configure'],
          parent: { title: '文件管理', name: 'files' },
        },
      },
      {
        path: 'contracts',
        name: 'contracts',
        component: () => import('@/views/ContractListView.vue'),
        meta: {
          title: '合同列表',
          uiCode: 'UI-004',
          description: '合同查询与详情入口',
          requiredPermissions: ['financial.read'],
        },
      },
      {
        path: 'contracts/:contractId',
        name: 'contract-detail',
        component: () => import('@/views/ContractDetailView.vue'),
        meta: {
          title: '合同详情',
          uiCode: 'UI-005',
          description: '合同事实、证据与版本入口',
          requiredPermissions: ['financial.read'],
          parent: { title: '合同列表', name: 'contracts' },
        },
      },
      {
        path: 'contracts/:contractId/primary-invoices',
        name: 'contract-primary-invoices',
        component: () => import('@/views/ContractPrimaryInvoiceListView.vue'),
        meta: {
          title: '合同当前主合同发票',
          uiCode: 'UI-005',
          description: '当前以此合同为已确认主合同的发票列表',
          requiredPermissions: ['financial.read'],
          parent: { title: '合同列表', name: 'contracts' },
        },
      },
      {
        path: 'invoices',
        name: 'invoices',
        component: () => import('@/views/InvoiceListView.vue'),
        meta: {
          title: '发票列表',
          uiCode: 'UI-006',
          description: '发票查询、重复状态与详情入口',
          requiredPermissions: ['financial.read'],
        },
      },
      {
        path: 'invoices/:invoiceId',
        name: 'invoice-detail',
        component: () => import('@/views/InvoiceDetailView.vue'),
        meta: {
          title: '发票详情',
          uiCode: 'UI-007',
          description: '发票字段、明细与证据入口',
          requiredPermissions: ['financial.read'],
          parent: { title: '发票列表', name: 'invoices' },
        },
      },
      {
        path: 'invoices/:invoiceId/contract-links',
        name: 'contract-invoice-links',
        component: () => import('@/views/ContractInvoiceLinkView.vue'),
        meta: {
          title: '发票主合同',
          uiCode: 'UI-008',
          description: '当前唯一已确认主合同的只读入口',
          requiredPermissions: ['financial.read'],
          parent: { title: '发票列表', name: 'invoices' },
        },
      },
      {
        path: 'suppliers',
        name: 'suppliers',
        component: () => import('@/views/SupplierListView.vue'),
        meta: {
          title: '供应商管理',
          description: '供应商候选解析、确认与纠错入口',
          requiredPermissions: ['financial.read'],
        },
      },
      {
        path: 'suppliers/:supplierId',
        name: 'supplier-detail',
        component: () => import('@/views/SupplierDetailView.vue'),
        meta: {
          title: '供应商详情',
          description: '供应商事实、来源和人工处理入口',
          requiredPermissions: ['financial.read'],
          parent: { title: '供应商管理', name: 'suppliers' },
        },
      },
      {
        path: 'contract-invoice-links',
        name: 'contract-invoice-links-entry',
        redirect: { name: 'invoices' },
      },
      {
        path: 'knowledge-bases',
        name: 'knowledge-bases',
        component: () => import('@/views/KnowledgeBaseListView.vue'),
        meta: {
          title: '制度知识库',
          uiCode: 'UI-009',
          description: '制度版本、分块、索引与评测入口',
          requiredAnyPermissions: ['knowledge.use', 'knowledge.publish'],
        },
      },
      {
        path: 'knowledge-bases/:kbId',
        name: 'knowledge-base-detail',
        component: () => import('@/views/KnowledgeBaseDetailView.vue'),
        meta: {
          title: '知识库详情',
          uiCode: 'UI-009',
          description: '知识库版本与标签页入口',
          requiredAnyPermissions: ['knowledge.use', 'knowledge.publish'],
          parent: { title: '制度知识库', name: 'knowledge-bases' },
        },
      },
      {
        path: 'qa',
        name: 'qa',
        component: () => import('@/views/QaView.vue'),
        meta: {
          title: 'AI 问答',
          uiCode: 'UI-010',
          description: '授权制度问答与引用入口',
          requiredPermissions: ['knowledge.use'],
        },
      },
      {
        path: 'audit-tasks',
        name: 'audit-tasks',
        component: () => import('@/views/AuditTaskListView.vue'),
        meta: {
          title: '审核任务',
          uiCode: 'UI-011',
          description: '审核任务与当前执行版本入口',
          requiredPermissions: ['audits.read'],
        },
      },
      {
        path: 'audit-tasks/:taskId',
        name: 'audit-task-detail',
        component: () => import('@/views/AuditTaskDetailView.vue'),
        meta: {
          title: '审核任务详情',
          uiCode: 'UI-012',
          description: '执行快照、风险复核与证据入口',
          requiredPermissions: ['audits.read'],
          parent: { title: '审核任务', name: 'audit-tasks' },
        },
      },
      {
        path: 'audit-reports/:reportId',
        name: 'audit-report-detail',
        component: () => import('@/views/AuditReportView.vue'),
        meta: {
          title: '审核报告',
          uiCode: 'UI-013',
          description: '报告版本、预览与授权下载入口',
          requiredPermissions: ['reports.read'],
          parent: { title: '审核任务', name: 'audit-tasks' },
        },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UserManagementView.vue'),
        meta: {
          title: '用户管理',
          uiCode: 'UI-014',
          description: '用户状态与固定角色管理入口',
          requiredPermissions: ['users.manage'],
        },
      },
      {
        path: 'operation-logs',
        name: 'operation-logs',
        component: () => import('@/views/OperationLogView.vue'),
        meta: {
          title: '操作日志',
          uiCode: 'UI-014',
          description: '认证、授权与用户管理的追加式审计记录',
          requiredPermissions: ['operations.read'],
        },
      },
      {
        path: 'forbidden',
        name: 'forbidden',
        component: () => import('@/views/AccessDeniedView.vue'),
        meta: { title: '无权访问' },
      },
      {
        path: ':pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: '页面不存在' },
      },
    ],
  },
]

export function createAppRouter(history: RouterHistory = createWebHistory()): Router {
  const appRouter = createRouter({
    history,
    routes,
    scrollBehavior(_to, _from, savedPosition) {
      return savedPosition ?? { top: 0 }
    },
  })

  appRouter.beforeEach(async (to) => {
    const auth = useAuthStore()
    await auth.restoreSession()

    if (to.name === 'login' && auth.isAuthenticated) {
      return { name: 'dashboard' }
    }

    if (to.meta.requiresAuth && !auth.isAuthenticated) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }

    if (
      to.meta.requiredPermissions &&
      !auth.hasAllPermissions(to.meta.requiredPermissions)
    ) {
      return { name: 'forbidden' }
    }
    if (
      to.meta.requiredAnyPermissions &&
      !to.meta.requiredAnyPermissions.some((permission) =>
        auth.user?.permissions.includes(permission),
      )
    ) {
      return {
        name: 'forbidden',
        query: { from: to.fullPath },
      }
    }

    return true
  })

  appRouter.afterEach((to) => {
    document.title = `${to.meta.title} | FinAudit Agent`
  })

  return appRouter
}

export const router = createAppRouter()
