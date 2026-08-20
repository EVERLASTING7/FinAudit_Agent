<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import DocumentCorrectionPanel from '@/components/DocumentCorrectionPanel.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  documentCorrectionApi,
  type DocumentCorrectionBlockPage,
  type DocumentCorrectionBusinessType,
  type DocumentCorrectionEvidence,
} from '@/services/documentCorrections'
import {
  fileApi,
  type FileBusinessType,
  type FileListItem,
  type FileOriginalArtifact,
  type FileTextPreviewData,
} from '@/services/files'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const file = ref<FileListItem | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const previewLoading = ref(false)
const previewUrl = ref('')
const previewMimeType = ref<FileOriginalArtifact['mimeType'] | ''>('')
const previewError = ref('')
const textPreview = ref<FileTextPreviewData | null>(null)
const textPreviewError = ref('')
const correctionPage = ref<DocumentCorrectionBlockPage | null>(null)
const correctionEvidence = ref<DocumentCorrectionEvidence[]>([])
const correctionLoading = ref(false)
const correctionError = ref('')
const correctionTraceId = ref('')
const archiveReason = ref('')
const retryReason = ref('')
const archiveConfirmationPending = ref(false)
const actionLoading = ref(false)
const actionMessage = ref('')
const actionError = ref('')
const actionTraceId = ref('')
let requestController: AbortController | null = null
let previewController: AbortController | null = null
let correctionController: AbortController | null = null
let actionController: AbortController | null = null
let archiveIdempotencyKey = ''
let retryIdempotencyKey = ''

const businessTypeLabels: Readonly<Record<FileBusinessType, string>> = {
  contract: '合同',
  supplementary_agreement: '补充协议',
  invoice: '发票',
  policy: '制度',
}
const canManage = computed(() => auth.hasAllPermissions(['files.manage']))
const canReadFile = computed(() => auth.hasAllPermissions(['files.read']))
const canPreview = computed(
  () =>
    file.value !== null &&
    ['stored', 'archived'].includes(file.value.status) &&
    file.value.securityScanStatus === 'clean',
)
const canArchive = computed(
  () => canManage.value && file.value?.status === 'stored' && file.value.securityScanStatus === 'clean',
)
const canRetry = computed(
  () =>
    canManage.value &&
    file.value?.job?.retryable === true &&
    file.value.status !== 'archived',
)
const correctionBusinessType = computed<DocumentCorrectionBusinessType | null>(
  () => file.value?.intendedBusinessType ?? correctionPage.value?.businessType ?? null,
)
const correctionOnlyMode = computed(
  () =>
    !canReadFile.value &&
    auth.hasAllPermissions(['system.configure']) &&
    auth.user?.roles.includes('system_admin') === true,
)
const canLoadCorrectionBlocks = computed(() => {
  const businessType = correctionBusinessType.value
  const roles = auth.user?.roles ?? []
  const hasPermission =
    auth.user?.permissions.some((permission) =>
      ['files.manage', 'system.configure'].includes(permission),
    ) ?? false
  if (!hasPermission) return false
  if (businessType === null) return correctionOnlyMode.value
  const allowed: Readonly<Record<DocumentCorrectionBusinessType, readonly string[]>> = {
    contract: ['finance_reviewer', 'contract_admin', 'system_admin'],
    supplementary_agreement: ['contract_admin', 'system_admin'],
    invoice: ['finance_reviewer', 'system_admin'],
    policy: ['audit_reviewer', 'system_admin'],
  }
  return (
    roles.some((role) => allowed[businessType].includes(role)) &&
    (file.value === null ||
      (file.value.status === 'stored' && file.value.securityScanStatus === 'clean'))
  )
})

