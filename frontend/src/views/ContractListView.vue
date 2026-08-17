<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

import ContractStatuses from '@/components/ContractStatuses.vue'
import DecimalAmount from '@/components/DecimalAmount.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import { ApiError } from '@/services/api'
import { contractApi, type ContractListData } from '@/services/contracts'

const pageSize = 20
const result = ref<ContractListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
let requestController: AbortController | null = null

function unavailable(value: string | null): string {
  return value || '—'
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取合同列表。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '合同列表加载失败，请稍后重试。'
  }
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  requestController?.abort()
  requestController = null
  requestedCursor.value = cursor
  requestedPage.value = page
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  loading.value = false

  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await contractApi.list(pageSize, cursor, controller.signal)
    if (requestController === controller && !controller.signal.aborted) {
      result.value = response
      currentPage.value = page
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
      ui-code="UI-004"
      title="合同管理"
      description="查看当前持久化合同事实、确认状态和有效期。"
    >
      <template #actions>
        <RouterLink class="button button-primary" :to="{ name: 'files' }">前往文件管理</RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载合同列表…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示合同列表">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-contract-list" @click="retryPage">重试</button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="合同列表"
      :description="`当前页 ${result.items.length} 条记录；金额只按 API 十进制字符串格式化。`"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>合同</th><th>乙方</th><th>合同金额</th><th>确认 / 业务状态</th><th>有效期</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="contract in result.items" :key="contract.id">
              <td>
                <span class="table-primary">
                  <strong>{{ unavailable(contract.contractNo) }}</strong>
                  <span>{{ contract.name }}</span>
                </span>
              </td>
              <td>{{ unavailable(contract.partyBName) }}</td>
              <td class="numeric-text"><DecimalAmount :amount="contract.amount" /> {{ unavailable(contract.currency) }}</td>
              <td><ContractStatuses :confirmation-status="contract.confirmationStatus" :contract-status="contract.status" /></td>
              <td class="numeric-text">{{ unavailable(contract.effectiveDate) }}<br /><span class="table-secondary">至 {{ unavailable(contract.expiryDate) }}</span></td>
              <td>
                <RouterLink class="button button-secondary button-small" :to="{ name: 'contract-detail', params: { contractId: contract.id } }">查看</RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前页没有合同。</div>
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
