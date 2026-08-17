<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'

import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import {
  contractFieldCodes,
  type ContractFieldCode,
  type ContractFieldValueType,
  type JsonValue,
} from '@/services/contracts'
import {
  supplementaryAgreementApi,
  type SupplementaryAgreementChange,
  type SupplementaryAgreementDetail,
  type SupplementaryChangeInput,
} from '@/services/supplementaryAgreements'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ contractId: string; agreementId: string }>()
const emit = defineEmits<{
  close: []
  updated: [detail: SupplementaryAgreementDetail]
}>()

interface ChangeDraft {
  key: string
  fieldCode: string
  valueType: ContractFieldValueType
  newValueIsNull: boolean
  newValueText: string
  evidenceBlockId: string
  pageNo: string
  quoteText: string
  bboxText: string
}

const auth = useAuthStore()
const detail = shallowRef<SupplementaryAgreementDetail | null>(null)
const loading = ref(false)
const loadErrorMessage = ref('')
const loadErrorTraceId = ref('')
const editing = ref(false)
const drafts = ref<ChangeDraft[]>([])
const reason = ref('')
const writing = ref(false)
const writeErrorMessage = ref('')
const writeErrorTraceId = ref('')
const writeSuccessMessage = ref('')
let loadController: AbortController | null = null
let writeController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''
let draftSequence = 0

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

const canManage = computed(() => auth.hasAllPermissions(['contracts.manage']))
const canEdit = computed(
  () =>
    canManage.value &&
    detail.value !== null &&
    ['draft', 'pending_confirmation'].includes(detail.value.status),
)
const canDecide = computed(
  () => canManage.value && detail.value?.status === 'pending_confirmation',
)
const validReason = computed(
  () => reason.value.length >= 1 && reason.value.length <= 1000 && reason.value === reason.value.trim(),
)
const confirmationReady = computed(() => {
  const current = detail.value
  return (
    canDecide.value &&
    current !== null &&
    current.changes.length > 0 &&
    current.changes.every(
      (change) =>
        change.evidenceBlockId !== null && change.pageNo !== null && change.quoteText !== null,
    )
  )
})
const canSubmitChanges = computed(
  () => canEdit.value && validReason.value && drafts.value.length >= 1 && drafts.value.length <= 100,
)

function fieldLabel(fieldCode: string): string {
  return contractFieldCodes.includes(fieldCode as ContractFieldCode)
    ? fieldLabels[fieldCode as ContractFieldCode]
    : fieldCode
}

function formatValue(value: JsonValue): string {
  if (value === null) return 'null'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function resetWriteFeedback(): void {
  writeErrorMessage.value = ''
  writeErrorTraceId.value = ''
  writeSuccessMessage.value = ''
}

function formatLoadError(error: unknown): void {
  loadErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 401) {
    loadErrorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 403) {
    loadErrorMessage.value = '当前账号无权读取补充协议字段级详情。'
  } else if (error instanceof ApiError && error.status === 404) {
    loadErrorMessage.value = '补充协议不存在，或当前账号无权访问。'
  } else {
    loadErrorMessage.value = '补充协议字段级详情加载失败，请稍后重试。'
  }
}

function formatWriteError(error: unknown): void {
  writeErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) {
    writeErrorMessage.value =
      error instanceof TypeError
        ? '输入不符合补充协议写入约束，请检查字段、值和证据格式。'
        : '补充协议操作失败，请稍后重试。'
    return
  }
  if (error.status === 409) {
    writeErrorMessage.value = '协议版本、状态、字段或证据已变化。请刷新后核对最新数据。'
  } else if (error.status === 403) {
    writeErrorMessage.value = '当前账号无权执行补充协议写操作。'
  } else if (error.status === 404) {
    writeErrorMessage.value = '目标合同、补充协议或来源证据已不可见。'
  } else if (error.status === 422) {
    writeErrorMessage.value = '补充协议请求不符合字段约束，请检查输入。'
  } else {
    writeErrorMessage.value = '补充协议操作失败，请稍后重试。'
  }
}

function newDraft(change?: SupplementaryAgreementChange): ChangeDraft {
  draftSequence += 1
  return {
    key: `supplementary-change-${draftSequence}`,
    fieldCode: change?.fieldCode ?? '',
    valueType: change?.valueType ?? 'string',
    newValueIsNull: change?.newValue === null,
    newValueText:
      change?.newValue === null || change === undefined
        ? ''
        : change.valueType === 'json'
          ? JSON.stringify(change.newValue)
          : String(change.newValue),
    evidenceBlockId: change?.evidenceBlockId ?? '',
    pageNo: change?.pageNo === null || change === undefined ? '' : String(change.pageNo),
    quoteText: change?.quoteText ?? '',
    bboxText: change?.bbox === null || change === undefined ? '' : JSON.stringify(change.bbox),
  }
}

