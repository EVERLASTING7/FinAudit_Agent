<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

import DecimalAmount from '@/components/DecimalAmount.vue'
import InvoiceStatuses from '@/components/InvoiceStatuses.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import {
  invoiceApi,
  type InvoiceListData,
  type InvoiceStatus,
} from '@/services/invoices'

const pageSize = 20
const result = ref<InvoiceListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
let requestController: AbortController | null = null

const invoiceStatusLabels: Readonly<Record<InvoiceStatus, string>> = {
  draft: '草稿',
  confirmed: '已确认',
  voided: '已作废',
  archived: '已归档',
}

function unavailable(value: string | null): string {
  return value || '—'
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取发票列表。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '发票列表加载失败，请稍后重试。'
  }
}

async function loadPage(
  cursor: string | undefined,
  page: number,
): Promise<void> {
  requestController?.abort()
  requestController = null
  requestedPage.value = page
  requestedCursor.value = cursor
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  loading.value = false

  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await invoiceApi.list(pageSize, cursor, controller.signal)
    if (requestController === controller && !controller.signal.aborted) {
      result.value = response
      currentPage.value = page
    }
  } catch (error) {
    if (requestController === controller && !controller.signal.aborted) {
      formatError(error)
    }
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

void loadPage(undefined, 1)
onUnmounted(() => requestController?.abort())
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-006"
      title="发票管理"
      description="查看发票确认状态和重复检测结果；重复检测不代表税务机关真伪查验。"
    >
      <template #actions>
        <RouterLink class="button button-primary" :to="{ name: 'files' }">前往文件管理</RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">
      正在加载发票列表…
    </div>

    <SectionCard v-else-if="errorMessage" title="无法显示发票列表">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-invoice-list" @click="retryPage">
          重试
        </button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="发票列表"
      :description="`当前页 ${result.items.length} 条记录；金额只按 API 十进制字符串格式化。`"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>发票</th>
              <th>开票日期</th>
              <th>销售方</th>
              <th>价税合计</th>
              <th>确认 / 重复状态</th>
              <th>发票状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="invoice in result.items" :key="invoice.id">
              <td>
                <span class="table-primary">
                  <strong>{{ unavailable(invoice.invoiceNumber) }}</strong>
                  <span>代码 {{ unavailable(invoice.invoiceCode) }}</span>
                </span>
              </td>
              <td class="numeric-text">{{ unavailable(invoice.invoiceDate) }}</td>
              <td>{{ unavailable(invoice.sellerName) }}</td>
              <td class="numeric-text"><DecimalAmount :amount="invoice.totalAmount" /> {{ invoice.currency }}</td>
              <td>
                <InvoiceStatuses
                  :confirmation-status="invoice.confirmationStatus"
                  :duplicate-status="invoice.duplicateStatus"
                />
              </td>
              <td><StatusTag :status="invoice.status" :label="invoiceStatusLabels[invoice.status]" /></td>
              <td>
                <RouterLink
                  class="button button-secondary button-small"
                  :to="{ name: 'invoice-detail', params: { invoiceId: invoice.id } }"
                >
                  查看
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前页没有发票。</div>
      <div class="pager">
        <span>第 {{ currentPage }} 页 · 每页 {{ result.pageSize }} 条</span>
        <div class="pager-buttons">
          <button
            type="button"
            aria-label="上一页"
            :disabled="currentPage <= 1 || loading"
            @click="loadPreviousPage"
          >
            ‹
          </button>
          <button type="button" aria-current="page" disabled>{{ currentPage }}</button>
          <button
            type="button"
            aria-label="下一页"
            :disabled="!result.nextCursor || loading"
            @click="loadNextPage"
          >
            ›
          </button>
        </div>
      </div>
    </SectionCard>
  </section>
</template>
