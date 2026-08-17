<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import JobStageIndicator from '@/components/JobStageIndicator.vue'
import PageHeader from '@/components/PageHeader.vue'
import ReportOutdatedNotice from '@/components/ReportOutdatedNotice.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import { reportApi, type AuditReportData } from '@/services/reports'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const report = ref<AuditReportData | null>(null)
const loading = ref(false)
const previewLoading = ref(false)
const downloading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const previewError = ref('')
const downloadError = ref('')
const previewUrl = ref('')
let metadataController: AbortController | null = null
let previewController: AbortController | null = null
let downloadController: AbortController | null = null

const routeReportId = computed(() =>
  typeof route.params.reportId === 'string' ? route.params.reportId : '',
)
const isReadable = computed(
  () => report.value !== null && ['ready', 'outdated', 'archived'].includes(report.value.status),
)
const canExport = computed(() => auth.hasAllPermissions(['reports.export']))
const reportStatusLabels: Readonly<Record<AuditReportData['status'], string>> = {
  queued: '报告已排队',
  generating: '报告生成中',
  ready: '报告已就绪',
  failed: '报告生成失败',
  outdated: '报告已过期',
  archived: '报告已归档',
}
const reportStatusLabel = computed(() =>
  report.value === null ? '' : reportStatusLabels[report.value.status],
)
const pageTitle = computed(() =>
  report.value === null ? '审核报告' : `审核报告 · V${report.value.reportVersion}`,
)

function formatDate(value: string | null): string {
  if (value === null) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString('zh-CN', { hour12: false })
}

