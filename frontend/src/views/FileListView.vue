<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  fileApi,
  type FileBatchUploadData,
  type FileBusinessType,
  type FileListData,
  type FileRecordData,
} from '@/services/files'
import { useAuthStore } from '@/stores/auth'

const pageSize = 20
const auth = useAuthStore()
const result = ref<FileListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
const selectedFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const businessType = ref<FileBusinessType>('contract')
const autoProcessRequested = ref(true)
const targetKnowledgeBaseId = ref('')
const uploading = ref(false)
const uploadErrorMessage = ref('')
const uploadErrorTraceId = ref('')
const uploadResult = ref<FileRecordData | null>(null)
const batchUploadResult = ref<FileBatchUploadData | null>(null)
const uploadTraceId = ref('')
let uploadIdempotencyKey = ''
let requestController: AbortController | null = null
let uploadController: AbortController | null = null

const businessTypeLabels: Readonly<Record<FileBusinessType, string>> = {
  contract: '合同',
  supplementary_agreement: '补充协议',
  invoice: '发票',
  policy: '制度',
}

const canUpload = computed(() => auth.hasAllPermissions(['files.upload']))
const targetIsValid = computed(
  () => businessType.value !== 'policy' || UUID_PATTERN.test(targetKnowledgeBaseId.value.trim()),
)
const uploadReady = computed(
  () =>
    canUpload.value &&
    selectedFiles.value.length >= 1 &&
    selectedFiles.value.length <= 20 &&
    targetIsValid.value &&
    !uploading.value,
)

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

function formatListError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取文件列表。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '文件列表加载失败，请稍后重试。'
  }
}

