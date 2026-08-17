<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'

import { ApiError } from '@/services/api'
import {
  contractApi,
  contractFieldCodes,
  type ContractCorrectionHistoryData,
  type ContractDetail,
  type ContractEvidence,
  type ContractEvidenceResponseData,
  type ContractFactsInput,
  type ContractFactsReplaceInput,
  type ContractFieldCode,
  type ContractMutationData,
} from '@/services/contracts'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ contract: ContractDetail }>()
const emit = defineEmits<{
  updated: [data: ContractMutationData]
  refreshRequested: []
}>()

const auth = useAuthStore()
const evidence = ref<ContractEvidenceResponseData | null>(null)
const history = ref<ContractCorrectionHistoryData | null>(null)
const supportingLoading = ref(false)
const supportingErrorMessage = ref('')
const supportingErrorTraceId = ref('')
const editing = ref(false)
const reason = ref('')
const writing = ref(false)
const writeErrorMessage = ref('')
const writeErrorTraceId = ref('')
const writeSuccessMessage = ref('')
const form = reactive({
  contractNo: '',
  name: '',
  partyAName: '',
  partyATaxNo: '',
  partyBName: '',
  partyBTaxNo: '',
  amount: '',
  currency: '',
  signedDate: '',
  effectiveDate: '',
  expiryDate: '',
  paymentMethod: '',
  paymentTerms: '',
})
let supportingController: AbortController | null = null
let writeController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const fieldLabels: Readonly<Record<ContractFieldCode, string>> = {
  contract_no: '合同编号',
  name: '合同名称',
  party_a_name: '甲方名称',
  party_a_tax_no: '甲方税号',
  party_b_name: '乙方名称',
  party_b_tax_no: '乙方税号',
  amount: '合同金额',
  currency: '币种',
  signed_date: '签订日期',
  effective_date: '生效日期',
  expiry_date: '到期日期',
  payment_method: '付款方式',
  payment_terms: '付款条件',
}

const requiredConfirmationCodes = [
  'contract_no',
  'name',
  'party_a_name',
  'party_a_tax_no',
  'party_b_name',
  'party_b_tax_no',
  'amount',
  'currency',
  'effective_date',
] as const satisfies readonly ContractFieldCode[]

const canManage = computed(() => auth.hasAllPermissions(['contracts.manage']))
const validReason = computed(() => {
  const value = reason.value
  return value.length >= 1 && value.length <= 1000 && value === value.trim()
})
const evidenceIsCurrent = computed(
  () => evidence.value !== null && evidence.value.rowVersion === props.contract.rowVersion,
)
const evidenceByCode = computed(() => {
  const result = new Map<ContractFieldCode, ContractEvidence>()
  for (const field of evidence.value?.fields ?? []) {
    if (field.evidence !== null) result.set(field.fieldCode, field.evidence)
  }
  return result
})
const evidenceRows = computed(() =>
  (evidence.value?.fields ?? []).map((field) => ({
    fieldCode: field.fieldCode,
    label: fieldLabels[field.fieldCode],
    candidate: formatCandidate(field.candidateValue),
    pageNo: field.evidence?.pageNo ?? '—',
    quoteText: field.evidence?.quoteText ?? '无来源证据',
    confidence: field.evidence?.confidence ?? '—',
  })),
)
const canReplaceFacts = computed(
  () =>
    canManage.value &&
    props.contract.status === 'draft' &&
    ['unconfirmed', 'rejected'].includes(props.contract.confirmationStatus) &&
    evidenceIsCurrent.value,
)
const canDecide = computed(
  () =>
    canManage.value &&
    props.contract.status === 'draft' &&
    props.contract.confirmationStatus === 'unconfirmed' &&
    evidenceIsCurrent.value,
)
const confirmationReady = computed(() => {
  if (!canDecide.value) return false
  const facts = currentFacts()
  return requiredConfirmationCodes.every((code) => {
    const value = factByCode(facts, code)
    return value !== null && value !== '' && evidenceByCode.value.has(code)
  }) && contractFieldCodes.every((code) => factByCode(facts, code) === null || evidenceByCode.value.has(code))
})

