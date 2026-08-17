<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import DecimalAmount from '@/components/DecimalAmount.vue'
import InvoiceStatuses from '@/components/InvoiceStatuses.vue'
import InvoiceManagementPanel from '@/components/InvoiceManagementPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import PageTabs from '@/components/PageTabs.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  invoiceApi,
  type InvoiceDetail,
  type InvoiceDuplicateCandidateBasisStatus,
  type InvoiceDuplicateCandidateListData,
  type InvoiceExactDuplicatePairData,
  type InvoiceMutationData,
} from '@/services/invoices'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const canCorrectSuppliers = computed(() => auth.hasAllPermissions(['suppliers.correct']))
const duplicateCandidatePageSize = 20
const activeTab = ref('fields')
const invoice = ref<InvoiceDetail | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const duplicateCandidateResult = ref<InvoiceDuplicateCandidateListData | null>(null)
const duplicateCandidateLoading = ref(false)
const duplicateCandidateErrorMessage = ref('')
const duplicateCandidateErrorTraceId = ref('')
const duplicateCandidateCurrentPage = ref(1)
const duplicateCandidateRequestedPage = ref(1)
const duplicateCandidateRequestedCursor = ref<string | undefined>()
const duplicateCandidateCursorStack = ref<Array<string | undefined>>([undefined])
const duplicatePairResult = ref<InvoiceExactDuplicatePairData | null>(null)
const duplicatePairLoading = ref(false)
const duplicatePairErrorMessage = ref('')
const duplicatePairErrorTraceId = ref('')
const duplicatePairRequestedCandidateId = ref('')
let requestController: AbortController | null = null
let duplicateCandidateRequestController: AbortController | null = null
let duplicatePairRequestController: AbortController | null = null

const tabs = computed(() => [
  { id: 'fields', label: '发票字段' },
  { id: 'items', label: '明细', count: invoice.value?.items.length ?? 0 },
])

const invoiceId = computed(() =>
  typeof route.params.invoiceId === 'string' ? route.params.invoiceId : '',
)
const pageTitle = computed(() => {
  if (!invoice.value) return '发票详情'
  return [invoice.value.invoiceType, invoice.value.invoiceNumber].filter(Boolean).join(' · ') || '发票详情'
})
const duplicateCandidateIds = computed(
  () => duplicateCandidateResult.value?.items.map((item) => item.id) ?? [],
)

const duplicateCandidateBasisLabels: Readonly<
  Record<InvoiceDuplicateCandidateBasisStatus, string>
> = {
  ready: '身份字段完整，已执行精确等值查询',
  incomplete_identity: '身份字段不完整，未执行候选查询',
  source_voided: '源发票已作废，未执行候选查询',
}

function unavailable(value: string | null): string {
  return value || '—'
}

function exactIdentityValue(value: string): string {
  if (value === '') return '""（空字符串）'
  const escaped = Array.from(JSON.stringify(value), (character) => {
    if (!/^\s$/u.test(character)) return character
    const codePoint = character.codePointAt(0)!
    return codePoint <= 0xffff
      ? `\\u${codePoint.toString(16).padStart(4, '0')}`
      : `\\u{${codePoint.toString(16)}}`
  }).join('')
  return /^\s+$/u.test(value) ? `${escaped}（纯空白，${value.length} 个字符）` : escaped
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取此发票。'
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '发票不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '发票详情加载失败，请稍后重试。'
  }
}

function formatDuplicateCandidateError(error: unknown): void {
  duplicateCandidateErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 401) {
    duplicateCandidateErrorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 403) {
    duplicateCandidateErrorMessage.value = '当前账号无权读取此发票的精确重复候选。'
  } else if (error instanceof ApiError && error.status === 404) {
    duplicateCandidateErrorMessage.value = '发票不存在，或当前账号无权访问其精确重复候选。'
  } else {
    duplicateCandidateErrorMessage.value = '精确重复候选加载失败，请稍后重试。'
  }
}

