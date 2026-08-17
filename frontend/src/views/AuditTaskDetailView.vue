<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import AuditTaskExecutionStatuses from '@/components/AuditTaskExecutionStatuses.vue'
import PageHeader from '@/components/PageHeader.vue'
import RiskBadge from '@/components/RiskBadge.vue'
import RiskReviewStatuses from '@/components/RiskReviewStatuses.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  auditApi,
  type AuditRiskData,
  type AuditTaskDetailData,
} from '@/services/audits'
import { reportApi, type AuditReportData } from '@/services/reports'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const detail = ref<AuditTaskDetailData | null>(null)
const reports = ref<AuditReportData[]>([])
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const reportError = ref('')
const reason = ref('')
const writing = ref(false)
const writeError = ref('')
const writeTraceId = ref('')
const writeSuccess = ref('')
let requestController: AbortController | null = null
let writeController: AbortController | null = null
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const taskId = computed(() =>
  typeof route.params.taskId === 'string' ? route.params.taskId : '',
)
const validReason = computed(() => {
  const value = reason.value
  return value.length >= 1 && value.length <= 1000 && value === value.trim()
})
const canFinanceReview = computed(() => auth.hasAllPermissions(['audits.complete']))
const canHighReview = computed(() => auth.hasAllPermissions(['risks.review_high']))
const canNonHighReview = computed(() => auth.hasAllPermissions(['risks.review_non_high']))
const pendingRisks = computed(() =>
  detail.value?.risks.filter((risk) => risk.reviewStatus === 'pending') ?? [],
)
const readyReports = computed(() =>
  reports.value.filter((report) => ['ready', 'outdated', 'archived'].includes(report.status)),
)
const overallRisk = computed(() => {
  const order = ['none', 'notice', 'low', 'medium', 'high'] as const
  return detail.value?.risks.reduce(
    (highest, risk) =>
      order.indexOf(risk.effectiveLevel) > order.indexOf(highest) ? risk.effectiveLevel : highest,
    'none' as (typeof order)[number],
  ) ?? 'none'
})

function formatLoadError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取此审核任务。'
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '审核任务不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '审核任务详情加载失败，请稍后重试。'
  }
}

function shouldPoll(current: AuditTaskDetailData, currentReports: AuditReportData[]): boolean {
  if (['validating', 'queued', 'running'].includes(current.execution.status)) return true
  return current.task.status === 'completed' &&
    (currentReports.length === 0 || currentReports.some((report) => ['queued', 'generating'].includes(report.status)))
}

function schedulePoll(): void {
  if (pollTimer !== null) clearTimeout(pollTimer)
  pollTimer = setTimeout(() => {
    pollTimer = null
    void loadTask(false)
  }, 750)
}

async function loadReports(executionId: string, signal: AbortSignal): Promise<AuditReportData[]> {
  try {
    const response = await reportApi.list(executionId, signal)
    reportError.value = ''
    return response.items
  } catch {
    if (!signal.aborted) reportError.value = '报告状态暂时无法读取。'
    return []
  }
}

