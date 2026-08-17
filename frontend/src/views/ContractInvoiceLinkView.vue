<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import ContractStatuses from '@/components/ContractStatuses.vue'
import DecimalAmount from '@/components/DecimalAmount.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  invoicePrimaryContractApi,
  type ContractInvoiceCandidateListData,
  type ContractInvoiceHistoryData,
  type ContractInvoiceLink,
  type ContractInvoiceMatchReasons,
  type InvoicePrimaryContractData,
  type MatchEvidenceStatus,
} from '@/services/invoicePrimaryContract'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const primary = ref<InvoicePrimaryContractData | null>(null)
const candidates = ref<ContractInvoiceCandidateListData | null>(null)
const history = ref<ContractInvoiceHistoryData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const reason = ref('')
const writing = ref(false)
const writeErrorMessage = ref('')
const writeErrorTraceId = ref('')
const writeSuccessMessage = ref('')
let requestController: AbortController | null = null
let writeController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const invoiceId = computed(() =>
  typeof route.params.invoiceId === 'string' ? route.params.invoiceId : '',
)
const currentPrimaryRelation = computed(
  () => history.value?.items.find((item) => item.status === 'confirmed_primary') ?? null,
)
const suggestedRelations = computed(
  () => history.value?.items.filter((item) => item.status === 'suggested') ?? [],
)
const canSuggest = computed(() => auth.hasAllPermissions(['links.suggest']))
const canManagePrimary = computed(() => auth.hasAllPermissions(['links.manage_primary']))
const validReason = computed(() => {
  const value = reason.value.trim()
  return value.length >= 1 && value.length <= 1000 && value === reason.value
})

const matchStatusLabels: Readonly<Record<MatchEvidenceStatus, string>> = {
  matched: '匹配',
  mismatched: '不匹配',
  unavailable: '无可用字段',
}

function unavailable(value: string | null): string {
  return value || '—'
}

function formatDate(value: string | null): string {
  if (value === null) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}

function candidateName(contractId: string): string {
  const item = candidates.value?.items.find((candidate) => candidate.contract.id === contractId)
  if (item) return `${item.contract.contractNo ?? '无编号'} · ${item.contract.name}`
  if (primary.value?.primaryContract?.id === contractId) {
    return `${primary.value.primaryContract.contractNo ?? '无编号'} · ${primary.value.primaryContract.name}`
  }
  return contractId
}

function matchReasonSummary(reasons: ContractInvoiceMatchReasons): string {
  return [
    `税号：${matchStatusLabels[reasons.taxNo.status]}`,
    `名称：${matchStatusLabels[reasons.name.status]}`,
    `日期：${matchStatusLabels[reasons.date.status]}`,
  ].join('；')
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取此发票的主合同。'
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '发票不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '主合同加载失败，请稍后重试。'
  }
}

function formatWriteError(error: unknown): void {
  writeErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) {
    writeErrorMessage.value = '合同关联操作失败，请稍后重试。'
    return
  }
  if (error.status === 409) {
    writeErrorMessage.value = '发票或关系版本已变化，或当前状态不允许此操作。请刷新后核对最新状态。'
  } else if (error.status === 403) {
    writeErrorMessage.value = '当前账号无权执行此合同关联操作。'
  } else if (error.status === 404) {
    writeErrorMessage.value = '目标发票、合同或关系已不可见。'
  } else if (error.status === 422) {
    writeErrorMessage.value = '关联请求不符合约束，请检查原因和目标关系。'
  } else {
    writeErrorMessage.value = '合同关联操作失败，请稍后重试。'
  }
}

