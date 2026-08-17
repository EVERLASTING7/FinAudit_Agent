<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import MetricCard from '@/components/MetricCard.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import { dashboardApi, type DashboardData } from '@/services/dashboard'
import { roleLabels, useAuthStore, type RoleCode } from '@/stores/auth'

const auth = useAuthStore()
const result = ref<DashboardData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
let requestController: AbortController | null = null

const roleGuidance: Readonly<Record<RoleCode, readonly string[]>> = {
  system_admin: ['关注失败技术任务与用户状态异常', '索引构建、评测和技术发布必须以后端授权结果为准'],
  finance_reviewer: ['关注待确认字段、待财务复核与退回修正', '完成审核后才能进入报告生成流程'],
  audit_reviewer: ['关注 high 风险最终复核', '制度业务审批与技术发布必须职责分离'],
  contract_admin: ['关注合同字段、补充协议与关联建议', '主合同最终确认仍由财务审核人员执行'],
  read_only: ['仅查看已授权对象和已完成任务', '报告导出仍由 reports.export 权限单独控制'],
}

const roleNames = computed(() =>
  auth.user?.roles.map((role) => roleLabels[role]).join('、') || '当前角色待加载',
)
const currentGuidance = computed(() => [
  ...new Set((auth.user?.roles ?? []).flatMap((role) => roleGuidance[role])),
])
const metricCards = computed(() => {
  if (!result.value) return []
  const cards: Array<{ label: string; value: number; hint: string; tone: 'brand' | 'gold' | 'warning' | 'danger' }> = []
  if (result.value.auditTasks) {
    cards.push({ label: '开放审核任务', value: result.value.auditTasks.openCount, hint: '当前组织未归档任务', tone: 'gold' })
    cards.push({ label: '待人工复核', value: result.value.auditTasks.pendingReviewCount, hint: '当前执行等待财务或审计复核', tone: 'brand' })
  }
  if (result.value.files) {
    cards.push({ label: '处理中／失败文件', value: result.value.files.activeProcessingCount, hint: `${result.value.files.failedProcessingCount} 个处理失败或已拒绝`, tone: result.value.files.failedProcessingCount ? 'danger' : 'brand' })
  }
  if (result.value.failedJobs) {
    cards.push({ label: '失败异步任务', value: result.value.failedJobs.failedCount, hint: '仅 jobs.recover 权限可见', tone: result.value.failedJobs.failedCount ? 'warning' : 'brand' })
  }
  return cards
})

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function validatePermissionShape(data: DashboardData): void {
  const expectedAudits = auth.hasAllPermissions(['audits.read'])
  const expectedFiles = auth.hasAllPermissions(['files.read'])
  const expectedJobs = auth.hasAllPermissions(['jobs.recover'])
  if (
    Boolean(data.auditTasks) !== expectedAudits ||
    Boolean(data.files) !== expectedFiles ||
    Boolean(data.failedJobs) !== expectedJobs
  ) {
    throw new TypeError('dashboard permission projection is inconsistent')
  }
}