function nullable(value: string): string | null {
  return value === '' ? null : value
}

function formatCandidate(value: unknown): string {
  if (value === null) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value)
    : '—'
}

function resetForm(contract: ContractDetail): void {
  form.contractNo = contract.contractNo ?? ''
  form.name = contract.name
  form.partyAName = contract.partyAName ?? ''
  form.partyATaxNo = contract.partyATaxNo ?? ''
  form.partyBName = contract.partyBName ?? ''
  form.partyBTaxNo = contract.partyBTaxNo ?? ''
  form.amount = contract.amount ?? ''
  form.currency = contract.currency ?? ''
  form.signedDate = contract.signedDate ?? ''
  form.effectiveDate = contract.effectiveDate ?? ''
  form.expiryDate = contract.expiryDate ?? ''
  form.paymentMethod = contract.paymentMethod ?? ''
  form.paymentTerms = contract.paymentTerms ?? ''
}

function currentFacts(): ContractFactsInput {
  return {
    contractNo: nullable(form.contractNo),
    name: nullable(form.name),
    partyAName: nullable(form.partyAName),
    partyATaxNo: nullable(form.partyATaxNo),
    partyBName: nullable(form.partyBName),
    partyBTaxNo: nullable(form.partyBTaxNo),
    amount: nullable(form.amount),
    currency: nullable(form.currency),
    signedDate: nullable(form.signedDate),
    effectiveDate: nullable(form.effectiveDate),
    expiryDate: nullable(form.expiryDate),
    paymentMethod: nullable(form.paymentMethod),
    paymentTerms: nullable(form.paymentTerms),
  }
}

function factByCode(facts: ContractFactsInput, code: ContractFieldCode): string | null {
  const values: Readonly<Record<ContractFieldCode, string | null>> = {
    contract_no: facts.contractNo,
    name: facts.name,
    party_a_name: facts.partyAName,
    party_a_tax_no: facts.partyATaxNo,
    party_b_name: facts.partyBName,
    party_b_tax_no: facts.partyBTaxNo,
    amount: facts.amount,
    currency: facts.currency,
    signed_date: facts.signedDate,
    effective_date: facts.effectiveDate,
    expiry_date: facts.expiryDate,
    payment_method: facts.paymentMethod,
    payment_terms: facts.paymentTerms,
  }
  return values[code]
}

function resetWriteFeedback(): void {
  writeErrorMessage.value = ''
  writeErrorTraceId.value = ''
  writeSuccessMessage.value = ''
}

function formatSupportingError(error: unknown): void {
  supportingErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    supportingErrorMessage.value = '当前账号无权读取合同证据或修正历史。'
  } else if (error instanceof ApiError && error.status === 404) {
    supportingErrorMessage.value = '合同不存在，或当前账号无权访问。'
  } else {
    supportingErrorMessage.value = '合同证据与修正历史加载失败，请稍后重试。'
  }
}

function formatWriteError(error: unknown): void {
  writeErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) {
    writeErrorMessage.value =
      error instanceof TypeError ? '输入不符合合同写入约束，请检查字段格式。' : '合同操作失败，请稍后重试。'
    return
  }
  if (error.status === 409) {
    writeErrorMessage.value = '合同版本、状态或来源证据已变化。请刷新后核对最新数据。'
  } else if (error.status === 403) {
    writeErrorMessage.value = '当前账号无权执行合同写操作。'
  } else if (error.status === 404) {
    writeErrorMessage.value = '目标合同或来源证据已不可见。'
  } else if (error.status === 422) {
    writeErrorMessage.value = '合同请求不符合字段约束，请检查输入。'
  } else {
    writeErrorMessage.value = '合同操作失败，请稍后重试。'
  }
}

