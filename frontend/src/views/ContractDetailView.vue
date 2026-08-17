<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'

import ContractManagementPanel from '@/components/ContractManagementPanel.vue'
import ContractStatuses from '@/components/ContractStatuses.vue'
import DecimalAmount from '@/components/DecimalAmount.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import SupplementaryAgreementPanel from '@/components/SupplementaryAgreementPanel.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  contractApi,
  type ContractDetail,
  type ContractMutationData,
  type JsonValue,
} from '@/services/contracts'
import {
  supplementaryAgreementApi,
  type EffectiveContractData,
  type SupplementaryAgreementConfirmationStatus,
  type SupplementaryAgreementDetail,
  type SupplementaryAgreementHeaderListData,
  type SupplementaryAgreementStatus,
} from '@/services/supplementaryAgreements'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()
const agreementPageSize = 20
const contract = ref<ContractDetail | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const agreementResult = ref<SupplementaryAgreementHeaderListData | null>(null)
const agreementLoading = ref(false)
const agreementErrorMessage = ref('')
const agreementErrorTraceId = ref('')
const agreementCurrentPage = ref(1)
const agreementRequestedPage = ref(1)
const agreementRequestedCursor = ref<string | undefined>()
const agreementCursorStack = ref<Array<string | undefined>>([undefined])
const selectedAgreementId = ref('')
const baselineDate = ref('')
const effectiveResult = shallowRef<EffectiveContractData | null>(null)
const effectiveLoading = ref(false)
const effectiveErrorMessage = ref('')
const effectiveErrorTraceId = ref('')
const managementPanel = ref<{ startEditing: () => void } | null>(null)
const canCorrectSuppliers = computed(() => auth.hasAllPermissions(['suppliers.correct']))
let requestController: AbortController | null = null
let agreementRequestController: AbortController | null = null
let effectiveRequestController: AbortController | null = null

const contractId = computed(() =>
  typeof route.params.contractId === 'string' ? route.params.contractId : '',
)

function unavailable(value: string | null): string {
  return value || '—'
}

function formatJsonValue(value: JsonValue): string {
  if (value === null) return 'null'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

const agreementStatusLabels: Readonly<Record<SupplementaryAgreementStatus, string>> = {
  draft: '草稿',
  pending_confirmation: '待确认',
  confirmed: '已确认',
  rejected: '已拒绝',
  archived: '已归档',
}

const agreementConfirmationLabels: Readonly<
  Record<SupplementaryAgreementConfirmationStatus, string>
> = {
  unconfirmed: '未确认',
  confirmed: '已确认',
  rejected: '已拒绝',
}

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取此合同。'
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '合同不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '合同详情加载失败，请稍后重试。'
  }
}

function formatAgreementError(error: unknown): void {
  agreementErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 401) {
    agreementErrorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 403) {
    agreementErrorMessage.value = '当前账号无权读取补充协议原始 Header。'
  } else if (error instanceof ApiError && error.status === 404) {
    agreementErrorMessage.value = '合同不存在，或当前账号无权访问其补充协议原始 Header。'
  } else {
    agreementErrorMessage.value = '补充协议原始 Header 加载失败，请稍后重试。'
  }
}

function applyMutation(result: ContractMutationData): void {
  if (contract.value?.id !== result.contract.id) return
  contract.value = result.contract
}

function startContractEditing(): void {
  managementPanel.value?.startEditing()
  document.getElementById('contract-management')?.scrollIntoView?.({ block: 'start' })
}

function resetAgreements(): void {
  agreementRequestController?.abort()
  agreementRequestController = null
  effectiveRequestController?.abort()
  effectiveRequestController = null
  agreementResult.value = null
  agreementLoading.value = false
  agreementErrorMessage.value = ''
  agreementErrorTraceId.value = ''
  agreementCurrentPage.value = 1
  agreementRequestedPage.value = 1
  agreementRequestedCursor.value = undefined
  agreementCursorStack.value = [undefined]
  selectedAgreementId.value = ''
  baselineDate.value = ''
  effectiveResult.value = null
  effectiveLoading.value = false
  effectiveErrorMessage.value = ''
  effectiveErrorTraceId.value = ''
}