function formatBytes(raw: string): string {
  const size = Number(raw)
  if (!Number.isSafeInteger(size) || size < 0) return raw
  if (size < 1024) return `${size} B`
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 ** 3) return `${(size / 1024 ** 2).toFixed(1)} MB`
  return `${(size / 1024 ** 3).toFixed(1)} GB`
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '文件不存在，或当前账号无权查看。'
  } else if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取该文件。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '文件详情加载失败，请稍后重试。'
  }
}

function revokePreviewUrl(): void {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  previewMimeType.value = ''
}

function previewMessage(error: unknown, kind: 'original' | 'text'): string {
  if (!(error instanceof ApiError)) return kind === 'original' ? '原文件响应校验失败。' : '解析文本响应校验失败。'
  if (error.status === 409) return kind === 'original' ? '原文件尚未进入可预览状态。' : '活动解析文本尚未就绪。'
  if (error.status === 503) return kind === 'original' ? '原文件存储暂不可用。' : '解析文本暂不可用。'
  if (error.status === 401) return '登录状态已失效，请重新登录。'
  if (error.status === 403) return '当前账号无权预览该文件。'
  return '文件预览加载失败，请稍后重试。'
}

function clearCorrectionBlocks(): void {
  correctionController?.abort()
  correctionController = null
  correctionPage.value = null
  correctionEvidence.value = []
  correctionLoading.value = false
  correctionError.value = ''
  correctionTraceId.value = ''
}

function correctionErrorMessage(error: unknown): string {
  correctionTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) return '文档纠错来源响应校验失败，请刷新后重试。'
  if (error.code === 'PARSE_VERSION_CHANGED') return '活动解析版本已变化，请重新加载纠错来源。'
  if (error.code === 'DOCUMENT_PARSE_NOT_READY') return '当前文件尚无可纠错的活动解析版本。'
  if (error.status === 403) return '当前账号缺少文档纠错权限或对应业务角色。'
  if (error.status === 404) return '文件不存在，或当前账号不可见。'
  if (error.status === 409) return '当前文件状态不能读取纠错来源。'
  return '文档纠错来源加载失败，请稍后重试。'
}

async function loadCorrectionBlocks(reset: boolean): Promise<void> {
  const fileId = String(route.params.fileId ?? '')
  if (!UUID_PATTERN.test(fileId) || !canLoadCorrectionBlocks.value) {
    if (reset) clearCorrectionBlocks()
    return
  }
  const cursor = reset ? undefined : correctionPage.value?.nextCursor ?? undefined
  if (!reset && cursor === undefined) return
  correctionController?.abort()
  const controller = new AbortController()
  correctionController = controller
  correctionLoading.value = true
  correctionError.value = ''
  correctionTraceId.value = ''
  if (reset) {
    correctionPage.value = null
    correctionEvidence.value = []
  }
  try {
    const page = await documentCorrectionApi.listBlocks(fileId, 50, cursor, controller.signal)
    if (correctionController !== controller || controller.signal.aborted) return
    if (
      !reset &&
      correctionPage.value !== null &&
      correctionPage.value.parseVersionId !== page.parseVersionId
    ) {
      throw new TypeError('document correction parse version changed within pagination')
    }
    correctionPage.value = page
    const nextEvidence = page.items.map((item) => ({
      blockId: item.blockId,
      parseVersionId: page.parseVersionId,
      pageNo: item.pageNo,
      quoteText: item.textContent,
    }))
    correctionEvidence.value = reset
      ? nextEvidence
      : [...correctionEvidence.value, ...nextEvidence]
  } catch (error) {
    if (correctionController === controller && !controller.signal.aborted) {
      correctionError.value = correctionErrorMessage(error)
    }
  } finally {
    if (correctionController === controller) {
      correctionController = null
      correctionLoading.value = false
    }
  }
}

async function correctionActivated(): Promise<void> {
  await loadCorrectionBlocks(true)
  if (file.value !== null) await loadPreviews(file.value)
}