async function loadSupportingData(contractId: string, rowVersion: string): Promise<void> {
  supportingController?.abort()
  evidence.value = null
  history.value = null
  supportingErrorMessage.value = ''
  supportingErrorTraceId.value = ''
  const controller = new AbortController()
  supportingController = controller
  supportingLoading.value = true
  try {
    const [evidenceResponse, historyResponse] = await Promise.all([
      contractApi.getEvidence(contractId, controller.signal),
      contractApi.getHistory(contractId, controller.signal),
    ])
    if (
      supportingController === controller &&
      !controller.signal.aborted &&
      props.contract.id === contractId
    ) {
      evidence.value = evidenceResponse
      history.value = historyResponse
      if (evidenceResponse.rowVersion !== rowVersion) {
        supportingErrorMessage.value = '合同版本已变化，需刷新详情后才能继续写入。'
      }
    }
  } catch (error) {
    if (supportingController === controller && !controller.signal.aborted) formatSupportingError(error)
  } finally {
    if (supportingController === controller) {
      supportingController = null
      supportingLoading.value = false
    }
  }
}

function idempotencyKey(signature: string): string {
  if (pendingSignature !== signature) {
    pendingSignature = signature
    pendingIdempotencyKey = `contract-write.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

async function runWrite(
  signature: string,
  operation: (key: string, signal: AbortSignal) => Promise<ContractMutationData>,
  successMessage: string,
): Promise<void> {
  if (!validReason.value || writing.value) return
  resetWriteFeedback()
  const controller = new AbortController()
  writeController = controller
  writing.value = true
  try {
    const result = await operation(idempotencyKey(signature), controller.signal)
    if (writeController !== controller || controller.signal.aborted) return
    writeSuccessMessage.value = successMessage
    reason.value = ''
    editing.value = false
    pendingSignature = ''
    pendingIdempotencyKey = ''
    resetForm(result.contract)
    emit('updated', result)
    await loadSupportingData(result.contract.id, result.contract.rowVersion)
  } catch (error) {
    if (writeController === controller && !controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) {
      writeController = null
      writing.value = false
    }
  }
}

function buildFactsInput(): ContractFactsReplaceInput | null {
  if (!evidence.value || !evidenceIsCurrent.value) return null
  const facts = currentFacts()
  const fieldEvidence: ContractFactsReplaceInput['fieldEvidence'] = []
  for (const fieldCode of contractFieldCodes) {
    if (factByCode(facts, fieldCode) === null) continue
    const sourceEvidence = evidenceByCode.value.get(fieldCode)
    if (!sourceEvidence) {
      writeErrorMessage.value = `${fieldLabels[fieldCode]}没有可复核的来源证据，不能作为非空事实提交。`
      return null
    }
    fieldEvidence.push({ fieldCode, evidence: sourceEvidence })
  }
  return { rowVersion: props.contract.rowVersion, reason: reason.value, facts, fieldEvidence }
}

function replaceFacts(): void {
  resetWriteFeedback()
  const input = buildFactsInput()
  if (!input || !canReplaceFacts.value) return
  const signature = `facts:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => contractApi.replaceFacts(props.contract.id, input, key, signal),
    '合同事实已完整替换，并保留字段来源证据。',
  )
}