function formatBytes(value: number | null): string {
  if (value === null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

function shortHash(value: string | null): string {
  return value === null ? '—' : `${value.slice(0, 12)}…${value.slice(-8)}`
}

function revokePreviewUrl(): void {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

function describeError(error: unknown, scope: 'metadata' | 'preview' | 'download'): string {
  if (!(error instanceof ApiError)) {
    return scope === 'metadata'
      ? '报告响应校验失败，请刷新后重试。'
      : scope === 'preview'
        ? 'PDF 制品完整性校验失败，未在浏览器中打开。'
        : 'XLSX 制品完整性校验失败，未触发下载。'
  }
  const messages: Readonly<Record<number, string>> = {
    401: '登录状态已失效，请重新登录。',
    403: scope === 'download' ? '当前账号无报告导出权限。' : '当前账号无报告读取权限。',
    404: '报告不存在或当前账号不可见。',
    409: '报告状态已变化，请刷新后重试。',
    503: '报告制品暂不可用，请稍后重试。',
  }
  return messages[error.status] ?? '报告请求失败，请稍后重试。'
}

async function loadPreview(current: AuditReportData): Promise<void> {
  previewController?.abort()
  revokePreviewUrl()
  previewError.value = ''
  const controller = new AbortController()
  previewController = controller
  previewLoading.value = true
  try {
    const artifact = await reportApi.previewPdf(current, controller.signal)
    if (previewController !== controller || controller.signal.aborted) return
    previewUrl.value = URL.createObjectURL(artifact.body)
    if (report.value?.id === current.id) {
      report.value = {
        ...report.value,
        status: artifact.status,
        isOutdated: artifact.isOutdated,
      }
    }
  } catch (error) {
    if (previewController === controller && !controller.signal.aborted) {
      previewError.value = describeError(error, 'preview')
    }
  } finally {
    if (previewController === controller) {
      previewController = null
      previewLoading.value = false
    }
  }
}

async function loadReport(): Promise<void> {
  metadataController?.abort()
  previewController?.abort()
  revokePreviewUrl()
  report.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  previewError.value = ''
  downloadError.value = ''
  const reportId = routeReportId.value
  if (!UUID_PATTERN.test(reportId)) {
    errorMessage.value = '报告 ID 不符合规范，无法读取报告。'
    return
  }

  const controller = new AbortController()
  metadataController = controller
  loading.value = true
  try {
    const current = await reportApi.get(reportId, controller.signal)
    if (metadataController !== controller || controller.signal.aborted) return
    report.value = current
    if (['ready', 'outdated', 'archived'].includes(current.status)) {
      await loadPreview(current)
    }
  } catch (error) {
    if (metadataController === controller && !controller.signal.aborted) {
      errorMessage.value = describeError(error, 'metadata')
      errorTraceId.value = error instanceof ApiError ? error.traceId : ''
    }
  } finally {
    if (metadataController === controller) {
      metadataController = null
      loading.value = false
    }
  }
}

async function downloadXlsx(): Promise<void> {
  const current = report.value
  if (current === null || !isReadable.value || !canExport.value || downloading.value) return
  downloadController?.abort()
  downloadError.value = ''
  const controller = new AbortController()
  downloadController = controller
  downloading.value = true
  try {
    const artifact = await reportApi.downloadXlsx(current, controller.signal)
    if (downloadController !== controller || controller.signal.aborted) return
    const objectUrl = URL.createObjectURL(artifact.body)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = artifact.filename
    link.rel = 'noopener'
    document.body.append(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
    report.value = {
      ...current,
      status: artifact.status,
      isOutdated: artifact.isOutdated,
    }
  } catch (error) {
    if (downloadController === controller && !controller.signal.aborted) {
      downloadError.value = describeError(error, 'download')
    }
  } finally {
    if (downloadController === controller) {
      downloadController = null
      downloading.value = false
    }
  }
}

watch(routeReportId, () => void loadReport(), { immediate: true })

onUnmounted(() => {
  metadataController?.abort()
  previewController?.abort()
  downloadController?.abort()
  revokePreviewUrl()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-013"
      :title="pageTitle"
      description="正式报告版本不可覆盖；PDF 预览和 XLSX 下载均经过权限与制品完整性校验。"
      :status="report?.status"
      :status-label="reportStatusLabel"
    >
      <template v-if="report" #meta>
        <span><strong>来源执行：</strong>V{{ report.reportVersion }}</span>
        <span><strong>报告 ID：</strong><code>{{ report.id }}</code></span>
        <span><strong>生成时间：</strong>{{ formatDate(report.generatedAt) }}</span>
        <span><strong>生成器：</strong>{{ report.generatorVersion }}</span>
      </template>
      <template #actions>
        <RouterLink
          v-if="report"
          class="button button-secondary"
          :to="{
            name: 'audit-task-detail',
            params: { taskId: report.auditTaskId },
            query: { executionId: report.executionId },
          }"
        >
          返回来源执行
        </RouterLink>
        <RouterLink v-else class="button button-secondary" :to="{ name: 'audit-tasks' }">
          返回审核任务
        </RouterLink>
        <button class="button button-secondary" type="button" :disabled="loading" @click="loadReport">
          刷新
        </button>
        <button
          class="button button-primary"
          type="button"
          :disabled="!isReadable || !canExport || downloading"
          :title="canExport ? '' : '当前账号缺少 reports.export 权限'"
          @click="downloadXlsx"
        >
          {{ downloading ? '正在校验…' : '下载风险明细 XLSX' }}
        </button>
      </template>
    </PageHeader>

    <div v-if="loading" class="callout" role="status">正在读取正式报告元数据…</div>
    <div v-else-if="errorMessage" class="callout callout-danger" role="alert">
      <div>
        <strong>{{ errorMessage }}</strong>
        <span v-if="errorTraceId" class="mono-text">trace_id：{{ errorTraceId }}</span>
      </div>
    </div>

    <template v-else-if="report">
      <ReportOutdatedNotice :status="report.status" :is-outdated="report.isOutdated" />

      <div v-if="report.status === 'queued' || report.status === 'generating'" class="callout">
        <JobStageIndicator
          :status="report.status === 'queued' ? 'queued' : 'running'"
          :stage="report.status === 'generating' ? 'report_generating' : null"
          :attempt-no="0"
          :max-attempts="3"
        />
      </div>

      <div v-if="report.status === 'failed'" class="callout callout-danger" role="alert">
        <div>
          <strong>报告生成失败</strong>
          <span class="mono-text">失败代码：{{ report.failureCode }}</span>
        </div>
      </div>

      <div class="content-grid content-grid-balanced">
        <SectionCard title="版本与追溯" compact>
          <dl class="summary-grid">
            <div class="summary-item"><dt>状态</dt><dd><StatusTag :status="report.status" :label="reportStatusLabels[report.status]" /></dd></div>
            <div class="summary-item"><dt>报告版本</dt><dd>V{{ report.reportVersion }}</dd></div>
            <div class="summary-item"><dt>执行 ID</dt><dd class="mono-text">{{ report.executionId }}</dd></div>
            <div class="summary-item"><dt>负载哈希</dt><dd class="mono-text">{{ shortHash(report.payloadSha256) }}</dd></div>
            <div class="summary-item"><dt>创建时间</dt><dd>{{ formatDate(report.createdAt) }}</dd></div>
            <div class="summary-item"><dt>过期时间</dt><dd>{{ formatDate(report.outdatedAt) }}</dd></div>
          </dl>
        </SectionCard>

        <SectionCard title="制品完整性" compact>
          <dl class="summary-grid">
            <div class="summary-item"><dt>PDF SHA-256</dt><dd class="mono-text">{{ shortHash(report.pdfSha256) }}</dd></div>
            <div class="summary-item"><dt>PDF 大小</dt><dd>{{ formatBytes(report.pdfSizeBytes) }}</dd></div>
            <div class="summary-item"><dt>XLSX SHA-256</dt><dd class="mono-text">{{ shortHash(report.xlsxSha256) }}</dd></div>
            <div class="summary-item"><dt>XLSX 大小</dt><dd>{{ formatBytes(report.xlsxSizeBytes) }}</dd></div>
            <div class="summary-item"><dt>数据库版本</dt><dd>{{ report.rowVersion }}</dd></div>
            <div class="summary-item"><dt>历史状态</dt><dd>{{ report.isOutdated ? '旧事实版本' : '当前事实版本' }}</dd></div>
          </dl>
        </SectionCard>
      </div>

      <SectionCard v-if="report.aiDraft" title="AI 报告草稿（未审批）" description="草稿仅概括冻结事实，不替代确定性规则结果、人工复核或正式发布决定。">
        <div class="page-stack">
          <div><strong>执行摘要</strong><p>{{ report.aiDraft.executiveSummary }}</p></div>
          <div><strong>范围说明</strong><p>{{ report.aiDraft.scopeSummary }}</p></div>
          <div><strong>风险摘要</strong><p>{{ report.aiDraft.riskSummary }}</p></div>
          <div><strong>建议动作</strong><ol><li v-for="item in report.aiDraft.recommendations" :key="item">{{ item }}</li></ol></div>
          <div v-if="report.aiDraft.warnings.length"><strong>限制与警告</strong><ul><li v-for="warning in report.aiDraft.warnings" :key="warning">{{ warning }}</li></ul></div>
          <span class="mono-text">草稿 SHA-256：{{ shortHash(report.aiDraftSha256) }}</span>
        </div>
      </SectionCard>

      <div v-else-if="report.aiDraftStatus === 'degraded'" class="callout" role="status">
        AI 报告草稿暂不可用；正式确定性 PDF/XLSX 仍按冻结事实生成。
      </div>

      <div v-if="downloadError" class="callout callout-danger" role="alert">
        <strong>{{ downloadError }}</strong>
      </div>

      <SectionCard
        title="PDF 浏览器预览"
        description="浏览器仅接收已授权、已按数据库哈希复核的 PDF Blob；对象存储地址不会暴露给前端。"
      >
        <div v-if="previewLoading" class="callout" role="status">正在读取并校验 PDF 制品…</div>
        <div v-else-if="previewError" class="callout callout-danger" role="alert">
          <div>
            <strong>{{ previewError }}</strong>
            <button class="button button-secondary button-small" type="button" @click="loadPreview(report)">
              重试预览
            </button>
          </div>
        </div>
        <iframe
          v-else-if="previewUrl"
          class="report-preview-frame"
          :src="previewUrl"
          title="正式审核报告 PDF 预览"
          referrerpolicy="no-referrer"
        />
        <div v-else class="callout">
          当前报告状态为 {{ report.status }}，PDF 制品尚不可预览。
        </div>
      </SectionCard>
    </template>
  </section>
</template>

<style scoped>
.report-preview-frame {
  width: 100%;
  min-height: 72vh;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
}

@media (max-width: 760px) {
  .report-preview-frame {
    min-height: 58vh;
  }
}
</style>