function resetDrafts(source: SupplementaryAgreementDetail): void {
  drafts.value = source.changes.map((change) => newDraft(change))
}

function addDraft(): void {
  if (drafts.value.length >= 100) return
  drafts.value = [...drafts.value, newDraft()]
  resetWriteFeedback()
}

function removeDraft(index: number): void {
  drafts.value = drafts.value.filter((_draft, draftIndex) => draftIndex !== index)
  resetWriteFeedback()
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isJsonValue)
  return (
    typeof value === 'object' &&
    value !== null &&
    Object.values(value).every(isJsonValue)
  )
}

function parseJson(text: string): JsonValue {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new TypeError('JSON value is invalid')
  }
  if (!isJsonValue(parsed)) throw new TypeError('JSON value is invalid')
  return parsed
}

function parseBbox(text: string): Record<string, JsonValue> | null {
  if (text === '') return null
  const parsed = parseJson(text)
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new TypeError('bbox must be a JSON object')
  }
  return parsed
}

function parsePageNo(text: string): number | null {
  if (text === '') return null
  if (!/^[1-9]\d*$/.test(text)) throw new TypeError('page number must be positive')
  const value = Number(text)
  if (!Number.isSafeInteger(value)) throw new TypeError('page number must be safe')
  return value
}

function draftValue(draft: ChangeDraft): JsonValue {
  if (draft.newValueIsNull) return null
  if (draft.valueType === 'json') return parseJson(draft.newValueText)
  return draft.newValueText
}

function buildChanges(): SupplementaryChangeInput[] {
  return drafts.value.map((draft) => ({
    fieldCode: draft.fieldCode,
    valueType: draft.valueType,
    newValue: draftValue(draft),
    evidenceBlockId: draft.evidenceBlockId === '' ? null : draft.evidenceBlockId,
    pageNo: parsePageNo(draft.pageNo),
    quoteText: draft.quoteText === '' ? null : draft.quoteText,
    bbox: parseBbox(draft.bboxText),
  }))
}

function idempotencyKey(signature: string): string {
  if (pendingSignature !== signature) {
    pendingSignature = signature
    pendingIdempotencyKey = `supplementary-write.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

async function loadDetail(): Promise<void> {
  loadController?.abort()
  loadController = null
  loadErrorMessage.value = ''
  loadErrorTraceId.value = ''
  detail.value = null
  editing.value = false
  drafts.value = []
  const targetContractId = props.contractId
  const targetAgreementId = props.agreementId
  const controller = new AbortController()
  loadController = controller
  loading.value = true
  try {
    const response = await supplementaryAgreementApi.getDetail(
      targetContractId,
      targetAgreementId,
      controller.signal,
    )
    if (
      loadController === controller &&
      !controller.signal.aborted &&
      props.contractId === targetContractId &&
      props.agreementId === targetAgreementId
    ) {
      detail.value = response
      resetDrafts(response)
    }
  } catch (error) {
    if (loadController === controller && !controller.signal.aborted) formatLoadError(error)
  } finally {
    if (loadController === controller) {
      loadController = null
      loading.value = false
    }
  }
}

async function runWrite(
  signature: string,
  operation: (key: string, signal: AbortSignal) => Promise<SupplementaryAgreementDetail>,
  successMessage: string,
): Promise<void> {
  if (!validReason.value || writing.value) return
  resetWriteFeedback()
  const controller = new AbortController()
  writeController = controller
  writing.value = true
  try {
    const response = await operation(idempotencyKey(signature), controller.signal)
    if (writeController !== controller || controller.signal.aborted) return
    detail.value = response
    resetDrafts(response)
    editing.value = false
    reason.value = ''
    pendingSignature = ''
    pendingIdempotencyKey = ''
    writeSuccessMessage.value = successMessage
    emit('updated', response)
  } catch (error) {
    if (writeController === controller && !controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) {
      writeController = null
      writing.value = false
    }
  }
}

function replaceChanges(): void {
  if (!canSubmitChanges.value || detail.value === null) return
  resetWriteFeedback()
  let changes: SupplementaryChangeInput[]
  try {
    changes = buildChanges()
  } catch (error) {
    formatWriteError(error)
    return
  }
  const input = { rowVersion: detail.value.rowVersion, reason: reason.value, changes }
  const signature = `changes:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) =>
      supplementaryAgreementApi.replaceChanges(
        props.contractId,
        props.agreementId,
        input,
        key,
        signal,
      ),
    '补充协议字段级变更已完整替换，相关审核执行已按服务端规则失效。',
  )
}