function formatDuplicatePairError(error: unknown): void {
  duplicatePairErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 401) {
    duplicatePairErrorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 403) {
    duplicatePairErrorMessage.value = '当前账号无权核对这组精确重复发票。'
  } else if (error instanceof ApiError && error.status === 404) {
    duplicatePairErrorMessage.value = '这组发票已不存在、不可访问或不再构成精确重复候选。'
  } else {
    duplicatePairErrorMessage.value = '精确重复对比加载失败，请稍后重试。'
  }
}

function resetDuplicatePair(): void {
  duplicatePairRequestController?.abort()
  duplicatePairRequestController = null
  duplicatePairResult.value = null
  duplicatePairLoading.value = false
  duplicatePairErrorMessage.value = ''
  duplicatePairErrorTraceId.value = ''
  duplicatePairRequestedCandidateId.value = ''
}

function resetDuplicateCandidates(): void {
  resetDuplicatePair()
  duplicateCandidateRequestController?.abort()
  duplicateCandidateRequestController = null
  duplicateCandidateResult.value = null
  duplicateCandidateLoading.value = false
  duplicateCandidateErrorMessage.value = ''
  duplicateCandidateErrorTraceId.value = ''
  duplicateCandidateCurrentPage.value = 1
  duplicateCandidateRequestedPage.value = 1
  duplicateCandidateRequestedCursor.value = undefined
  duplicateCandidateCursorStack.value = [undefined]
}

async function loadDuplicateCandidatePage(
  targetInvoiceId: string,
  cursor: string | undefined,
  page: number,
): Promise<void> {
  resetDuplicatePair()
  duplicateCandidateRequestController?.abort()
  duplicateCandidateRequestController = null
  duplicateCandidateRequestedCursor.value = cursor
  duplicateCandidateRequestedPage.value = page
  duplicateCandidateResult.value = null
  duplicateCandidateErrorMessage.value = ''
  duplicateCandidateErrorTraceId.value = ''
  duplicateCandidateLoading.value = false

  if (!UUID_PATTERN.test(targetInvoiceId) || invoice.value?.id !== targetInvoiceId) return

  const controller = new AbortController()
  duplicateCandidateRequestController = controller
  duplicateCandidateLoading.value = true
  try {
    const response = await invoiceApi.listDuplicateCandidates(
      targetInvoiceId,
      duplicateCandidatePageSize,
      cursor,
      controller.signal,
    )
    if (
      duplicateCandidateRequestController === controller &&
      !controller.signal.aborted &&
      invoiceId.value === targetInvoiceId &&
      invoice.value?.id === targetInvoiceId
    ) {
      duplicateCandidateResult.value = response
      duplicateCandidateCurrentPage.value = page
    }
  } catch (error) {
    if (
      duplicateCandidateRequestController === controller &&
      !controller.signal.aborted &&
      invoiceId.value === targetInvoiceId &&
      invoice.value?.id === targetInvoiceId
    ) {
      formatDuplicateCandidateError(error)
    }
  } finally {
    if (duplicateCandidateRequestController === controller) {
      duplicateCandidateRequestController = null
      duplicateCandidateLoading.value = false
    }
  }
}

async function loadExactDuplicatePair(candidateId: string): Promise<void> {
  duplicatePairRequestController?.abort()
  duplicatePairRequestController = null
  duplicatePairResult.value = null
  duplicatePairErrorMessage.value = ''
  duplicatePairErrorTraceId.value = ''
  duplicatePairLoading.value = false
  duplicatePairRequestedCandidateId.value = candidateId

  const targetInvoiceId = invoice.value?.id ?? ''
  if (
    !UUID_PATTERN.test(targetInvoiceId) ||
    !UUID_PATTERN.test(candidateId) ||
    candidateId === targetInvoiceId ||
    !duplicateCandidateResult.value?.items.some((item) => item.id === candidateId)
  ) {
    return
  }

  const controller = new AbortController()
  duplicatePairRequestController = controller
  duplicatePairLoading.value = true
  try {
    const response = await invoiceApi.getExactDuplicatePair(
      targetInvoiceId,
      candidateId,
      controller.signal,
    )
    if (
      duplicatePairRequestController === controller &&
      !controller.signal.aborted &&
      invoiceId.value === targetInvoiceId &&
      invoice.value?.id === targetInvoiceId &&
      duplicatePairRequestedCandidateId.value === candidateId &&
      duplicateCandidateResult.value?.items.some((item) => item.id === candidateId)
    ) {
      duplicatePairResult.value = response
    }
  } catch (error) {
    if (
      duplicatePairRequestController === controller &&
      !controller.signal.aborted &&
      invoiceId.value === targetInvoiceId &&
      invoice.value?.id === targetInvoiceId &&
      duplicatePairRequestedCandidateId.value === candidateId
    ) {
      formatDuplicatePairError(error)
    }
  } finally {
    if (duplicatePairRequestController === controller) {
      duplicatePairRequestController = null
      duplicatePairLoading.value = false
    }
  }
}

