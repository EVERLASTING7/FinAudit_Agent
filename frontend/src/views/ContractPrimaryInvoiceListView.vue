<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import DecimalAmount from '@/components/DecimalAmount.vue'
import InvoiceStatuses from '@/components/InvoiceStatuses.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  contractPrimaryInvoiceApi,
  type ContractPrimaryInvoiceListData,
} from '@/services/contractPrimaryInvoices'

const route = useRoute()
const pageSize = 20
const result = ref<ContractPrimaryInvoiceListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
let requestController: AbortController | null = null

const contractId = computed(() =>
  typeof route.params.contractId === 'string' ? route.params.contractId : '',
)

function unavailable(value: string | null): string {
  return value || '—'
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取此合同的当前主合同发票。'
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '合同不存在，或当前账号无权访问。'
  } else {
    errorMessage.value = '当前主合同发票加载失败，请稍后重试。'
  }
}

async function loadPage(
  targetContractId: string,
  cursor: string | undefined,
  page: number,
): Promise<void> {
  requestController?.abort()
  requestController = null
  requestedCursor.value = cursor
  requestedPage.value = page
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  loading.value = false

  if (!UUID_PATTERN.test(targetContractId)) {
    errorMessage.value = '合同标识无效，未向服务器发送请求。'
    return
  }

  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await contractPrimaryInvoiceApi.list(
      targetContractId,
      pageSize,
      cursor,
      controller.signal,
    )
    if (
      requestController === controller &&
      !controller.signal.aborted &&
      contractId.value === targetContractId
    ) {
      result.value = response
      currentPage.value = page
    }
  } catch (error) {
    if (
      requestController === controller &&
      !controller.signal.aborted &&
      contractId.value === targetContractId
    ) {
      formatError(error)
    }
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

function resetAndLoad(): void {
  currentPage.value = 1
  requestedPage.value = 1
  requestedCursor.value = undefined
  cursorStack.value = [undefined]
  void loadPage(contractId.value, undefined, 1)
}

function retryPage(): void {
  void loadPage(contractId.value, requestedCursor.value, requestedPage.value)
}

function loadNextPage(): void {
  if (!result.value?.nextCursor) return
  const cursor = result.value.nextCursor
  cursorStack.value = [...cursorStack.value.slice(0, currentPage.value), cursor]
  void loadPage(contractId.value, cursor, currentPage.value + 1)
}

function loadPreviousPage(): void {
  if (currentPage.value <= 1) return
  const targetPage = currentPage.value - 1
  cursorStack.value = cursorStack.value.slice(0, targetPage)
  void loadPage(contractId.value, cursorStack.value[targetPage - 1], targetPage)
}

watch(contractId, resetAndLoad, { immediate: true })
onUnmounted(() => requestController?.abort())
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-005"
      title="合同当前主合同发票"
      :description="`合同 ${contractId} 当前作为已确认主合同的发票只读列表；UUID 顺序不代表业务时间。`"
    >
      <template #actions>
        <RouterLink
          v-if="UUID_PATTERN.test(contractId)"
          class="button button-secondary"
          :to="{ name: 'contract-detail', params: { contractId } }"
        >
          返回合同详情
        </RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载当前主合同发票…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示当前主合同发票">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-contract-primary-invoices" @click="retryPage">重试</button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="当前主合同发票"
      description="仅展示当前确认关系；不包含候选、匹配依据、取消历史或关联写能力。"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>发票</th><th>销售方</th><th>价税合计</th><th>确认 / 重复 / 业务状态</th><th>开票日期</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="invoice in result.items" :key="invoice.id">
              <td>
                <span class="table-primary">
                  <strong>{{ unavailable(invoice.invoiceNumber) }}</strong>
                  <span class="mono-text">{{ unavailable(invoice.invoiceCode) }}</span>
                  <span class="mono-text">{{ invoice.id }}</span>
                </span>
              </td>
              <td>{{ unavailable(invoice.sellerName) }}</td>
              <td class="numeric-text"><DecimalAmount :amount="invoice.totalAmount" /> {{ invoice.currency }}</td>
              <td>
                <div class="inline-actions">
                  <InvoiceStatuses :confirmation-status="invoice.confirmationStatus" :duplicate-status="invoice.duplicateStatus" />
                  <StatusTag :status="invoice.status" />
                </div>
              </td>
              <td class="numeric-text">{{ unavailable(invoice.invoiceDate) }}</td>
              <td>
                <RouterLink class="button button-secondary button-small" :to="{ name: 'invoice-detail', params: { invoiceId: invoice.id } }">查看</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前合同没有作为已确认主合同的发票。</div>
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