function selectAgreement(agreementId: string): void {
  selectedAgreementId.value = selectedAgreementId.value === agreementId ? '' : agreementId
}

function applyAgreementMutation(detail: SupplementaryAgreementDetail): void {
  if (agreementResult.value !== null) {
    agreementResult.value = {
      ...agreementResult.value,
      items: agreementResult.value.items.map((item) =>
        item.id === detail.id
          ? {
              id: detail.id,
              agreementNo: detail.agreementNo,
              name: detail.name,
              signedDate: detail.signedDate,
              effectiveDate: detail.effectiveDate,
              status: detail.status,
              confirmationStatus: detail.confirmationStatus,
            }
          : item,
      ),
    }
  }
  effectiveResult.value = null
  effectiveErrorMessage.value = ''
  effectiveErrorTraceId.value = ''
}

function formatEffectiveError(error: unknown): void {
  effectiveErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 401) {
    effectiveErrorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 403) {
    effectiveErrorMessage.value = '当前账号无权读取基准日期有效字段。'
  } else if (error instanceof ApiError && error.status === 404) {
    effectiveErrorMessage.value = '合同不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 409) {
    effectiveErrorMessage.value = '同一字段在同一生效日存在冲突，服务端已停止投影。'
  } else if (error instanceof TypeError) {
    effectiveErrorMessage.value = '基准日期或服务响应不符合约束。'
  } else {
    effectiveErrorMessage.value = '有效字段投影加载失败，请稍后重试。'
  }
}

function resetEffectiveResult(): void {
  effectiveRequestController?.abort()
  effectiveRequestController = null
  effectiveResult.value = null
  effectiveLoading.value = false
  effectiveErrorMessage.value = ''
  effectiveErrorTraceId.value = ''
}

async function loadEffectiveFields(): Promise<void> {
  effectiveRequestController?.abort()
  effectiveRequestController = null
  effectiveResult.value = null
  effectiveErrorMessage.value = ''
  effectiveErrorTraceId.value = ''
  if (!contract.value || baselineDate.value === '') return

  const targetContractId = contract.value.id
  const targetBaselineDate = baselineDate.value
  const controller = new AbortController()
  effectiveRequestController = controller
  effectiveLoading.value = true
  try {
    const response = await supplementaryAgreementApi.getEffectiveFields(
      targetContractId,
      targetBaselineDate,
      controller.signal,
    )
    if (
      effectiveRequestController === controller &&
      !controller.signal.aborted &&
      contract.value?.id === targetContractId &&
      baselineDate.value === targetBaselineDate
    ) {
      effectiveResult.value = response
    }
  } catch (error) {
    if (effectiveRequestController === controller && !controller.signal.aborted) {
      formatEffectiveError(error)
    }
  } finally {
    if (effectiveRequestController === controller) {
      effectiveRequestController = null
      effectiveLoading.value = false
    }
  }
}

async function loadAgreementPage(
  targetContractId: string,
  cursor: string | undefined,
  page: number,
): Promise<void> {
  agreementRequestController?.abort()
  agreementRequestController = null
  agreementRequestedCursor.value = cursor
  agreementRequestedPage.value = page
  agreementResult.value = null
  agreementErrorMessage.value = ''
  agreementErrorTraceId.value = ''
  agreementLoading.value = false

  if (!UUID_PATTERN.test(targetContractId) || contract.value?.id !== targetContractId) return

  const controller = new AbortController()
  agreementRequestController = controller
  agreementLoading.value = true
  try {
    const response = await supplementaryAgreementApi.listHeaders(
      targetContractId,
      agreementPageSize,
      cursor,
      controller.signal,
    )
    if (
      agreementRequestController === controller &&
      !controller.signal.aborted &&
      contractId.value === targetContractId &&
      contract.value?.id === targetContractId
    ) {
      agreementResult.value = response
      agreementCurrentPage.value = page
    }
  } catch (error) {
    if (
      agreementRequestController === controller &&
      !controller.signal.aborted &&
      contractId.value === targetContractId &&
      contract.value?.id === targetContractId
    ) {
      formatAgreementError(error)
    }
  } finally {
    if (agreementRequestController === controller) {
      agreementRequestController = null
      agreementLoading.value = false
    }
  }
}