function retryExactDuplicatePair(): void {
  if (!duplicatePairRequestedCandidateId.value) return
  void loadExactDuplicatePair(duplicatePairRequestedCandidateId.value)
}

function retryDuplicateCandidatePage(): void {
  if (!invoice.value) return
  void loadDuplicateCandidatePage(
    invoice.value.id,
    duplicateCandidateRequestedCursor.value,
    duplicateCandidateRequestedPage.value,
  )
}

function loadNextDuplicateCandidatePage(): void {
  if (!invoice.value || !duplicateCandidateResult.value?.nextCursor) return
  const cursor = duplicateCandidateResult.value.nextCursor
  duplicateCandidateCursorStack.value = [
    ...duplicateCandidateCursorStack.value.slice(0, duplicateCandidateCurrentPage.value),
    cursor,
  ]
  void loadDuplicateCandidatePage(
    invoice.value.id,
    cursor,
    duplicateCandidateCurrentPage.value + 1,
  )
}

function loadPreviousDuplicateCandidatePage(): void {
  if (!invoice.value || duplicateCandidateCurrentPage.value <= 1) return
  const targetPage = duplicateCandidateCurrentPage.value - 1
  duplicateCandidateCursorStack.value = duplicateCandidateCursorStack.value.slice(0, targetPage)
  void loadDuplicateCandidatePage(
    invoice.value.id,
    duplicateCandidateCursorStack.value[targetPage - 1],
    targetPage,
  )
}

function applyMutation(result: InvoiceMutationData): void {
  if (invoice.value?.id !== result.invoice.id) return
  invoice.value = result.invoice
  resetDuplicateCandidates()
  void loadDuplicateCandidatePage(result.invoice.id, undefined, 1)
}