function decide(decision: 'confirmed' | 'rejected'): void {
  if (!canDecide.value || (decision === 'confirmed' && !confirmationReady.value)) return
  const input = { rowVersion: props.contract.rowVersion, decision, reason: reason.value }
  const signature = `decision:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => contractApi.decide(props.contract.id, input, key, signal),
    decision === 'confirmed' ? '合同事实已确认。' : '合同事实已拒绝。',
  )
}

function startEditing(): void {
  if (canReplaceFacts.value) editing.value = true
}

defineExpose({ startEditing })

watch(
  () => [props.contract.id, props.contract.rowVersion] as const,
  ([contractId, rowVersion]) => {
    writeController?.abort()
    editing.value = false
    reason.value = ''
    pendingSignature = ''
    pendingIdempotencyKey = ''
    resetWriteFeedback()
    resetForm(props.contract)
    void loadSupportingData(contractId, rowVersion)
  },
  { immediate: true },
)

onUnmounted(() => {
  supportingController?.abort()
  writeController?.abort()
})
</script>

<template>
  <section id="contract-management" class="page-stack" aria-label="合同写操作与审计">
    <div v-if="supportingLoading" class="section-card" role="status" aria-live="polite">
      正在加载合同证据与修正历史…
    </div>

    <div v-if="supportingErrorMessage" class="callout callout-danger" role="alert">
      <div>
        <strong>{{ supportingErrorMessage }}</strong>
        <span v-if="supportingErrorTraceId" class="mono-text"> Trace ID：{{ supportingErrorTraceId }}</span>
      </div>
      <button class="button button-secondary button-small" type="button" @click="emit('refreshRequested')">刷新详情</button>
    </div>

    <div v-if="!canManage" class="callout" role="note">
      <div><strong>只读模式</strong>当前账号没有合同管理权限，可查看证据和修正历史，但不能修改或处置。</div>
    </div>

    <div v-else class="section-card">
      <div class="section-card-header">
        <div><h2>人工操作</h2><p>所有写操作绑定当前行版本、来源证据、幂等键和人工原因。</p></div>
      </div>
      <div class="section-card-body page-stack">
        <div class="form-field">
          <label for="contract-write-reason">操作原因</label>
          <textarea
            id="contract-write-reason"
            v-model="reason"
            rows="3"
            maxlength="1000"
            :disabled="writing"
            placeholder="填写人工复核或处置依据"
            @input="resetWriteFeedback"
          />
          <span class="form-help">原因不能为空，且不得包含首尾空白。</span>
        </div>
        <div class="inline-actions">
          <button class="button button-secondary" type="button" :disabled="!canReplaceFacts || writing" data-testid="edit-contract-facts" @click="editing = !editing">
            {{ editing ? '收起事实修正' : '修正完整事实' }}
          </button>
          <button class="button button-primary" type="button" :disabled="!confirmationReady || !validReason || writing" data-testid="confirm-contract" @click="decide('confirmed')">确认合同</button>
          <button class="button button-danger" type="button" :disabled="!canDecide || !validReason || writing" data-testid="reject-contract" @click="decide('rejected')">拒绝合同</button>
        </div>
        <div v-if="canDecide && !confirmationReady" class="callout callout-warning" role="note">
          <div>确认前必须补齐合同编号、名称、双方名称与税号、金额、币种、生效日期，并确保每个非空字段都有来源证据。</div>
        </div>
        <div v-if="writeErrorMessage" class="callout callout-danger" role="alert">
          <div><strong>{{ writeErrorMessage }}</strong><span v-if="writeErrorTraceId" class="mono-text"> Trace ID：{{ writeErrorTraceId }}</span></div>
        </div>
        <div v-if="writeSuccessMessage" class="callout callout-success" role="status"><div><strong>{{ writeSuccessMessage }}</strong></div></div>
      </div>
    </div>

    <div v-if="editing && canReplaceFacts" class="section-card">
      <div class="section-card-header"><div><h2>完整事实修正</h2><p>提交会完整替换当前未确认事实；现有来源证据按字段原样保留。</p></div></div>
      <div class="section-card-body page-stack">
        <div class="callout callout-warning" role="note"><div>人工修正只调整结构化值，不改变来源文本。没有来源证据的字段只能保持为空。</div></div>
        <div class="form-grid">
          <div class="form-field"><label for="edit-contract-no">合同编号</label><input id="edit-contract-no" v-model.trim="form.contractNo" class="text-input" maxlength="100" /></div>
          <div class="form-field"><label for="edit-contract-name">合同名称</label><input id="edit-contract-name" v-model.trim="form.name" class="text-input" maxlength="300" /></div>
          <div class="form-field"><label for="edit-party-a-name">甲方名称</label><input id="edit-party-a-name" v-model.trim="form.partyAName" class="text-input" maxlength="300" /></div>
          <div class="form-field"><label for="edit-party-a-tax-no">甲方税号</label><input id="edit-party-a-tax-no" v-model.trim="form.partyATaxNo" class="text-input" maxlength="32" /></div>
          <div class="form-field"><label for="edit-party-b-name">乙方名称</label><input id="edit-party-b-name" v-model.trim="form.partyBName" class="text-input" maxlength="300" /></div>
          <div class="form-field"><label for="edit-party-b-tax-no">乙方税号</label><input id="edit-party-b-tax-no" v-model.trim="form.partyBTaxNo" class="text-input" maxlength="32" /></div>
          <div class="form-field"><label for="edit-contract-amount">合同金额</label><input id="edit-contract-amount" v-model.trim="form.amount" class="text-input" inputmode="decimal" /></div>
          <div class="form-field"><label for="edit-contract-currency">币种</label><input id="edit-contract-currency" v-model.trim="form.currency" class="text-input" maxlength="3" /></div>
          <div class="form-field"><label for="edit-contract-signed-date">签订日期</label><input id="edit-contract-signed-date" v-model="form.signedDate" class="text-input" type="date" /></div>
          <div class="form-field"><label for="edit-contract-effective-date">生效日期</label><input id="edit-contract-effective-date" v-model="form.effectiveDate" class="text-input" type="date" /></div>
          <div class="form-field"><label for="edit-contract-expiry-date">到期日期</label><input id="edit-contract-expiry-date" v-model="form.expiryDate" class="text-input" type="date" /></div>
          <div class="form-field"><label for="edit-contract-payment-method">付款方式</label><input id="edit-contract-payment-method" v-model.trim="form.paymentMethod" class="text-input" maxlength="100" /></div>
          <div class="form-field"><label for="edit-contract-payment-terms">付款条件</label><textarea id="edit-contract-payment-terms" v-model.trim="form.paymentTerms" rows="3" maxlength="4000" /></div>
        </div>
        <div class="inline-actions">
          <button class="button button-primary" type="button" :disabled="!validReason || writing" data-testid="replace-contract-facts" @click="replaceFacts">提交完整事实修正</button>
        </div>
      </div>
    </div>

    <div v-if="evidence" class="section-card">
      <div class="section-card-header"><div><h2>合同字段证据</h2><p>证据版本 {{ evidence.rowVersion }}；来源文件 {{ evidence.fileId }}。</p></div></div>
      <div class="section-card-body">
        <div class="data-table-wrap">
          <table class="data-table">
            <thead><tr><th>字段</th><th>候选值</th><th>页码</th><th>引用文本</th><th>置信度</th></tr></thead>
            <tbody>
              <tr v-for="field in evidenceRows" :key="field.fieldCode">
                <td>{{ field.label }}<span class="mono-text">{{ field.fieldCode }}</span></td>
                <td>{{ field.candidate }}</td>
                <td>{{ field.pageNo }}</td>
                <td>{{ field.quoteText }}</td>
                <td>{{ field.confidence }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="history" class="section-card">
      <div class="section-card-header"><div><h2>合同修正与处置历史</h2><p>追加式记录事实替换、确认和拒绝。</p></div></div>
      <div class="section-card-body">
        <div v-if="history.items.length" class="data-table-wrap">
          <table class="data-table"><thead><tr><th>字段路径</th><th>原因</th><th>Actor 角色</th><th>时间</th><th>Trace ID</th></tr></thead><tbody><tr v-for="item in history.items" :key="item.id"><td class="mono-text">{{ item.fieldPath }}</td><td>{{ item.reason }}</td><td>{{ item.actorRoleCode }}</td><td>{{ new Date(item.createdAt).toLocaleString('zh-CN', { hour12: false }) }}</td><td class="mono-text">{{ item.traceId }}</td></tr></tbody></table>
        </div>
        <div v-else class="empty-inline">尚无人工修正或处置历史。</div>
      </div>
    </div>
  </section>
</template>