async function loadPreviews(current: FileListItem): Promise<void> {
  previewController?.abort()
  revokePreviewUrl()
  previewError.value = ''
  textPreviewError.value = ''
  textPreview.value = null
  if (!['stored', 'archived'].includes(current.status) || current.securityScanStatus !== 'clean') return
  const controller = new AbortController()
  previewController = controller
  previewLoading.value = true
  const [original, text] = await Promise.allSettled([
    fileApi.previewOriginal(current, controller.signal),
    current.autoProcessRequested
      ? fileApi.textPreview(current.fileId, 100_000, controller.signal)
      : Promise.reject(new Error('scan-only file has no text preview')),
  ])
  if (previewController !== controller || controller.signal.aborted) return
  if (original.status === 'fulfilled') {
    previewUrl.value = URL.createObjectURL(original.value.body)
    previewMimeType.value = original.value.mimeType
    if (file.value?.fileId === current.fileId && file.value.status !== original.value.status) {
      file.value = { ...file.value, status: original.value.status }
    }
  } else {
    previewError.value = previewMessage(original.reason, 'original')
  }
  if (!current.autoProcessRequested) {
    textPreviewError.value = '该文件只执行安全扫描，未请求解析文本。'
  } else if (text.status === 'fulfilled') {
    textPreview.value = text.value
  } else {
    textPreviewError.value = previewMessage(text.reason, 'text')
  }
  if (previewController === controller) {
    previewController = null
    previewLoading.value = false
  }
}