function formatUploadError(error: unknown): void {
  uploadErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) {
    uploadErrorMessage.value = '文件上传失败，请检查输入后重试。'
    return
  }
  const messages: Readonly<Record<number, string>> = {
    400: '文件内容或格式不合法，请选择受支持的真实文件。',
    401: '登录状态已失效，请重新登录。',
    403: '当前账号无权上传此业务类型的文件。',
    409: '上传意图与已有幂等请求或文件分类冲突，请刷新列表核对后再提交。',
    413: '文件超过服务端允许的大小。',
    422: '上传参数不符合约束，请检查业务类型和知识库 ID。',
    503: '文件存储或扫描服务暂不可用，请使用当前请求重试。',
  }
  uploadErrorMessage.value = messages[error.status] ?? '文件上传失败，请稍后重试。'
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  requestController?.abort()
  requestedCursor.value = cursor
  requestedPage.value = page
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await fileApi.list(pageSize, cursor, controller.signal)
    if (requestController === controller && !controller.signal.aborted) {
      result.value = response
      currentPage.value = page
    }
  } catch (error) {
    if (requestController === controller && !controller.signal.aborted) formatListError(error)
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

function retryPage(): void {
  void loadPage(requestedCursor.value, requestedPage.value)
}

function loadNextPage(): void {
  if (!result.value?.nextCursor) return
  const cursor = result.value.nextCursor
  cursorStack.value = [...cursorStack.value.slice(0, currentPage.value), cursor]
  void loadPage(cursor, currentPage.value + 1)
}

function loadPreviousPage(): void {
  if (currentPage.value <= 1) return
  const targetPage = currentPage.value - 1
  cursorStack.value = cursorStack.value.slice(0, targetPage)
  void loadPage(cursorStack.value[targetPage - 1], targetPage)
}

function invalidateUploadRequest(): void {
  uploadIdempotencyKey = ''
  uploadResult.value = null
  batchUploadResult.value = null
  uploadTraceId.value = ''
  uploadErrorMessage.value = ''
  uploadErrorTraceId.value = ''
  if (businessType.value !== 'policy') targetKnowledgeBaseId.value = ''
}

function selectUpload(event: Event): void {
  const input = event.currentTarget as HTMLInputElement
  selectedFiles.value = Array.from(input.files ?? [])
  invalidateUploadRequest()
}

async function uploadFile(): Promise<void> {
  if (!uploadReady.value) return
  uploadErrorMessage.value = ''
  uploadErrorTraceId.value = ''
  uploadResult.value = null
  batchUploadResult.value = null
  uploadIdempotencyKey ||= `file-upload.${crypto.randomUUID()}`
  const controller = new AbortController()
  uploadController = controller
  uploading.value = true
  try {
    const commonInput = {
      intendedBusinessType: businessType.value,
      autoProcessRequested: autoProcessRequested.value,
      ...(businessType.value === 'policy'
        ? { targetKnowledgeBaseId: targetKnowledgeBaseId.value.trim() }
        : {}),
    }
    const response =
      selectedFiles.value.length === 1
        ? await fileApi.upload(
            { ...commonInput, file: selectedFiles.value[0] as File },
            uploadIdempotencyKey,
            controller.signal,
          )
        : await fileApi.uploadBatch(
            { ...commonInput, files: selectedFiles.value },
            uploadIdempotencyKey,
            controller.signal,
          )
    if (uploadController !== controller || controller.signal.aborted) return
    if ('record' in response) uploadResult.value = response.record
    else batchUploadResult.value = response.data
    uploadTraceId.value = response.traceId
    uploadIdempotencyKey = ''
    selectedFiles.value = []
    if (fileInput.value) fileInput.value.value = ''
    cursorStack.value = [undefined]
    await loadPage(undefined, 1)
  } catch (error) {
    if (uploadController === controller && !controller.signal.aborted) formatUploadError(error)
  } finally {
    if (uploadController === controller) {
      uploadController = null
      uploading.value = false
    }
  }
}

void loadPage(undefined, 1)
onUnmounted(() => {
  requestController?.abort()
  uploadController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-003"
      title="文件管理"
      description="上传文件并查看安全扫描与异步处理受理状态。"
    />

    <SectionCard title="上传文件" description="单次最多选择 20 个文件；批量结果逐项独立受理或拒绝，失败重试复用同一幂等键。">
      <form class="form-grid" @submit.prevent="uploadFile">
        <div class="form-field form-field-full">
          <label for="upload-file">文件</label>
          <input
            id="upload-file"
            ref="fileInput"
            type="file"
            multiple
            accept=".pdf,.png,.jpg,.jpeg,.docx"
            :disabled="!canUpload || uploading"
            required
            @change="selectUpload"
          />
          <span class="form-help">已选择 {{ selectedFiles.length }} 个文件。内容、扩展名、MIME 和安全扫描均由服务端重新校验。</span>
        </div>
        <div class="form-field">
          <label for="file-business-type">业务类型</label>
          <select
            id="file-business-type"
            v-model="businessType"
            :disabled="!canUpload || uploading"
            @change="invalidateUploadRequest"
          >
            <option v-for="(label, value) in businessTypeLabels" :key="value" :value="value">{{ label }}</option>
          </select>
        </div>
        <div class="form-field">
          <label for="file-auto-process">处理方式</label>
          <select
            id="file-auto-process"
            v-model="autoProcessRequested"
            :disabled="!canUpload || uploading"
            @change="invalidateUploadRequest"
          >
            <option :value="true">安全扫描后自动处理</option>
            <option :value="false">仅执行安全扫描</option>
          </select>
        </div>
        <div v-if="businessType === 'policy'" class="form-field form-field-full">
          <label for="target-knowledge-base-id">目标知识库 ID</label>
          <input
            id="target-knowledge-base-id"
            v-model.trim="targetKnowledgeBaseId"
            class="text-input mono-text"
            type="text"
            placeholder="00000000-0000-0000-0000-000000000000"
            :disabled="!canUpload || uploading"
            :aria-invalid="targetKnowledgeBaseId !== '' && !targetIsValid"
            required
            @input="invalidateUploadRequest"
          />
          <span class="form-help">制度文件必须绑定当前账号有权提交的知识库。</span>
        </div>
        <div class="form-actions form-field-full">
          <button class="button button-primary" type="submit" :disabled="!uploadReady">
            {{ uploading ? '正在上传…' : selectedFiles.length > 1 ? '批量上传并创建任务' : '上传并创建任务' }}
          </button>
          <span v-if="!canUpload" class="form-help">当前账号只有读取权限，不能上传文件。</span>
        </div>
      </form>

      <div v-if="uploadErrorMessage" class="callout callout-danger" role="alert" style="margin-top: 14px">
        <div>
          <strong>{{ uploadErrorMessage }}</strong>
          <span v-if="uploadErrorTraceId" class="mono-text"> Trace ID：{{ uploadErrorTraceId }}</span>
        </div>
      </div>
      <div v-if="uploadResult" class="callout callout-success" role="status" style="margin-top: 14px">
        <div>
          <strong>{{ uploadResult.reused ? '已复用组织内同内容文件' : '文件已受理' }}</strong>
          文件 ID：<span class="mono-text">{{ uploadResult.fileId }}</span>；任务 ID：<span class="mono-text">{{ uploadResult.jobId }}</span>。
          <span v-if="uploadTraceId" class="mono-text"> Trace ID：{{ uploadTraceId }}</span>
        </div>
      </div>
      <div v-if="batchUploadResult" class="callout" role="status" style="margin-top: 14px">
        <div>
          <strong>批量处理完成：受理 {{ batchUploadResult.acceptedCount }} 个，拒绝 {{ batchUploadResult.rejectedCount }} 个。</strong>
          <span v-if="uploadTraceId" class="mono-text"> Trace ID：{{ uploadTraceId }}</span>
          <ul class="compact-list">
            <li v-for="item in batchUploadResult.items" :key="item.index">
              {{ item.originalName }}：{{ item.outcome === 'accepted' ? '已受理' : `已拒绝（${item.error?.code ?? 'UNKNOWN'}）` }}
            </li>
          </ul>
        </div>
      </div>
    </SectionCard>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载文件列表…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示文件列表">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-file-list" @click="retryPage">重试</button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="文件列表"
      :description="`当前页 ${result.items.length} 条记录；状态来自持久化文件与受理任务。`"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>文件</th><th>业务类型</th><th>文件 / 扫描</th><th>任务</th><th>大小</th><th>创建时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in result.items" :key="item.fileId">
              <td>
                <span class="table-primary">
                  <strong>{{ item.originalName }}</strong>
                  <span class="mono-text">{{ item.fileId }}</span>
                </span>
              </td>
              <td>{{ businessTypeLabels[item.intendedBusinessType] }}</td>
              <td>
                <div class="inline-statuses">
                  <StatusTag :status="item.status" />
                  <StatusTag :status="item.securityScanStatus" />
                </div>
              </td>
              <td>
                <span class="table-primary">
                  <StatusTag :status="item.jobStatus" />
                  <span>{{ item.jobScope === 'full' ? '完整处理' : '仅安全扫描' }}</span>
                </span>
              </td>
              <td class="numeric-text">{{ formatBytes(item.sizeBytes) }}</td>
              <td>{{ formatDate(item.createdAt) }}</td>
              <td>
                <RouterLink class="button button-secondary button-small" :to="{ name: 'file-detail', params: { fileId: item.fileId } }">查看</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前页没有文件。</div>
      <div class="pager">
        <span>第 {{ currentPage }} 页 · 每页 {{ result.pageSize }} 条</span>
        <div class="pager-buttons">
          <button type="button" aria-label="上一页" :disabled="currentPage <= 1 || loading" @click="loadPreviousPage">‹</button>
          <button type="button" aria-current="page" disabled>{{ currentPage }}</button>
          <button type="button" aria-label="下一页" :disabled="!result.nextCursor || loading" @click="loadNextPage">›</button>
        </div>
      </div>
    </SectionCard>
  </section>
</template>