async function loadDashboard(): Promise<void> {
  requestController?.abort()
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await dashboardApi.get(5, controller.signal)
    validatePermissionShape(response)
    if (requestController === controller && !controller.signal.aborted) result.value = response
  } catch (error) {
    if (requestController !== controller || controller.signal.aborted) return
    errorTraceId.value = error instanceof ApiError ? error.traceId : ''
    errorMessage.value = error instanceof ApiError && error.status === 401
      ? '登录状态已失效，请重新登录。'
      : '工作台摘要加载失败，请稍后重试。'
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

void loadDashboard()
onUnmounted(() => requestController?.abort())
</script>

<template>
  <section class="page page-stack">
    <PageHeader ui-code="UI-002" title="工作台" description="按当前数据库权限显示有界审核、文件处理和失败 Job 摘要。" :status="result ? 'ready' : 'pending'" :status-label="result ? '真实权限摘要' : '摘要加载中'">
      <template #meta><span>当前用户：<strong>{{ auth.user?.displayName || '未加载' }}</strong></span><span>角色：<strong>{{ roleNames }}</strong></span></template>
      <template #actions><RouterLink class="button button-secondary" :to="{ name: 'knowledge-bases' }">制度知识库</RouterLink><RouterLink class="button button-primary" :to="{ name: 'qa' }">制度问答</RouterLink></template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载权限裁剪摘要…</div>
    <SectionCard v-else-if="errorMessage" title="无法显示工作台"><div class="callout callout-danger" role="alert"><div><strong>{{ errorMessage }}</strong><span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span></div></div><div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-dashboard" @click="loadDashboard">重试</button></div></SectionCard>

    <template v-else-if="result">
      <div v-if="metricCards.length" class="metrics-grid" aria-label="工作台摘要"><MetricCard v-for="card in metricCards" :key="card.label" :label="card.label" :value="card.value" :hint="card.hint" :tone="card.tone" /></div>

      <div class="content-grid">
        <SectionCard v-if="result.auditTasks" title="最近审核任务" description="按更新时间倒序；进入详情后重新读取完整冻结执行与风险事实。" compact>
          <div v-if="result.auditTasks.items.length" class="data-table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>状态</th><th>当前执行</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="task in result.auditTasks.items" :key="task.id"><td><span class="table-primary"><strong>{{ task.name }}</strong><span class="mono-text">{{ task.taskNo }}</span></span></td><td><StatusTag :status="task.status" /></td><td class="mono-text">{{ task.currentExecutionId || '—' }}</td><td>{{ formatTimestamp(task.updatedAt) }}</td><td><RouterLink class="button button-secondary button-small" :to="{ name: 'audit-task-detail', params: { taskId: task.id } }">查看</RouterLink></td></tr></tbody></table></div><div v-else class="empty-inline">当前没有可见审核任务。</div>
        </SectionCard>

        <SectionCard title="当前角色提示" description="提示来自固定角色职责，不表示额外权限或实时计数。"><ul v-if="currentGuidance.length" class="plain-list"><li v-for="item in currentGuidance" :key="item" class="list-card">{{ item }}</li></ul><div v-else class="empty-inline">当前角色信息尚未加载。</div></SectionCard>
      </div>

      <SectionCard v-if="result.files" title="最近文件处理" description="只展示每个文件的权威 file_scan/file_process Job，不混入后续提取 Job。" compact>
        <div v-if="result.files.items.length" class="data-table-wrap"><table class="data-table"><thead><tr><th>文件</th><th>业务类型</th><th>文件 / 扫描状态</th><th>处理 Job</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="file in result.files.items" :key="file.fileId"><td><span class="table-primary"><strong>{{ file.originalName }}</strong><span class="mono-text">{{ file.fileId }}</span></span></td><td>{{ file.intendedBusinessType }}</td><td><div class="inline-actions"><StatusTag :status="file.status" /><StatusTag :status="file.securityScanStatus" /></div></td><td><span class="table-primary"><StatusTag :status="file.jobStatus" /><span class="mono-text">{{ file.jobId }}</span></span></td><td>{{ formatTimestamp(file.createdAt) }}</td><td><RouterLink class="button button-secondary button-small" :to="{ name: 'file-detail', params: { fileId: file.fileId } }">查看</RouterLink></td></tr></tbody></table></div><div v-else class="empty-inline">当前没有可见文件。</div>
      </SectionCard>

      <SectionCard v-if="result.failedJobs" title="失败异步任务" description="仅系统恢复权限可见；错误正文、输入、Worker 与 lease 信息不会进入浏览器。" compact>
        <div v-if="result.failedJobs.items.length" class="data-table-wrap"><table class="data-table"><thead><tr><th>Job</th><th>资源</th><th>阶段</th><th>尝试</th><th>错误代码</th><th>创建时间</th></tr></thead><tbody><tr v-for="job in result.failedJobs.items" :key="job.id"><td><span class="table-primary"><strong>{{ job.jobType }}</strong><span class="mono-text">{{ job.id }}</span></span></td><td><span class="table-primary"><strong>{{ job.resourceType }}</strong><span class="mono-text">{{ job.resourceId }}</span></span></td><td>{{ job.stage || '—' }}</td><td class="numeric-text">{{ job.attemptNo }} / {{ job.maxAttempts }}</td><td><StatusTag status="failed" :label="job.errorCode" /></td><td>{{ formatTimestamp(job.createdAt) }}</td></tr></tbody></table></div><div v-else class="empty-inline">当前没有失败异步任务。</div>
      </SectionCard>
    </template>
  </section>
</template>