async function loadData(): Promise<void> {
  requestController?.abort()
  requestController = null
  primary.value = null
  candidates.value = null
  history.value = null
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
    const [primaryResponse, candidateResponse, historyResponse] = await Promise.all([
      invoicePrimaryContractApi.get(targetInvoiceId, controller.signal),
      invoicePrimaryContractApi.listCandidates(targetInvoiceId, controller.signal),
      invoicePrimaryContractApi.getHistory(targetInvoiceId, controller.signal),
    ])
    if (
      requestController === controller &&
      !controller.signal.aborted &&
      invoiceId.value === targetInvoiceId
    ) {
      primary.value = primaryResponse
      candidates.value = candidateResponse
      history.value = historyResponse
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

function idempotencyKey(signature: string): string {
  if (pendingSignature !== signature) {
    pendingSignature = signature
    pendingIdempotencyKey = `contract-link.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

function resetWriteFeedback(): void {
  writeErrorMessage.value = ''
  writeErrorTraceId.value = ''
  writeSuccessMessage.value = ''
}

async function runWrite(
  signature: string,
  operation: (key: string, signal: AbortSignal) => Promise<unknown>,
  successMessage: string,
): Promise<void> {
  if (!validReason.value || writing.value) return
  resetWriteFeedback()
  const controller = new AbortController()
  writeController = controller
  writing.value = true
  try {
    await operation(idempotencyKey(signature), controller.signal)
    if (writeController !== controller || controller.signal.aborted) return
    writeSuccessMessage.value = successMessage
    reason.value = ''
    pendingSignature = ''
    pendingIdempotencyKey = ''
    await loadData()
  } catch (error) {
    if (writeController === controller && !controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) {
      writeController = null
      writing.value = false
    }
  }
}

function suggest(contractId: string): void {
  if (!canSuggest.value || !candidates.value) return
  const input = {
    contractId,
    invoiceRowVersion: candidates.value.invoiceRowVersion,
    reason: reason.value,
  }
  const signature = `suggest:${contractId}:${input.invoiceRowVersion}:${input.reason}`
  void runWrite(
    signature,
    (key, signal) => invoicePrimaryContractApi.suggest(invoiceId.value, input, key, signal),
    '合同建议已创建。',
  )
}

function setPrimary(relation: ContractInvoiceLink): void {
  if (!canManagePrimary.value || !candidates.value) return
  const input = {
    suggestionId: relation.id,
    invoiceRowVersion: candidates.value.invoiceRowVersion,
    relationRowVersion: relation.rowVersion,
    reason: reason.value,
  }
  const signature = `primary:${relation.id}:${input.invoiceRowVersion}:${input.relationRowVersion}:${input.reason}`
  void runWrite(
    signature,
    (key, signal) => invoicePrimaryContractApi.setPrimary(invoiceId.value, input, key, signal),
    currentPrimaryRelation.value ? '主合同已替换。' : '主合同已确认。',
  )
}

function cancelPrimary(): void {
  const relation = currentPrimaryRelation.value
  if (!canManagePrimary.value || !candidates.value || !relation) return
  const input = {
    invoiceRowVersion: candidates.value.invoiceRowVersion,
    relationRowVersion: relation.rowVersion,
    reason: reason.value,
  }
  const signature = `cancel:${relation.id}:${input.invoiceRowVersion}:${input.relationRowVersion}:${input.reason}`
  void runWrite(
    signature,
    (key, signal) => invoicePrimaryContractApi.cancelPrimary(invoiceId.value, input, key, signal),
    '当前主合同已取消。',
  )
}

watch(invoiceId, () => {
  writeController?.abort()
  resetWriteFeedback()
  reason.value = ''
  pendingSignature = ''
  pendingIdempotencyKey = ''
  void loadData()
}, { immediate: true })
onUnmounted(() => {
  requestController?.abort()
  writeController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-008"
      title="发票主合同关联"
      :description="`发票 ${invoiceId} 的候选、当前主合同和版本化历史。`"
      :status="currentPrimaryRelation ? 'confirmed_primary' : ''"
    >
      <template #actions>
        <RouterLink
          v-if="UUID_PATTERN.test(invoiceId)"
          class="button button-secondary"
          :to="{ name: 'invoice-detail', params: { invoiceId } }"
        >
          返回发票详情
        </RouterLink>
        <button
          v-if="currentPrimaryRelation && canManagePrimary"
          class="button button-danger"
          type="button"
          :disabled="writing || !validReason"
          data-testid="cancel-primary-contract"
          @click="cancelPrimary"
        >
          取消当前主合同
        </button>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">
      正在加载发票主合同…
    </div>

    <SectionCard v-else-if="errorMessage" title="无法显示合同关联">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-primary-contract" @click="loadData">重试</button>
      </div>
    </SectionCard>

    <template v-else-if="primary && candidates && history">
      <SectionCard title="关联操作原因" description="所有建议、确认、替换和取消都会记录原因、Actor、Trace 与前后版本。">
        <div class="form-field">
          <label for="contract-link-reason">操作原因</label>
          <textarea
            id="contract-link-reason"
            v-model="reason"
            rows="3"
            maxlength="1000"
            :disabled="writing"
            placeholder="填写本次人工判断依据"
            @input="resetWriteFeedback"
          />
          <span class="form-help">原因必须去除首尾空白，且不能为空。</span>
        </div>
        <div v-if="writeErrorMessage" class="callout callout-danger" role="alert" style="margin-top: 14px">
          <div><strong>{{ writeErrorMessage }}</strong><span v-if="writeErrorTraceId" class="mono-text"> Trace ID：{{ writeErrorTraceId }}</span></div>
        </div>
        <div v-if="writeSuccessMessage" class="callout callout-success" role="status" style="margin-top: 14px">
          <div><strong>{{ writeSuccessMessage }}</strong>已重新读取当前候选、主合同和历史。</div>
        </div>
      </SectionCard>

      <SectionCard
        v-if="primary.primaryContract"
        title="当前已确认主合同"
        description="合同字段为当前持久化投影；关系行版本用于并发保护。"
      >
        <div class="field-grid">
          <div class="field-item"><span class="field-label">合同编号</span><strong class="field-value mono-text">{{ unavailable(primary.primaryContract.contractNo) }}</strong></div>
          <div class="field-item"><span class="field-label">合同名称</span><strong class="field-value">{{ primary.primaryContract.name }}</strong></div>
          <div class="field-item"><span class="field-label">乙方</span><strong class="field-value">{{ unavailable(primary.primaryContract.partyBName) }}</strong></div>
          <div class="field-item"><span class="field-label">合同金额</span><strong class="field-value numeric-text"><DecimalAmount :amount="primary.primaryContract.amount" /> {{ unavailable(primary.primaryContract.currency) }}</strong></div>
          <div class="field-item"><span class="field-label">有效期</span><strong class="field-value numeric-text">{{ unavailable(primary.primaryContract.effectiveDate) }} 至 {{ unavailable(primary.primaryContract.expiryDate) }}</strong></div>
          <div class="field-item"><span class="field-label">关系版本</span><strong class="field-value mono-text">{{ currentPrimaryRelation?.rowVersion ?? '—' }}</strong></div>
        </div>
        <div class="form-actions">
          <RouterLink class="button button-secondary" :to="{ name: 'contract-detail', params: { contractId: primary.primaryContract.id } }">查看合同详情</RouterLink>
        </div>
      </SectionCard>

      <SectionCard v-else title="当前没有已确认主合同">
        <div class="empty-inline">此发票当前没有已确认主合同；这不表示发票不存在。可以先创建合同建议，再由有主合同管理权限的用户确认。</div>
      </SectionCard>

      <SectionCard title="合同候选" :description="`服务端按税号、名称、日期三个独立依据排序；发票行版本 ${candidates.invoiceRowVersion}。`" compact>
        <div v-if="candidates.items.length" class="data-table-wrap">
          <table class="data-table">
            <thead><tr><th>合同</th><th>乙方 / 金额</th><th>匹配依据</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="candidate in candidates.items" :key="candidate.contract.id">
                <td><span class="table-primary"><strong>{{ unavailable(candidate.contract.contractNo) }}</strong><span>{{ candidate.contract.name }}</span></span></td>
                <td>{{ unavailable(candidate.contract.partyBName) }}<br /><span class="numeric-text"><DecimalAmount :amount="candidate.contract.amount" /> {{ unavailable(candidate.contract.currency) }}</span></td>
                <td>{{ matchReasonSummary(candidate.matchReasons) }}</td>
                <td><ContractStatuses :confirmation-status="candidate.contract.confirmationStatus" :contract-status="candidate.contract.status" /></td>
                <td>
                  <button
                    v-if="canSuggest && !history.items.some((item) => item.contractId === candidate.contract.id && item.status !== 'cancelled')"
                    class="button button-secondary button-small"
                    type="button"
                    :disabled="writing || !validReason"
                    :data-testid="`suggest-contract-${candidate.contract.id}`"
                    @click="suggest(candidate.contract.id)"
                  >创建建议</button>
                  <span v-else class="table-secondary">已有活动关系或无建议权限</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-inline">当前没有可关联合同候选。</div>
      </SectionCard>

      <SectionCard title="待确认建议" description="确认新的建议会在同一事务中替换旧主合同，并保留取消原因与历史。" compact>
        <div v-if="suggestedRelations.length" class="data-table-wrap">
          <table class="data-table">
            <thead><tr><th>建议关系</th><th>合同</th><th>匹配依据</th><th>行版本</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="relation in suggestedRelations" :key="relation.id">
                <td class="mono-text">{{ relation.id }}</td>
                <td>{{ candidateName(relation.contractId) }}</td>
                <td>{{ matchReasonSummary(relation.matchReasons) }}</td>
                <td class="mono-text">{{ relation.rowVersion }}</td>
                <td>
                  <button
                    v-if="canManagePrimary"
                    class="button button-primary button-small"
                    type="button"
                    :disabled="writing || !validReason"
                    :data-testid="`confirm-suggestion-${relation.id}`"
                    @click="setPrimary(relation)"
                  >{{ currentPrimaryRelation ? '替换为主合同' : '确认主合同' }}</button>
                  <span v-else class="table-secondary">无主合同管理权限</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-inline">当前没有待确认建议。</div>
      </SectionCard>

      <SectionCard title="关联历史" description="历史按服务端稳定顺序展示，不在前端重建关系状态。" compact>
        <div v-if="history.items.length" class="data-table-wrap">
          <table class="data-table">
            <thead><tr><th>关系</th><th>合同</th><th>状态</th><th>建议 / 确认 / 取消</th><th>取消原因</th><th>版本</th></tr></thead>
            <tbody>
              <tr v-for="relation in history.items" :key="relation.id">
                <td class="mono-text">{{ relation.id }}</td>
                <td>{{ candidateName(relation.contractId) }}</td>
                <td><StatusTag :status="relation.status" /></td>
                <td>{{ formatDate(relation.suggestedAt) }}<br />{{ formatDate(relation.confirmedAt) }}<br />{{ formatDate(relation.cancelledAt) }}</td>
                <td>{{ relation.cancelReason ?? '—' }}</td>
                <td class="mono-text">{{ relation.rowVersion }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-inline">尚无合同关联历史。</div>
      </SectionCard>
    </template>
  </section>
</template>
