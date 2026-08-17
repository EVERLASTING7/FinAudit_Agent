<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import { supplierApi, type SupplierListData } from '@/services/suppliers'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const pageSize = 20
const result = ref<SupplierListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
const resolving = ref(false)
const resolveError = ref('')
const resolveTraceId = ref('')
const resolveForm = reactive({
  sourceType: route.query.source_type === 'invoice' ? 'invoice' : 'contract' as 'contract' | 'invoice',
  sourceId: typeof route.query.source_id === 'string' ? route.query.source_id : '',
  rowVersion: typeof route.query.row_version === 'string' ? route.query.row_version : '',
})
let listController: AbortController | null = null
let resolveController: AbortController | null = null
let pendingResolveSignature = ''
let pendingResolveKey = ''

const canCorrect = computed(() => auth.hasAllPermissions(['suppliers.correct']))
const resolveReady = computed(
  () =>
    canCorrect.value &&
    UUID_PATTERN.test(resolveForm.sourceId) &&
    /^[1-9]\d*$/.test(resolveForm.rowVersion) &&
    !resolving.value,
)

function formatListError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取供应商列表。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '供应商列表加载失败，请稍后重试。'
  }
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  listController?.abort()
  requestedCursor.value = cursor
  requestedPage.value = page
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  const controller = new AbortController()
  listController = controller
  loading.value = true
  try {
    const response = await supplierApi.list(pageSize, cursor, controller.signal)
    if (listController === controller && !controller.signal.aborted) {
      result.value = response
      currentPage.value = page
    }
  } catch (error) {
    if (listController === controller && !controller.signal.aborted) formatListError(error)
  } finally {
    if (listController === controller) {
      listController = null
      loading.value = false
    }
  }
}

function retryPage(): void {
  void loadPage(requestedCursor.value, requestedPage.value)
}

function nextPage(): void {
  if (!result.value?.nextCursor) return
  const cursor = result.value.nextCursor
  cursorStack.value = [...cursorStack.value.slice(0, currentPage.value), cursor]
  void loadPage(cursor, currentPage.value + 1)
}

function previousPage(): void {
  if (currentPage.value <= 1) return
  const page = currentPage.value - 1
  cursorStack.value = cursorStack.value.slice(0, page)
  void loadPage(cursorStack.value[page - 1], page)
}

function resolveIdempotencyKey(signature: string): string {
  if (pendingResolveSignature !== signature) {
    pendingResolveSignature = signature
    pendingResolveKey = `supplier-resolve.${crypto.randomUUID()}`
  }
  return pendingResolveKey
}

function formatResolveError(error: unknown): void {
  resolveTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 409) {
    resolveError.value = '来源版本或供应商状态已变化，请返回来源详情刷新后重试。'
  } else if (error instanceof ApiError && error.status === 403) {
    resolveError.value = '当前账号无权解析供应商候选。'
  } else if (error instanceof ApiError && error.status === 404) {
    resolveError.value = '来源不存在、尚未确认或当前账号不可见。'
  } else if (error instanceof ApiError && error.status === 422) {
    resolveError.value = '来源类型、标识或数据版本不符合约束。'
  } else {
    resolveError.value = '供应商候选解析失败；可直接重试，系统会复用同一幂等键。'
  }
}

async function resolveSource(): Promise<void> {
  if (!resolveReady.value) return
  resolveError.value = ''
  resolveTraceId.value = ''
  const input = {
    sourceType: resolveForm.sourceType,
    sourceId: resolveForm.sourceId,
    rowVersion: resolveForm.rowVersion,
  }
  const signature = JSON.stringify(input)
  const controller = new AbortController()
  resolveController = controller
  resolving.value = true
  try {
    const resolved = await supplierApi.resolveSource(
      input,
      resolveIdempotencyKey(signature),
      controller.signal,
    )
    if (resolveController !== controller || controller.signal.aborted) return
    pendingResolveSignature = ''
    pendingResolveKey = ''
    await router.push({ name: 'supplier-detail', params: { supplierId: resolved.supplier.id } })
  } catch (error) {
    if (resolveController === controller && !controller.signal.aborted) formatResolveError(error)
  } finally {
    if (resolveController === controller) {
      resolveController = null
      resolving.value = false
    }
  }
}