async function loadInvoice(): Promise<void> {
  requestController?.abort()
  requestController = null
  resetDuplicateCandidates()
  invoice.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  loading.value = false

  const targetInvoiceId = invoiceId.value
  if (!UUID_PATTERN.test(targetInvoiceId)) {
    errorMessage.value = '发票标识无效，未向服务器发送请求。'
    return
  }

  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await invoiceApi.getDetail(targetInvoiceId, controller.signal)
    if (
      requestController === controller &&
      !controller.signal.aborted &&
      invoiceId.value === targetInvoiceId
    ) {
      invoice.value = response
      void loadDuplicateCandidatePage(targetInvoiceId, undefined, 1)
    }
  } catch (error) {
    if (!controller.signal.aborted) formatError(error)
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

watch(invoiceId, loadInvoice, { immediate: true })
onUnmounted(() => {
  requestController?.abort()
  duplicateCandidateRequestController?.abort()
  duplicatePairRequestController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-007"
      :title="pageTitle"
      :description="invoice ? `${invoice.invoiceCode || '无发票代码'} · ${invoice.id}` : '发票字段与明细只读视图'"
      :status="invoice?.duplicateStatus || ''"
    >
      <template v-if="invoice" #meta>
        <span><strong>销售方：</strong>{{ unavailable(invoice.sellerName) }}</span>
        <span><strong>开票日期：</strong>{{ unavailable(invoice.invoiceDate) }}</span>
        <span><strong>数据版本：</strong>{{ invoice.rowVersion }}</span>
      </template>
      <template #actions>
        <RouterLink
          v-if="invoice && canCorrectSuppliers && invoice.confirmationStatus === 'confirmed'"
          class="button button-secondary"
          data-testid="resolve-invoice-supplier"
          :to="{ name: 'suppliers', query: { source_type: 'invoice', source_id: invoice.id, row_version: invoice.rowVersion } }"
        >
          处理销售方供应商
        </RouterLink>
        <RouterLink
          v-if="invoice"
          class="button button-primary"
          :to="{ name: 'contract-invoice-links', params: { invoiceId: invoice.id } }"
        >
          查看当前主合同
        </RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">
      正在加载发票详情…
    </div>

    <SectionCard v-else-if="errorMessage" title="无法显示发票详情">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-invoice" @click="loadInvoice">重试</button>
      </div>
    </SectionCard>

    <template v-else-if="invoice">
      <SectionCard title="发票状态" description="确认状态、重复状态和发票业务状态分别展示。">
        <div class="inline-actions">
          <InvoiceStatuses
            :confirmation-status="invoice.confirmationStatus"
            :duplicate-status="invoice.duplicateStatus"
          />
          <StatusTag :status="invoice.status" />
        </div>
      </SectionCard>

      <SectionCard
        title="发票事实"
        description="金额按 API 返回的十进制字符串展示，前端不重新汇总或推导。"
        compact
      >
        <PageTabs v-model="activeTab" :items="tabs" label="发票详情标签" />

        <div v-if="activeTab === 'fields'" id="fields-panel" class="tab-panel page-stack" role="tabpanel" aria-labelledby="fields-tab">
          <div class="field-grid">
            <div class="field-item"><span class="field-label">发票代码</span><strong class="field-value mono-text">{{ unavailable(invoice.invoiceCode) }}</strong></div>
            <div class="field-item"><span class="field-label">发票号码</span><strong class="field-value mono-text">{{ unavailable(invoice.invoiceNumber) }}</strong></div>
            <div class="field-item"><span class="field-label">发票类型</span><strong class="field-value">{{ unavailable(invoice.invoiceType) }}</strong></div>
            <div class="field-item"><span class="field-label">是否红字</span><strong class="field-value">{{ invoice.isRedInvoice === null ? '未识别' : invoice.isRedInvoice ? '是' : '否' }}</strong></div>
            <div class="field-item"><span class="field-label">开票日期</span><strong class="field-value numeric-text">{{ unavailable(invoice.invoiceDate) }}</strong></div>
            <div class="field-item"><span class="field-label">购买方</span><strong class="field-value">{{ unavailable(invoice.buyerName) }}</strong><span class="field-evidence">税务身份：{{ unavailable(invoice.buyerTaxNo) }}</span></div>
            <div class="field-item"><span class="field-label">销售方</span><strong class="field-value">{{ unavailable(invoice.sellerName) }}</strong><span class="field-evidence">税务身份：{{ unavailable(invoice.sellerTaxNo) }}</span></div>
            <div class="field-item"><span class="field-label">不含税金额</span><strong class="field-value numeric-text"><DecimalAmount :amount="invoice.amountExcludingTax" /> {{ invoice.currency }}</strong></div>
            <div class="field-item"><span class="field-label">税额</span><strong class="field-value numeric-text"><DecimalAmount :amount="invoice.taxAmount" /> {{ invoice.currency }}</strong></div>
            <div class="field-item"><span class="field-label">价税合计</span><strong class="field-value numeric-text"><DecimalAmount :amount="invoice.totalAmount" /> {{ invoice.currency }}</strong></div>
            <div class="field-item"><span class="field-label">币种</span><strong class="field-value">{{ invoice.currency }}</strong></div>
          </div>
        </div>

        <div v-else id="items-panel" class="tab-panel page-stack" role="tabpanel" aria-labelledby="items-tab">
          <div v-if="invoice.items.length" class="data-table-wrap">
            <table class="data-table">
              <thead>
                <tr><th>行号</th><th>项目</th><th>规格 / 单位</th><th>数量</th><th>单价</th><th>不含税金额</th><th>税率（比例）</th><th>税额</th><th>价税合计</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in invoice.items" :key="item.id">
                  <td>{{ item.lineNo }}</td>
                  <td>{{ unavailable(item.itemName) }}</td>
                  <td>{{ unavailable(item.specification) }} / {{ unavailable(item.unit) }}</td>
                  <td class="numeric-text"><DecimalAmount :amount="item.quantity" /></td>
                  <td class="numeric-text"><DecimalAmount :amount="item.unitPrice" /></td>
                  <td class="numeric-text"><DecimalAmount :amount="item.amountExcludingTax" /></td>
                  <td class="numeric-text"><DecimalAmount :amount="item.taxRate" /></td>
                  <td class="numeric-text"><DecimalAmount :amount="item.taxAmount" /></td>
                  <td class="numeric-text"><DecimalAmount :amount="item.totalAmount" /></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="empty-inline">当前发票没有明细。</p>
        </div>
      </SectionCard>

      <div v-if="duplicateCandidateLoading" class="section-card" role="status" aria-live="polite">
        正在加载精确重复候选…
      </div>

      <SectionCard v-else-if="duplicateCandidateErrorMessage" title="无法显示精确重复候选">
        <div class="callout callout-danger" role="alert">
          <div>
            <strong>{{ duplicateCandidateErrorMessage }}</strong>
            <span v-if="duplicateCandidateErrorTraceId" class="mono-text"> Trace ID：{{ duplicateCandidateErrorTraceId }}</span>
          </div>
        </div>
        <div class="form-actions">
          <button class="button button-primary" type="button" data-testid="retry-invoice-duplicate-candidates" @click="retryDuplicateCandidatePage">重试</button>
        </div>
      </SectionCard>

      <SectionCard
        v-else-if="duplicateCandidateResult"
        title="精确重复候选"
        description="只比较当前持久化的发票代码、发票号码和销售方税号；不执行清理、模糊匹配、外部查验或自动处置。"
        compact
      >
        <div class="callout callout-warning" role="note">
          <div><strong>检测基准：</strong>{{ duplicateCandidateBasisLabels[duplicateCandidateResult.basisStatus] }}</div>
        </div>

        <template v-if="duplicateCandidateResult.basisStatus === 'ready'">
          <div v-if="duplicateCandidateResult.items.length" class="data-table-wrap">
            <table class="data-table">
              <thead>
                <tr><th>候选发票</th><th>销售方</th><th>价税合计</th><th>确认 / 重复 / 业务状态</th><th>开票日期</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="candidate in duplicateCandidateResult.items" :key="candidate.id">
                  <td>
                    <span class="table-primary">
                      <strong>{{ unavailable(candidate.invoiceNumber) }}</strong>
                      <span class="mono-text">{{ unavailable(candidate.invoiceCode) }}</span>
                      <span class="mono-text">{{ candidate.id }}</span>
                    </span>
                  </td>
                  <td>{{ unavailable(candidate.sellerName) }}</td>
                  <td class="numeric-text"><DecimalAmount :amount="candidate.totalAmount" /> {{ candidate.currency }}</td>
                  <td>
                    <div class="inline-actions">
                      <InvoiceStatuses :confirmation-status="candidate.confirmationStatus" :duplicate-status="candidate.duplicateStatus" />
                      <StatusTag :status="candidate.status" />
                    </div>
                  </td>
                  <td class="numeric-text">{{ unavailable(candidate.invoiceDate) }}</td>
                  <td>
                    <div class="inline-actions">
                      <RouterLink class="button button-secondary button-small" :to="{ name: 'invoice-detail', params: { invoiceId: candidate.id } }">查看</RouterLink>
                      <button
                        class="button button-secondary button-small"
                        type="button"
                        :data-testid="`compare-invoice-duplicate-${candidate.id}`"
                        :disabled="duplicatePairLoading && duplicatePairRequestedCandidateId === candidate.id"
                        @click="loadExactDuplicatePair(candidate.id)"
                      >
                        对比
                      </button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-inline">本次数据库读取未发现精确重复候选；这不等同于税务唯一性、外部真伪或人工确认结论。</div>
          <div class="pager">
            <span>第 {{ duplicateCandidateCurrentPage }} 页 · 每页 {{ duplicateCandidateResult.pageSize }} 条</span>
            <div class="pager-buttons">
              <button type="button" aria-label="重复候选上一页" :disabled="duplicateCandidateCurrentPage <= 1 || duplicateCandidateLoading" @click="loadPreviousDuplicateCandidatePage">‹</button>
              <button type="button" aria-current="page" disabled>{{ duplicateCandidateCurrentPage }}</button>
              <button type="button" aria-label="重复候选下一页" :disabled="!duplicateCandidateResult.nextCursor || duplicateCandidateLoading" @click="loadNextDuplicateCandidatePage">›</button>
            </div>
          </div>
        </template>

      </SectionCard>

      <div v-if="duplicatePairLoading" class="section-card" role="status" aria-live="polite">
        正在核对精确重复发票对…
      </div>

      <SectionCard v-else-if="duplicatePairErrorMessage" title="无法显示精确重复对比">
        <div class="callout callout-danger" role="alert">
          <div>
            <strong>{{ duplicatePairErrorMessage }}</strong>
            <span v-if="duplicatePairErrorTraceId" class="mono-text"> Trace ID：{{ duplicatePairErrorTraceId }}</span>
          </div>
        </div>
        <div class="form-actions">
          <button class="button button-primary" type="button" data-testid="retry-invoice-duplicate-pair" @click="retryExactDuplicatePair">重试</button>
        </div>
      </SectionCard>

      <SectionCard
        v-else-if="duplicatePairResult"
        title="精确重复对比"
        description="只展示后端在同一条数据库语句中重新核对通过的当前摘要与共同身份三元组。"
        compact
      >
        <div class="callout callout-warning" role="note">
          <div>本次 200 只证明这两个对象在该次数据库读取中仍精确匹配，不代表税务真伪、人工确认或重复状态已更新。</div>
        </div>
        <div class="field-grid">
          <div class="field-item"><span class="field-label">共同发票代码</span><strong class="field-value mono-text">{{ exactIdentityValue(duplicatePairResult.exactIdentity.invoiceCode) }}</strong></div>
          <div class="field-item"><span class="field-label">共同发票号码</span><strong class="field-value mono-text">{{ exactIdentityValue(duplicatePairResult.exactIdentity.invoiceNumber) }}</strong></div>
          <div class="field-item"><span class="field-label">共同销售方税号</span><strong class="field-value mono-text">{{ exactIdentityValue(duplicatePairResult.exactIdentity.sellerTaxNo) }}</strong></div>
        </div>
        <div class="data-table-wrap">
          <table class="data-table">
            <thead>
              <tr><th>对象</th><th>发票摘要</th><th>销售方</th><th>价税合计</th><th>确认 / 重复 / 业务状态</th><th>开票日期</th></tr>
            </thead>
            <tbody>
              <tr v-for="(item, label) in { source: duplicatePairResult.source, candidate: duplicatePairResult.candidate }" :key="item.id">
                <td>{{ label === 'source' ? '当前发票' : '候选发票' }}</td>
                <td><span class="table-primary"><strong>{{ item.invoiceNumber }}</strong><span class="mono-text">{{ item.invoiceCode }}</span><span class="mono-text">{{ item.id }}</span></span></td>
                <td>{{ unavailable(item.sellerName) }}</td>
                <td class="numeric-text"><DecimalAmount :amount="item.totalAmount" /> {{ item.currency }}</td>
                <td><div class="inline-actions"><InvoiceStatuses :confirmation-status="item.confirmationStatus" :duplicate-status="item.duplicateStatus" /><StatusTag :status="item.status" /></div></td>
                <td class="numeric-text">{{ unavailable(item.invoiceDate) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </SectionCard>

      <InvoiceManagementPanel
        :invoice="invoice"
        :duplicate-candidate-ids="duplicateCandidateIds"
        @updated="applyMutation"
        @refresh-requested="loadInvoice"
      />

      <SectionCard title="当前基线边界">
        <div class="callout callout-warning">
          <div>
            发票证据、完整事实修正、确认/拒绝、重复检测与处置、修正历史及合同关联已接入；销售方供应商入口也已接通。外部税务真伪核验和供应商高级合并、拆分、别名治理不属于当前 P0。
          </div>
        </div>
      </SectionCard>
    </template>
  </section>
</template>