async function loadTask(showLoading = true): Promise<void> {
  requestController?.abort()
  if (pollTimer !== null) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  const targetTaskId = taskId.value
  if (!UUID_PATTERN.test(targetTaskId)) {
    detail.value = null
    errorMessage.value = '审核任务标识无效，未向服务器发送请求。'
    errorTraceId.value = ''
    loading.value = false
    return
  }
  const controller = new AbortController()
  requestController = controller
  if (showLoading) loading.value = true
  errorMessage.value = ''
  errorTraceId.value = ''
  try {
    const response = await auditApi.getTask(targetTaskId, controller.signal)
    if (requestController !== controller || controller.signal.aborted || taskId.value !== targetTaskId) return
    const nextReports = await loadReports(response.execution.id, controller.signal)
    if (requestController !== controller || controller.signal.aborted || taskId.value !== targetTaskId) return
    detail.value = response
    reports.value = nextReports
    if (shouldPoll(response, nextReports)) schedulePoll()
  } catch (error) {
    if (requestController === controller && !controller.signal.aborted) formatLoadError(error)
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

function idempotencyKey(signature: string): string {
  if (signature !== pendingSignature) {
    pendingSignature = signature
    pendingIdempotencyKey = `audit-write.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

function formatWriteError(error: unknown): void {
  writeTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 409) {
    writeError.value = '审核状态、行版本、风险处置或职责分离条件已变化，请刷新后核对。'
  } else if (error instanceof ApiError && error.status === 403) {
    writeError.value = '当前账号无权执行此审核操作。'
  } else if (error instanceof ApiError && error.status === 422) {
    writeError.value = '审核请求不符合约束，请检查操作原因。'
  } else {
    writeError.value = '审核操作失败；可直接重试，系统会复用同一幂等键。'
  }
}

async function runWrite(
  signature: string,
  operation: (key: string, signal: AbortSignal) => Promise<unknown>,
  success: string,
): Promise<void> {
  if (!validReason.value || writing.value) return
  writeError.value = ''
  writeTraceId.value = ''
  writeSuccess.value = ''
  const controller = new AbortController()
  writeController = controller
  writing.value = true
  try {
    await operation(idempotencyKey(signature), controller.signal)
    if (writeController !== controller || controller.signal.aborted) return
    writeSuccess.value = success
    reason.value = ''
    pendingSignature = ''
    pendingIdempotencyKey = ''
    await loadTask(false)
  } catch (error) {
    if (writeController === controller && !controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) {
      writeController = null
      writing.value = false
    }
  }
}

function canReviewRisk(risk: AuditRiskData): boolean {
  return risk.effectiveLevel === 'high' ? canHighReview.value : canNonHighReview.value
}

function reviewRisk(risk: AuditRiskData, decision: 'confirmed' | 'dismissed'): void {
  if (!canReviewRisk(risk) || risk.reviewStatus !== 'pending') return
  const lane = risk.effectiveLevel === 'high' ? 'high' : 'non-high'
  const input = {
    rowVersion: risk.rowVersion,
    decision,
    effectiveLevel: null,
    reason: reason.value,
  } as const
  const signature = `risk:${risk.id}:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => auditApi.reviewRisk(risk.id, lane, input, key, signal),
    decision === 'confirmed' ? '风险事实已确认。' : '风险事实已驳回。',
  )
}

function financeReview(decision: 'submit' | 'return'): void {
  if (!detail.value || !canFinanceReview.value) return
  const execution = detail.value.execution
  const input = { rowVersion: execution.rowVersion, decision, reason: reason.value }
  const signature = `finance:${execution.id}:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => auditApi.financeReview(execution.id, input, key, signal),
    decision === 'submit' ? '财务复核已提交。' : '执行已退回修正。',
  )
}

function auditReview(decision: 'complete' | 'return'): void {
  if (!detail.value || !canHighReview.value) return
  const execution = detail.value.execution
  const input = { rowVersion: execution.rowVersion, decision, reason: reason.value }
  const signature = `audit:${execution.id}:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => auditApi.auditReview(execution.id, input, key, signal),
    decision === 'complete' ? '审计复核已完成。' : '执行已退回修正。',
  )
}

watch(taskId, () => void loadTask(), { immediate: true })
onUnmounted(() => {
  requestController?.abort()
  writeController?.abort()
  if (pollTimer !== null) clearTimeout(pollTimer)
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-012"
      :title="detail ? `${detail.task.taskNo} · ${detail.task.name}` : '审核任务详情'"
      :description="detail ? `执行 V${detail.execution.versionNo} · 基准日期 ${detail.execution.baselineDate}` : '审核任务、执行、规则、风险和报告的服务端事实'"
      :status="detail?.execution.status || ''"
    >
      <template v-if="detail" #meta>
        <span><strong>任务版本：</strong>{{ detail.task.rowVersion }}</span>
        <span><strong>执行版本：</strong>{{ detail.execution.rowVersion }}</span>
        <span><strong>快照：</strong><code>{{ detail.execution.snapshotSha256 || '尚未冻结' }}</code></span>
      </template>
      <template #actions><button class="button button-secondary" type="button" data-testid="refresh-audit-task" @click="loadTask()">刷新</button></template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载审核任务详情…</div>
    <SectionCard v-else-if="errorMessage" title="无法显示审核任务"><div class="callout callout-danger" role="alert"><div><strong>{{ errorMessage }}</strong><span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span></div></div><div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-audit-task" @click="loadTask()">重试</button></div></SectionCard>

    <template v-else-if="detail">
      <div class="content-grid content-grid-balanced">
        <SectionCard title="任务与执行状态" compact><div class="tab-panel"><AuditTaskExecutionStatuses :task-status="detail.task.status" :execution-status="detail.execution.status" /></div></SectionCard>
        <SectionCard title="总体风险" compact><div class="tab-panel inline-actions" style="justify-content: flex-start"><RiskBadge :level="overallRisk" /><span>{{ pendingRisks.length }} 项风险待复核</span></div></SectionCard>
      </div>

      <SectionCard title="人工复核" description="写操作要求当前行版本、幂等键、权限和人工原因。">
        <div class="form-field"><label for="audit-review-reason">操作原因</label><textarea id="audit-review-reason" v-model="reason" rows="3" maxlength="1000" :disabled="writing" placeholder="填写风险或执行复核依据" /></div>
        <div class="inline-actions" style="margin-top: 12px">
          <button v-if="detail.execution.status === 'pending_finance_review' && canFinanceReview" class="button button-primary" type="button" :disabled="!validReason || pendingRisks.length > 0 || writing" data-testid="submit-finance-review" @click="financeReview('submit')">提交财务复核</button>
          <button v-if="detail.execution.status === 'pending_finance_review' && canFinanceReview" class="button button-danger" type="button" :disabled="!validReason || writing" data-testid="return-finance-review" @click="financeReview('return')">退回修正</button>
          <button v-if="detail.execution.status === 'pending_audit_review' && canHighReview" class="button button-primary" type="button" :disabled="!validReason || pendingRisks.length > 0 || writing" data-testid="complete-audit-review" @click="auditReview('complete')">完成审计复核</button>
          <button v-if="detail.execution.status === 'pending_audit_review' && canHighReview" class="button button-danger" type="button" :disabled="!validReason || writing" data-testid="return-audit-review" @click="auditReview('return')">退回修正</button>
        </div>
        <div v-if="writeError" class="callout callout-danger" role="alert" style="margin-top: 12px"><div><strong>{{ writeError }}</strong><span v-if="writeTraceId" class="mono-text"> Trace ID：{{ writeTraceId }}</span></div></div>
        <div v-if="writeSuccess" class="callout callout-success" role="status" style="margin-top: 12px"><div><strong>{{ writeSuccess }}</strong></div></div>
      </SectionCard>

      <SectionCard title="规则结果" :description="`当前执行共 ${detail.rules.length} 条冻结规则结果。`" compact>
        <div v-if="detail.rules.length" class="data-table-wrap"><table class="data-table"><thead><tr><th>规则</th><th>状态</th><th>实际值</th><th>预期值</th><th>适用说明</th></tr></thead><tbody><tr v-for="rule in detail.rules" :key="rule.id"><td class="mono-text">{{ rule.ruleCode }}</td><td><StatusTag :status="rule.status" /></td><td>{{ rule.actualValue || '—' }}</td><td>{{ rule.expectedValue || '—' }}</td><td>{{ rule.applicabilityReason || '—' }}</td></tr></tbody></table></div>
        <div v-else class="empty-inline">执行尚未生成规则结果。</div>
      </SectionCard>

      <SectionCard title="风险与人工结论" :description="`共 ${detail.risks.length} 项风险；高风险和非高风险走独立权限通道。`">
        <article v-for="risk in detail.risks" :key="risk.id" class="evidence-card" style="margin-bottom: 12px">
          <header><div><h3>{{ risk.ruleCode }} · {{ risk.title }}</h3><div class="card-meta"><span>实际：{{ risk.actualValue || '—' }}</span><span>预期：{{ risk.expectedValue || '—' }}</span></div></div><RiskReviewStatuses :original-level="risk.originalLevel" :effective-level="risk.effectiveLevel" :review-status="risk.reviewStatus" /></header>
          <div v-if="risk.aiExplanation" class="callout" style="margin-top: 12px">
            <div>
              <strong>AI 风险解释（未审批）</strong>
              <p>{{ risk.aiExplanation.summary }}</p>
              <p><strong>解释：</strong>{{ risk.aiExplanation.reasoningSummary }}</p>
              <p v-if="risk.aiExplanation.businessImpact"><strong>业务影响：</strong>{{ risk.aiExplanation.businessImpact }}</p>
              <p><strong>建议动作：</strong>{{ risk.aiExplanation.recommendedAction }}</p>
              <p v-if="!risk.aiExplanation.evidenceSufficient">当前授权证据不足；此文字仅解释冻结规则事实，不构成审核结论。</p>
              <ul v-if="risk.aiExplanation.warnings.length"><li v-for="warning in risk.aiExplanation.warnings" :key="warning">{{ warning }}</li></ul>
            </div>
          </div>
          <div v-else-if="risk.aiExplanationStatus === 'degraded'" class="callout" style="margin-top: 12px">
            AI 解释暂不可用；规则结果与人工复核流程不受影响。
          </div>
          <div v-if="risk.reviewStatus === 'pending' && canReviewRisk(risk)" class="inline-actions" style="margin-top: 12px"><button class="button button-primary button-small" type="button" :disabled="!validReason || writing" :data-testid="`confirm-risk-${risk.id}`" @click="reviewRisk(risk, 'confirmed')">确认风险事实</button><button class="button button-secondary button-small" type="button" :disabled="!validReason || writing" :data-testid="`dismiss-risk-${risk.id}`" @click="reviewRisk(risk, 'dismissed')">驳回风险事实</button></div>
        </article>
        <div v-if="detail.risks.length === 0" class="empty-inline">当前执行没有产生风险。</div>
      </SectionCard>

      <SectionCard title="审核报告" description="执行完成后由 Report Worker 生成版本化 PDF 与 XLSX 制品。">
        <div v-if="readyReports.length" class="data-table-wrap"><table class="data-table"><thead><tr><th>版本</th><th>状态</th><th>生成时间</th><th>操作</th></tr></thead><tbody><tr v-for="report in readyReports" :key="report.id"><td>V{{ report.reportVersion }}</td><td><StatusTag :status="report.status" /></td><td>{{ report.generatedAt ? new Date(report.generatedAt).toLocaleString('zh-CN', { hour12: false }) : '—' }}</td><td><RouterLink class="button button-primary button-small" :to="{ name: 'audit-report-detail', params: { reportId: report.id } }" :data-testid="`open-report-${report.id}`">查看报告</RouterLink></td></tr></tbody></table></div>
        <div v-else class="empty-inline">{{ reportError || (detail.task.status === 'completed' ? '报告正在生成，页面会自动刷新。' : '审核完成后才会生成报告。') }}</div>
      </SectionCard>
    </template>
  </section>
</template>