void loadPage(undefined, 1)
onUnmounted(() => {
  listController?.abort()
  resolveController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="BETA-VS-03"
      title="供应商管理"
      description="从已确认合同或发票生成候选，并由有权限的人员修正、确认或拒绝。"
    />

    <SectionCard
      v-if="canCorrect"
      title="解析来源供应商"
      description="来源标识与版本可从合同或发票详情带入；服务端会重新校验组织、状态和当前版本。"
    >
      <form class="form-grid" @submit.prevent="resolveSource">
        <label class="form-field" for="supplier-source-type">
          <span>来源类型</span>
          <select id="supplier-source-type" v-model="resolveForm.sourceType">
            <option value="contract">合同乙方</option>
            <option value="invoice">发票销售方</option>
          </select>
        </label>
        <label class="form-field" for="supplier-source-id">
          <span>来源 ID</span>
          <input id="supplier-source-id" v-model="resolveForm.sourceId" class="mono-text" autocomplete="off" required />
        </label>
        <label class="form-field" for="supplier-source-row-version">
          <span>来源数据版本</span>
          <input id="supplier-source-row-version" v-model="resolveForm.rowVersion" inputmode="numeric" autocomplete="off" required />
        </label>
        <div v-if="resolveError" class="callout callout-danger" role="alert">
          <div>
            <strong>{{ resolveError }}</strong>
            <span v-if="resolveTraceId" class="mono-text"> Trace ID：{{ resolveTraceId }}</span>
          </div>
        </div>
        <div class="form-actions">
          <button class="button button-primary" type="submit" data-testid="resolve-supplier-source" :disabled="!resolveReady">
            {{ resolving ? '正在解析…' : '解析候选' }}
          </button>
        </div>
      </form>
    </SectionCard>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载供应商列表…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示供应商列表">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-supplier-list" @click="retryPage">重试</button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="供应商列表"
      :description="`当前页 ${result.items.length} 条；税务身份仅展示后端返回的统一公开值。`"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>标准名称</th><th>税务身份</th><th>来源</th><th>状态</th><th>数据版本</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="supplier in result.items" :key="supplier.id">
              <td><span class="table-primary"><strong>{{ supplier.standardName }}</strong><span class="mono-text">{{ supplier.id }}</span></span></td>
              <td class="mono-text">{{ supplier.taxNumber || '—' }}</td>
              <td>{{ supplier.sourceType === 'contract' ? '合同' : supplier.sourceType === 'invoice' ? '发票' : '人工' }}</td>
              <td><div class="inline-actions"><StatusTag :status="supplier.confirmationStatus" :label="supplier.confirmationStatus === 'unconfirmed' ? '待确认' : undefined" /><StatusTag :status="supplier.status" :label="supplier.status === 'inactive' ? '已失活' : undefined" /></div></td>
              <td class="numeric-text">{{ supplier.rowVersion }}</td>
              <td><RouterLink class="button button-secondary button-small" :to="{ name: 'supplier-detail', params: { supplierId: supplier.id } }">查看</RouterLink></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前页没有供应商。</div>
      <div class="pager">
        <span>第 {{ currentPage }} 页 · 每页 {{ result.pageSize }} 条</span>
        <div class="pager-buttons">
          <button type="button" aria-label="上一页" :disabled="currentPage <= 1 || loading" @click="previousPage">‹</button>
          <button type="button" aria-current="page" disabled>{{ currentPage }}</button>
          <button type="button" aria-label="下一页" :disabled="!result.nextCursor || loading" @click="nextPage">›</button>
        </div>
      </div>
    </SectionCard>
  </section>
</template>