async function loadFile(fileId: string): Promise<void> {
  requestController?.abort()
  previewController?.abort()
  clearCorrectionBlocks()
  revokePreviewUrl()
  file.value = null
  archiveConfirmationPending.value = false
  errorMessage.value = ''
  errorTraceId.value = ''
  if (!UUID_PATTERN.test(fileId)) {
    errorMessage.value = '文件 ID 格式无效。'
    loading.value = false
    return
  }
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  if (!canReadFile.value) {
    try {
      await loadCorrectionBlocks(true)
    } finally {
      if (requestController === controller) {
        requestController = null
        loading.value = false
      }
    }
    return
  }
  try {
    const response = await fileApi.get(fileId, controller.signal)
    if (requestController === controller && !controller.signal.aborted) {
      file.value = response
      await loadPreviews(response)
      await loadCorrectionBlocks(true)
    }
  } catch (error) {
    if (requestController === controller && !controller.signal.aborted) formatError(error)
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

function actionErrorMessage(error: unknown): string {
  actionTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) return '文件操作响应校验失败，请刷新后重试。'
  const messages: Readonly<Record<number, string>> = {
    401: '登录状态已失效，请重新登录。',
    403: '当前账号无权执行该文件操作。',
    404: '文件不存在或当前账号不可见。',
    409: '文件或任务状态已变化，请刷新后重试。',
    422: '操作原因不符合约束。',
    503: '文件服务暂不可用，请稍后重试。',
  }
  return messages[error.status] ?? '文件操作失败，请稍后重试。'
}

async function archiveFile(): Promise<void> {
  const current = file.value
  if (current === null || !canArchive.value || actionLoading.value || !archiveConfirmationPending.value) return
  const reason = archiveReason.value.trim()
  if (reason.length < 3) return
  archiveIdempotencyKey ||= `file-archive.${crypto.randomUUID()}`
  const controller = new AbortController()
  actionController = controller
  actionLoading.value = true
  actionMessage.value = ''
  actionError.value = ''
  actionTraceId.value = ''
  try {
    const updated = await fileApi.archive(
      current.fileId,
      current.rowVersion,
      reason,
      archiveIdempotencyKey,
      controller.signal,
    )
    if (actionController !== controller || controller.signal.aborted) return
    file.value = updated
    clearCorrectionBlocks()
    archiveReason.value = ''
    archiveConfirmationPending.value = false
    archiveIdempotencyKey = ''
    actionMessage.value = '文件已归档；历史引用和原文件保持可查。'
  } catch (error) {
    if (actionController === controller && !controller.signal.aborted) actionError.value = actionErrorMessage(error)
  } finally {
    if (actionController === controller) {
      actionController = null
      actionLoading.value = false
    }
  }
}

function requestArchiveConfirmation(): void {
  if (!canArchive.value || actionLoading.value || archiveReason.value.trim().length < 3) return
  actionMessage.value = ''
  actionError.value = ''
  actionTraceId.value = ''
  archiveConfirmationPending.value = true
}

async function retryJob(): Promise<void> {
  const current = file.value
  if (current === null || !canRetry.value || actionLoading.value) return
  const reason = retryReason.value.trim()
  if (reason.length < 3) return
  retryIdempotencyKey ||= `file-retry.${crypto.randomUUID()}`
  const controller = new AbortController()
  actionController = controller
  actionLoading.value = true
  actionMessage.value = ''
  actionError.value = ''
  actionTraceId.value = ''
  try {
    const updated = await fileApi.retry(
      current.fileId,
      current.rowVersion,
      current.jobId,
      current.job?.rowVersion ?? '',
      reason,
      retryIdempotencyKey,
      controller.signal,
    )
    if (actionController !== controller || controller.signal.aborted) return
    file.value = updated
    retryReason.value = ''
    retryIdempotencyKey = ''
    actionMessage.value = '原处理任务已重新排队，没有创建第二个文件或 Job。'
  } catch (error) {
    if (actionController === controller && !controller.signal.aborted) actionError.value = actionErrorMessage(error)
  } finally {
    if (actionController === controller) {
      actionController = null
      actionLoading.value = false
    }
  }
}

function retry(): void {
  void loadFile(String(route.params.fileId ?? ''))
}

watch(
  () => String(route.params.fileId ?? ''),
  (fileId) => void loadFile(fileId),
  { immediate: true },
)
watch(archiveReason, () => {
  archiveConfirmationPending.value = false
})
onUnmounted(() => {
  requestController?.abort()
  previewController?.abort()
  correctionController?.abort()
  actionController?.abort()
  revokePreviewUrl()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-003"
      :title="file?.originalName ?? (correctionPage ? '文档纠错' : '文件详情')"
      description="查看持久化文件元数据、安全扫描状态和当前受理任务。"
    >
      <template #meta>
        <span>文件 ID：<strong class="mono-text">{{ String(route.params.fileId ?? '') }}</strong></span>
        <span v-if="correctionBusinessType">业务类型：<strong>{{ businessTypeLabels[correctionBusinessType] }}</strong></span>
      </template>
      <template #actions>
        <RouterLink v-if="canReadFile" class="button button-secondary" :to="{ name: 'files' }">返回列表</RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载文件详情…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示文件详情">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-file-detail" @click="retry">重试</button>
      </div>
    </SectionCard>

    <template v-else-if="file">
      <SectionCard title="处理状态" description="文件、安全扫描和异步任务分别展示，不把局部成功误报为全链路成功。">
        <div class="inline-statuses">
          <StatusTag :status="file.status" />
          <StatusTag :status="file.securityScanStatus" />
          <StatusTag :status="file.jobStatus" />
        </div>
        <div v-if="actionMessage" class="callout callout-success" role="status" style="margin-top: 16px"><div><strong>{{ actionMessage }}</strong></div></div>
        <div v-if="actionError" class="callout callout-danger" role="alert" style="margin-top: 16px"><div><strong>{{ actionError }}</strong><span v-if="actionTraceId" class="mono-text"> Trace ID：{{ actionTraceId }}</span></div></div>
      </SectionCard>

      <SectionCard title="原文与解析预览" description="原文由 Backend 重新鉴权并校验 SHA-256；Markdown 只按纯文本显示，不执行文档内容。">
        <div v-if="previewLoading" role="status">正在校验预览…</div>
        <div v-if="previewError" class="callout callout-danger" role="alert"><div>{{ previewError }}</div></div>
        <iframe v-if="previewUrl && previewMimeType === 'application/pdf'" class="report-preview-frame" :src="previewUrl" title="文件原文 PDF 预览"></iframe>
        <img v-else-if="previewUrl && previewMimeType.startsWith('image/')" :src="previewUrl" :alt="`${file.originalName} 原图预览`" style="max-width: 100%; max-height: 720px; object-fit: contain" />
        <a v-else-if="previewUrl" class="button button-secondary" :href="previewUrl" target="_blank" rel="noopener">在浏览器中打开原文件</a>
        <div v-if="textPreview" style="margin-top: 16px">
          <strong>解析文本（{{ textPreview.charCount }} 字符<span v-if="textPreview.truncated">，当前仅显示前段</span>）</strong>
          <pre class="code-block" style="white-space: pre-wrap; max-height: 520px; overflow: auto">{{ textPreview.markdownText }}</pre>
        </div>
        <div v-else-if="textPreviewError" class="callout" role="note" style="margin-top: 16px"><div>{{ textPreviewError }}</div></div>
        <div v-if="canPreview" class="form-actions"><button class="button button-secondary" type="button" :disabled="previewLoading" @click="file && loadPreviews(file)">重新加载预览</button></div>
      </SectionCard>

      <SectionCard v-if="canLoadCorrectionBlocks || correctionLoading || correctionError" title="文档结构块纠错" description="来源身份由当前活动 Parse 提供；纠错先创建候选，完成后仍须显式激活。">
        <div v-if="correctionLoading && !correctionPage" role="status" aria-live="polite">正在加载可纠错文本块…</div>
        <div v-if="correctionError" class="callout callout-danger" role="alert"><div><strong>{{ correctionError }}</strong><span v-if="correctionTraceId" class="mono-text"> Trace ID：{{ correctionTraceId }}</span></div></div>
        <DocumentCorrectionPanel v-if="correctionPage && correctionBusinessType" :business-type="correctionBusinessType" :evidence-items="correctionEvidence" @activated="correctionActivated" />
        <div v-else-if="!correctionLoading && !correctionError" class="empty-inline">当前活动解析版本没有可纠错文本块。</div>
        <div class="form-actions">
          <button class="button button-secondary" type="button" :disabled="correctionLoading" data-testid="reload-document-correction-blocks" @click="loadCorrectionBlocks(true)">重新加载</button>
          <button v-if="correctionPage?.nextCursor" class="button button-secondary" type="button" :disabled="correctionLoading" data-testid="load-more-document-correction-blocks" @click="loadCorrectionBlocks(false)">加载更多</button>
        </div>
      </SectionCard>

      <SectionCard v-if="canManage" title="文件操作" description="归档不可恢复；失败重试复用当前 Job 和既有事实。">
        <form v-if="canRetry" class="form-grid" @submit.prevent="retryJob">
          <div class="form-field form-field-full"><label for="file-retry-reason">重试原因</label><input id="file-retry-reason" v-model="retryReason" class="text-input" minlength="3" maxlength="500" required /></div>
          <div class="form-actions form-field-full"><button class="button button-primary" type="submit" :disabled="actionLoading || retryReason.trim().length < 3">重新排队当前 Job</button></div>
        </form>
        <form v-if="canArchive" class="form-grid" @submit.prevent="requestArchiveConfirmation">
          <div class="form-field form-field-full"><label for="file-archive-reason">归档原因</label><input id="file-archive-reason" v-model="archiveReason" class="text-input" minlength="3" maxlength="500" required /></div>
          <div v-if="!archiveConfirmationPending" class="form-actions form-field-full"><button class="button button-danger" type="submit" :disabled="actionLoading || archiveReason.trim().length < 3">准备不可逆归档</button></div>
          <div v-else class="callout callout-danger form-field-full" role="alert">
            <div><strong>归档后不可恢复，但历史引用和原文件仍保持可查。请再次确认。</strong></div>
            <div class="form-actions">
              <button class="button button-danger" type="button" :disabled="actionLoading" @click="archiveFile">确认不可逆归档</button>
              <button class="button button-secondary" type="button" :disabled="actionLoading" @click="archiveConfirmationPending = false">取消</button>
            </div>
          </div>
        </form>
        <div v-if="!canRetry && !canArchive" class="empty-inline">当前状态没有可执行的文件管理动作。</div>
      </SectionCard>

      <SectionCard title="文件元数据" description="以下字段直接来自文件查询接口。">
        <dl class="summary-grid">
          <div class="summary-item"><dt>文件名</dt><dd>{{ file.originalName }}</dd></div>
          <div class="summary-item"><dt>大小</dt><dd>{{ formatBytes(file.sizeBytes) }}</dd></div>
          <div class="summary-item"><dt>创建时间</dt><dd>{{ formatDate(file.createdAt) }}</dd></div>
          <div class="summary-item"><dt>行版本</dt><dd class="mono-text">{{ file.rowVersion }}</dd></div>
          <div class="summary-item"><dt>内容去重复用</dt><dd>{{ file.reused ? '是' : '否' }}</dd></div>
          <div class="summary-item"><dt>自动处理</dt><dd>{{ file.autoProcessRequested ? '是' : '否' }}</dd></div>
          <div class="summary-item"><dt>目标知识库</dt><dd class="mono-text">{{ file.targetKnowledgeBaseId ?? '—' }}</dd></div>
          <div class="summary-item"><dt>下一阶段</dt><dd>安全扫描</dd></div>
        </dl>
      </SectionCard>

      <SectionCard title="受理任务" description="任务由 Job/Outbox 创建；页面只展示权威标识和当前状态。">
        <dl class="summary-grid">
          <div class="summary-item"><dt>任务 ID</dt><dd class="mono-text">{{ file.jobId }}</dd></div>
          <div class="summary-item"><dt>任务状态</dt><dd><StatusTag :status="file.jobStatus" /></dd></div>
          <div class="summary-item"><dt>任务范围</dt><dd>{{ file.jobScope === 'full' ? '安全扫描后完整处理' : '仅安全扫描' }}</dd></div>
          <div class="summary-item"><dt>业务类型</dt><dd>{{ businessTypeLabels[file.intendedBusinessType] }}</dd></div>
        </dl>
      </SectionCard>
    </template>

    <template v-else-if="correctionOnlyMode">
      <SectionCard title="文档结构块纠错" description="系统管理员仅获得获准的纠错来源投影，不获得文件原文预览或其他业务读取权限。">
        <div v-if="correctionLoading && !correctionPage" role="status" aria-live="polite">正在加载可纠错文本块…</div>
        <div v-if="correctionError" class="callout callout-danger" role="alert"><div><strong>{{ correctionError }}</strong><span v-if="correctionTraceId" class="mono-text"> Trace ID：{{ correctionTraceId }}</span></div></div>
        <DocumentCorrectionPanel v-if="correctionPage && correctionBusinessType" :business-type="correctionBusinessType" :evidence-items="correctionEvidence" @activated="correctionActivated" />
        <div v-else-if="!correctionLoading && !correctionError" class="empty-inline">当前活动解析版本没有可纠错文本块。</div>
        <div class="form-actions">
          <button class="button button-secondary" type="button" :disabled="correctionLoading" data-testid="reload-document-correction-blocks" @click="loadCorrectionBlocks(true)">重新加载</button>
          <button v-if="correctionPage?.nextCursor" class="button button-secondary" type="button" :disabled="correctionLoading" data-testid="load-more-document-correction-blocks" @click="loadCorrectionBlocks(false)">加载更多</button>
        </div>
      </SectionCard>
    </template>
  </section>
</template>

<style scoped>
.report-preview-frame {
  width: 100%;
  min-height: 640px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: white;
}

.code-block {
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-subtle);
}
</style>