function retryAgreementPage(): void {
  if (!contract.value) return
  void loadAgreementPage(
    contract.value.id,
    agreementRequestedCursor.value,
    agreementRequestedPage.value,
  )
}

function loadNextAgreementPage(): void {
  if (!contract.value || !agreementResult.value?.nextCursor) return
  const cursor = agreementResult.value.nextCursor
  agreementCursorStack.value = [
    ...agreementCursorStack.value.slice(0, agreementCurrentPage.value),
    cursor,
  ]
  void loadAgreementPage(contract.value.id, cursor, agreementCurrentPage.value + 1)
}

function loadPreviousAgreementPage(): void {
  if (!contract.value || agreementCurrentPage.value <= 1) return
  const targetPage = agreementCurrentPage.value - 1
  agreementCursorStack.value = agreementCursorStack.value.slice(0, targetPage)
  void loadAgreementPage(
    contract.value.id,
    agreementCursorStack.value[targetPage - 1],
    targetPage,
  )
}

async function loadContract(): Promise<void> {
  requestController?.abort()
  requestController = null
  resetAgreements()
  contract.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  loading.value = false

  const targetContractId = contractId.value
  if (!UUID_PATTERN.test(targetContractId)) {
    errorMessage.value = '合同标识无效，未向服务器发送请求。'
    return
  }

  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await contractApi.getDetail(targetContractId, controller.signal)
    if (
      requestController === controller &&
      !controller.signal.aborted &&
      contractId.value === targetContractId
    ) {
      contract.value = response
      void loadAgreementPage(targetContractId, undefined, 1)
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

watch(contractId, loadContract, { immediate: true })
onUnmounted(() => {
  requestController?.abort()
  agreementRequestController?.abort()
  effectiveRequestController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-005"
      :title="contract?.name || '合同详情'"
      :description="contract ? `${contract.contractNo || '合同编号待确认'} · ${contract.id}` : '合同事实、证据与人工确认视图'"
      :status="contract?.status || ''"
    >
      <template v-if="contract" #meta>
        <span><strong>乙方：</strong>{{ unavailable(contract.partyBName) }}</span>
        <span><strong>数据版本：</strong>{{ contract.rowVersion }}</span>
      </template>
      <template #actions>
        <button v-if="contract" class="button button-secondary" type="button" data-testid="open-contract-editor" @click="startContractEditing">编辑与确认</button>
        <RouterLink
          v-if="contract && canCorrectSuppliers && contract.confirmationStatus === 'confirmed'"
          class="button button-secondary"
          data-testid="resolve-contract-supplier"
          :to="{ name: 'suppliers', query: { source_type: 'contract', source_id: contract.id, row_version: contract.rowVersion } }"
        >
          处理乙方供应商
        </RouterLink>
        <RouterLink
          v-if="contract"
          class="button button-primary"
          :to="{ name: 'contract-primary-invoices', params: { contractId: contract.id } }"
        >
          查看当前主合同发票
        </RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载合同详情…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示合同详情">
      <div class="callout callout-danger" role="alert">
        <div><strong>{{ errorMessage }}</strong><span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span></div>
      </div>
      <div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-contract" @click="loadContract">重试</button></div>
    </SectionCard>

    <template v-else-if="contract">
      <SectionCard title="合同状态" description="确认状态与合同业务状态分别展示。">
        <ContractStatuses :confirmation-status="contract.confirmationStatus" :contract-status="contract.status" />
      </SectionCard>

      <SectionCard title="合同当前持久化事实" description="此处不是按审核基准日期应用补充协议后的有效字段投影。">
        <div class="field-grid">
          <div class="field-item"><span class="field-label">合同编号</span><strong class="field-value">{{ unavailable(contract.contractNo) }}</strong></div>
          <div class="field-item"><span class="field-label">合同名称</span><strong class="field-value">{{ contract.name }}</strong></div>
          <div class="field-item"><span class="field-label">甲方</span><strong class="field-value">{{ unavailable(contract.partyAName) }}</strong><span class="field-evidence">税务身份：{{ unavailable(contract.partyATaxNo) }}</span></div>
          <div class="field-item"><span class="field-label">乙方</span><strong class="field-value">{{ unavailable(contract.partyBName) }}</strong><span class="field-evidence">税务身份：{{ unavailable(contract.partyBTaxNo) }}</span></div>
          <div class="field-item"><span class="field-label">合同金额</span><strong class="field-value numeric-text"><DecimalAmount :amount="contract.amount" /> {{ unavailable(contract.currency) }}</strong></div>
          <div class="field-item"><span class="field-label">签订日期</span><strong class="field-value numeric-text">{{ unavailable(contract.signedDate) }}</strong></div>
          <div class="field-item"><span class="field-label">有效期</span><strong class="field-value numeric-text">{{ unavailable(contract.effectiveDate) }} 至 {{ unavailable(contract.expiryDate) }}</strong></div>
          <div class="field-item"><span class="field-label">付款方式</span><strong class="field-value">{{ unavailable(contract.paymentMethod) }}</strong></div>
          <div class="field-item"><span class="field-label">付款条件</span><strong class="field-value">{{ unavailable(contract.paymentTerms) }}</strong></div>
        </div>
      </SectionCard>

      <ContractManagementPanel
        ref="managementPanel"
        :contract="contract"
        @updated="applyMutation"
        @refresh-requested="loadContract"
      />

      <div v-if="agreementLoading" class="section-card" role="status" aria-live="polite">正在加载补充协议原始 Header…</div>

      <SectionCard v-else-if="agreementErrorMessage" title="无法显示补充协议原始 Header">
        <div class="callout callout-danger" role="alert">
          <div>
            <strong>{{ agreementErrorMessage }}</strong>
            <span v-if="agreementErrorTraceId" class="mono-text"> Trace ID：{{ agreementErrorTraceId }}</span>
          </div>
        </div>
        <div class="form-actions">
          <button class="button button-primary" type="button" data-testid="retry-supplementary-agreements" @click="retryAgreementPage">重试</button>
        </div>
      </SectionCard>

      <SectionCard
        v-else-if="agreementResult"
        title="补充协议原始 Header"
        description="仅展示当前持久化的 7 个 Header 字段；两个状态独立原样展示，不代表协议已生效、适用或进入审核快照。"
        compact
      >
        <div v-if="agreementResult.items.length" class="data-table-wrap">
          <table class="data-table">
            <thead>
              <tr><th>协议编号 / 名称</th><th>签订日期</th><th>生效日期</th><th>确认状态</th><th>业务状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="agreement in agreementResult.items" :key="agreement.id">
                <td>
                  <span class="table-primary">
                    <strong>{{ unavailable(agreement.agreementNo) }}</strong>
                    <span>{{ agreement.name }}</span>
                    <span class="mono-text">{{ agreement.id }}</span>
                  </span>
                </td>
                <td class="numeric-text">{{ unavailable(agreement.signedDate) }}</td>
                <td class="numeric-text">{{ agreement.effectiveDate }}</td>
                <td><StatusTag :status="agreement.confirmationStatus" :label="agreementConfirmationLabels[agreement.confirmationStatus]" /></td>
                <td><StatusTag :status="agreement.status" :label="agreementStatusLabels[agreement.status]" /></td>
                <td><button class="button button-secondary button-small" type="button" :data-testid="`open-supplementary-${agreement.id}`" @click="selectAgreement(agreement.id)">{{ selectedAgreementId === agreement.id ? '收起' : '查看与编辑' }}</button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-inline">当前合同没有补充协议原始 Header。</div>
        <div class="pager">
          <span>第 {{ agreementCurrentPage }} 页 · 每页 {{ agreementResult.pageSize }} 条</span>
          <div class="pager-buttons">
            <button type="button" aria-label="补充协议上一页" :disabled="agreementCurrentPage <= 1 || agreementLoading" @click="loadPreviousAgreementPage">‹</button>
            <button type="button" aria-current="page" disabled>{{ agreementCurrentPage }}</button>
            <button type="button" aria-label="补充协议下一页" :disabled="!agreementResult.nextCursor || agreementLoading" @click="loadNextAgreementPage">›</button>
          </div>
        </div>
      </SectionCard>

      <SupplementaryAgreementPanel
        v-if="selectedAgreementId"
        :contract-id="contract.id"
        :agreement-id="selectedAgreementId"
        @close="selectedAgreementId = ''"
        @updated="applyAgreementMutation"
      />

      <SectionCard title="基准日期有效字段" description="只整体应用在基准日期前已确认生效的补充协议；原值和有效值并列展示。">
        <form class="filter-bar" @submit.prevent="loadEffectiveFields">
          <div class="filter-field">
            <label for="effective-baseline-date">基准日期</label>
            <input id="effective-baseline-date" v-model="baselineDate" type="date" required @input="resetEffectiveResult" />
          </div>
          <div class="filter-actions"><button class="button button-primary" type="submit" data-testid="load-effective-contract" :disabled="baselineDate === '' || effectiveLoading">{{ effectiveLoading ? '正在计算…' : '读取有效字段' }}</button></div>
        </form>
        <div v-if="effectiveLoading" role="status" aria-live="polite">正在读取基准日期有效字段…</div>
        <div v-if="effectiveErrorMessage" class="callout callout-danger" role="alert"><div><strong>{{ effectiveErrorMessage }}</strong><span v-if="effectiveErrorTraceId" class="mono-text"> Trace ID：{{ effectiveErrorTraceId }}</span></div></div>
        <template v-if="effectiveResult">
          <div class="field-grid">
            <div class="field-item"><span class="field-label">基准日期</span><strong class="field-value numeric-text">{{ effectiveResult.baselineDate }}</strong></div>
            <div class="field-item"><span class="field-label">合同数据版本</span><strong class="field-value numeric-text">{{ effectiveResult.rowVersion }}</strong></div>
            <div class="field-item"><span class="field-label">采用协议数</span><strong class="field-value numeric-text">{{ effectiveResult.appliedAgreementIds.length }}</strong></div>
          </div>
          <div class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>字段</th><th>原始值</th><th>有效值</th><th>来源</th></tr></thead>
              <tbody><tr v-for="field in effectiveResult.fields" :key="field.fieldCode"><td><strong>{{ field.fieldCode }}</strong><span class="mono-text">{{ field.valueType }}</span></td><td>{{ formatJsonValue(field.originalValue) }}</td><td>{{ formatJsonValue(field.effectiveValue) }}</td><td><span v-if="field.sourceAgreementId" class="table-primary"><span>{{ field.sourceEffectiveDate }}</span><span class="mono-text">{{ field.sourceAgreementId }}</span></span><span v-else>原合同</span></td></tr></tbody>
            </table>
          </div>
        </template>
      </SectionCard>

      <SectionCard title="当前基线边界">
        <div class="callout callout-warning"><div>合同证据、完整事实修正、确认/拒绝、修正历史、补充协议字段级变更与决定、基准日期有效字段、当前主合同发票和乙方供应商入口已接入。附件管理与合同版本化替换仍未接入，且本页不会把未确认补充协议作为有效事实。</div></div>
      </SectionCard>
    </template>
  </section>
</template>