function decide(decision: 'confirmed' | 'rejected'): void {
  if (!canDecide.value || detail.value === null) return
  if (decision === 'confirmed' && !confirmationReady.value) return
  const input = { rowVersion: detail.value.rowVersion, decision, reason: reason.value }
  const signature = `decision:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) =>
      supplementaryAgreementApi.decide(
        props.contractId,
        props.agreementId,
        input,
        key,
        signal,
      ),
    decision === 'confirmed' ? '补充协议及全部当前变更已确认。' : '补充协议及全部当前变更已拒绝。',
  )
}

watch(
  () => [props.contractId, props.agreementId] as const,
  () => {
    writeController?.abort()
    reason.value = ''
    pendingSignature = ''
    pendingIdempotencyKey = ''
    resetWriteFeedback()
    void loadDetail()
  },
  { immediate: true },
)

onUnmounted(() => {
  loadController?.abort()
  writeController?.abort()
})
</script>

<template>
  <section id="supplementary-agreement-detail" class="section-card" aria-label="补充协议字段级详情与写操作">
    <div class="section-card-header">
      <div>
        <h2>补充协议字段级详情</h2>
        <p>服务端按字段代码排序返回当前完整变更集合；旧值由服务端按生效日计算。</p>
      </div>
      <button class="button button-secondary button-small" type="button" data-testid="close-supplementary-detail" @click="emit('close')">关闭</button>
    </div>

    <div v-if="loading" class="section-card-body" role="status" aria-live="polite">正在加载补充协议字段级详情…</div>

    <div v-else-if="loadErrorMessage" class="section-card-body page-stack">
      <div class="callout callout-danger" role="alert">
        <div><strong>{{ loadErrorMessage }}</strong><span v-if="loadErrorTraceId" class="mono-text"> Trace ID：{{ loadErrorTraceId }}</span></div>
      </div>
      <div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-supplementary-detail" @click="loadDetail">重试</button></div>
    </div>

    <div v-else-if="detail" class="section-card-body page-stack">
      <div class="field-grid">
        <div class="field-item"><span class="field-label">协议编号</span><strong class="field-value">{{ detail.agreementNo || '—' }}</strong></div>
        <div class="field-item"><span class="field-label">协议名称</span><strong class="field-value">{{ detail.name }}</strong></div>
        <div class="field-item"><span class="field-label">生效日期</span><strong class="field-value numeric-text">{{ detail.effectiveDate }}</strong></div>
        <div class="field-item"><span class="field-label">数据版本</span><strong class="field-value numeric-text">{{ detail.rowVersion }}</strong></div>
        <div class="field-item"><span class="field-label">确认状态</span><StatusTag :status="detail.confirmationStatus" /></div>
        <div class="field-item"><span class="field-label">业务状态</span><StatusTag :status="detail.status" /></div>
      </div>

      <div v-if="!canManage" class="callout" role="note"><div><strong>只读模式</strong>当前账号没有合同管理权限，可查看字段变更和来源证据，但不能修改或决定。</div></div>

      <div v-else class="page-stack">
        <div class="form-field">
          <label for="supplementary-write-reason">操作原因</label>
          <textarea id="supplementary-write-reason" v-model="reason" class="textarea-input" rows="3" maxlength="1000" :disabled="writing" placeholder="填写字段修正或决定依据" @input="resetWriteFeedback" />
          <span class="form-help">原因不能为空，且不得包含首尾空白。</span>
        </div>
        <div class="inline-actions">
          <button class="button button-secondary" type="button" data-testid="edit-supplementary-changes" :disabled="!canEdit || writing" @click="editing = !editing">{{ editing ? '收起字段编辑' : '编辑完整变更集合' }}</button>
          <button class="button button-primary" type="button" data-testid="confirm-supplementary" :disabled="!confirmationReady || !validReason || writing" @click="decide('confirmed')">确认补充协议</button>
          <button class="button button-danger" type="button" data-testid="reject-supplementary" :disabled="!canDecide || !validReason || writing" @click="decide('rejected')">拒绝补充协议</button>
        </div>
        <div v-if="canDecide && !confirmationReady" class="callout callout-warning" role="note"><div>确认要求当前变更集合非空，且每项都包含来源块、页码和逐字引用；拒绝不要求补造证据。</div></div>
        <div v-if="writeErrorMessage" class="callout callout-danger" role="alert"><div><strong>{{ writeErrorMessage }}</strong><span v-if="writeErrorTraceId" class="mono-text"> Trace ID：{{ writeErrorTraceId }}</span></div></div>
        <div v-if="writeSuccessMessage" class="callout callout-success" role="status"><div><strong>{{ writeSuccessMessage }}</strong></div></div>
      </div>

      <div v-if="editing && canEdit" class="page-stack">
        <div class="callout callout-warning" role="note"><div>提交会完整替换当前变更集合。字段旧值由服务端计算；来源证据必须引用当前组织可见的解析块。</div></div>
        <fieldset v-for="(draft, index) in drafts" :key="draft.key" class="section-card">
          <legend>变更 {{ index + 1 }}</legend>
          <div class="section-card-body page-stack">
            <div class="form-grid">
              <label class="form-field"><span>字段代码</span><input v-model.trim="draft.fieldCode" class="text-input" :data-testid="`supplementary-field-code-${index}`" :list="`contract-field-codes-${draft.key}`" maxlength="80" required /><datalist :id="`contract-field-codes-${draft.key}`"><option v-for="code in contractFieldCodes" :key="code" :value="code">{{ fieldLabels[code] }}</option></datalist></label>
              <label class="form-field"><span>值类型</span><select v-model="draft.valueType" class="select-input" :data-testid="`supplementary-value-type-${index}`"><option value="string">string</option><option value="number">number</option><option value="date">date</option><option value="json">json</option></select></label>
              <label class="form-field form-field-wide"><span>新值</span><textarea v-model="draft.newValueText" class="textarea-input" :data-testid="`supplementary-new-value-${index}`" rows="2" :disabled="draft.newValueIsNull" :placeholder="draft.valueType === 'json' ? '输入 JSON object、array 或 boolean' : '输入新值'" /></label>
              <label class="form-field"><span><input v-model="draft.newValueIsNull" type="checkbox" /> 新值为 null</span></label>
              <label class="form-field"><span>来源块 UUID（可选）</span><input v-model.trim="draft.evidenceBlockId" class="text-input" maxlength="36" /></label>
              <label class="form-field"><span>页码（可选）</span><input v-model.trim="draft.pageNo" class="text-input" inputmode="numeric" /></label>
              <label class="form-field form-field-wide"><span>逐字引用（可选）</span><textarea v-model="draft.quoteText" class="textarea-input" rows="2" maxlength="4000" /></label>
              <label class="form-field form-field-wide"><span>bbox JSON（可选）</span><textarea v-model.trim="draft.bboxText" class="textarea-input" rows="2" placeholder='例如 {"x":10,"y":20}' /></label>
            </div>
            <div class="inline-actions"><button class="button button-danger button-small" type="button" :data-testid="`remove-supplementary-change-${index}`" @click="removeDraft(index)">移除此项</button></div>
          </div>
        </fieldset>
        <div class="inline-actions">
          <button class="button button-secondary" type="button" data-testid="add-supplementary-change" :disabled="drafts.length >= 100" @click="addDraft">添加字段变更</button>
          <button class="button button-primary" type="button" data-testid="replace-supplementary-changes" :disabled="!canSubmitChanges || writing" @click="replaceChanges">提交完整变更集合</button>
        </div>
      </div>

      <div v-if="detail.changes.length" class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>字段</th><th>原值</th><th>新值</th><th>状态</th><th>来源证据</th></tr></thead>
          <tbody>
            <tr v-for="change in detail.changes" :key="change.id">
              <td><strong>{{ fieldLabel(change.fieldCode) }}</strong><span class="mono-text">{{ change.fieldCode }} · {{ change.valueType }}</span></td>
              <td>{{ formatValue(change.oldValue) }}</td>
              <td>{{ formatValue(change.newValue) }}</td>
              <td><StatusTag :status="change.confirmationStatus" /></td>
              <td><span v-if="change.evidenceBlockId" class="table-primary"><span>第 {{ change.pageNo }} 页</span><span>{{ change.quoteText }}</span><span class="mono-text">{{ change.evidenceBlockId }}</span></span><span v-else>无来源证据</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前补充协议尚无字段级变更。</div>
    </div>
  </section>
</template>
