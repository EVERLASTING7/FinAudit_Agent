<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'

import { ApiError } from '@/services/api'
import {
  invoiceApi,
  type InvoiceCorrectionHistoryData,
  type InvoiceDetail,
  type InvoiceEvidenceResponseData,
  type InvoiceFactsReplaceInput,
  type InvoiceMutationData,
} from '@/services/invoices'
import { useAuthStore } from '@/stores/auth'

interface EditableItem {
  lineNo: number
  itemName: string
  specification: string
  unit: string
  quantity: string
  unitPrice: string
  amountExcludingTax: string
  taxRate: string
  taxAmount: string
  totalAmount: string
}

const props = defineProps<{
  invoice: InvoiceDetail
  duplicateCandidateIds: string[]
}>()
const emit = defineEmits<{
  updated: [data: InvoiceMutationData]
  refreshRequested: []
}>()

const auth = useAuthStore()
const evidence = ref<InvoiceEvidenceResponseData | null>(null)
const history = ref<InvoiceCorrectionHistoryData | null>(null)
const supportingLoading = ref(false)
const supportingErrorMessage = ref('')
const supportingErrorTraceId = ref('')
const editing = ref(false)
const reason = ref('')
const selectedCandidateId = ref('')
const writing = ref(false)
const writeErrorMessage = ref('')
const writeErrorTraceId = ref('')
const writeSuccessMessage = ref('')
const form = reactive({
  invoiceCode: '',
  invoiceNumber: '',
  invoiceType: '',
  isRedInvoice: '',
  invoiceDate: '',
  buyerName: '',
  buyerTaxNo: '',
  sellerName: '',
  sellerTaxNo: '',
  amountExcludingTax: '',
  taxAmount: '',
  totalAmount: '',
  currency: 'CNY',
  items: [] as EditableItem[],
})
let supportingController: AbortController | null = null
let writeController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const canManage = computed(() => auth.hasAllPermissions(['invoices.manage']))
const validReason = computed(() => {
  const value = reason.value
  return value.length >= 1 && value.length <= 1000 && value === value.trim()
})
const evidenceIsCurrent = computed(
  () => evidence.value !== null && evidence.value.rowVersion === props.invoice.rowVersion,
)
const canReplaceFacts = computed(
  () =>
    canManage.value &&
    props.invoice.status === 'draft' &&
    ['unconfirmed', 'rejected'].includes(props.invoice.confirmationStatus) &&
    evidenceIsCurrent.value,
)
const canDecide = computed(
  () =>
    canManage.value &&
    props.invoice.status === 'draft' &&
    props.invoice.confirmationStatus === 'unconfirmed',
)
const canCheckDuplicate = computed(
  () =>
    canManage.value &&
    !['voided', 'archived'].includes(props.invoice.status) &&
    !['confirmed_duplicate', 'exception_approved'].includes(props.invoice.duplicateStatus),
)
const canDecideDuplicate = computed(
  () =>
    canManage.value &&
    !['voided', 'archived'].includes(props.invoice.status) &&
    props.duplicateCandidateIds.includes(selectedCandidateId.value),
)

function nullable(value: string): string | null {
  return value === '' ? null : value
}

function resetForm(invoice: InvoiceDetail): void {
  form.invoiceCode = invoice.invoiceCode ?? ''
  form.invoiceNumber = invoice.invoiceNumber ?? ''
  form.invoiceType = invoice.invoiceType ?? ''
  form.isRedInvoice = invoice.isRedInvoice === null ? '' : String(invoice.isRedInvoice)
  form.invoiceDate = invoice.invoiceDate ?? ''
  form.buyerName = invoice.buyerName ?? ''
  form.buyerTaxNo = invoice.buyerTaxNo ?? ''
  form.sellerName = invoice.sellerName ?? ''
  form.sellerTaxNo = invoice.sellerTaxNo ?? ''
  form.amountExcludingTax = invoice.amountExcludingTax ?? ''
  form.taxAmount = invoice.taxAmount ?? ''
  form.totalAmount = invoice.totalAmount ?? ''
  form.currency = invoice.currency
  form.items = invoice.items.map((item) => ({
    lineNo: item.lineNo,
    itemName: item.itemName ?? '',
    specification: item.specification ?? '',
    unit: item.unit ?? '',
    quantity: item.quantity ?? '',
    unitPrice: item.unitPrice ?? '',
    amountExcludingTax: item.amountExcludingTax ?? '',
    taxRate: item.taxRate ?? '',
    taxAmount: item.taxAmount ?? '',
    totalAmount: item.totalAmount ?? '',
  }))
}

function resetWriteFeedback(): void {
  writeErrorMessage.value = ''
  writeErrorTraceId.value = ''
  writeSuccessMessage.value = ''
}

function formatSupportingError(error: unknown): void {
  supportingErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    supportingErrorMessage.value = '当前账号无权读取发票证据或修正历史。'
  } else if (error instanceof ApiError && error.status === 404) {
    supportingErrorMessage.value = '发票不存在，或当前账号无权访问。'
  } else {
    supportingErrorMessage.value = '发票证据与修正历史加载失败，请稍后重试。'
  }
}

function formatWriteError(error: unknown): void {
  writeErrorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) {
    writeErrorMessage.value =
      error instanceof TypeError ? '输入不符合发票写入约束，请检查字段格式。' : '发票操作失败，请稍后重试。'
    return
  }
  if (error.status === 409) {
    writeErrorMessage.value = '发票版本、状态、证据或重复事实已变化。请刷新后核对最新数据。'
  } else if (error.status === 403) {
    writeErrorMessage.value = '当前账号无权执行发票写操作。'
  } else if (error.status === 404) {
    writeErrorMessage.value = '目标发票、候选或来源证据已不可见。'
  } else if (error.status === 422) {
    writeErrorMessage.value = '发票请求不符合字段约束，请检查输入。'
  } else {
    writeErrorMessage.value = '发票操作失败，请稍后重试。'
  }
}

async function loadSupportingData(invoiceId: string, rowVersion: string): Promise<void> {
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
      invoiceApi.getEvidence(invoiceId, controller.signal),
      invoiceApi.getHistory(invoiceId, controller.signal),
    ])
    if (
      supportingController === controller &&
      !controller.signal.aborted &&
      props.invoice.id === invoiceId
    ) {
      evidence.value = evidenceResponse
      history.value = historyResponse
      if (evidenceResponse.rowVersion !== rowVersion) {
        supportingErrorMessage.value = '发票版本已变化，需刷新详情后才能继续写入。'
      }
    }
  } catch (error) {
    if (supportingController === controller && !controller.signal.aborted) {
      formatSupportingError(error)
    }
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
    pendingIdempotencyKey = `invoice-write.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

async function runWrite(
  signature: string,
  operation: (key: string, signal: AbortSignal) => Promise<InvoiceMutationData>,
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
    resetForm(result.invoice)
    emit('updated', result)
    await loadSupportingData(result.invoice.id, result.invoice.rowVersion)
  } catch (error) {
    if (writeController === controller && !controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) {
      writeController = null
      writing.value = false
    }
  }
}

function buildFactsInput(): InvoiceFactsReplaceInput | null {
  if (!evidence.value || !evidenceIsCurrent.value) return null
  return {
    rowVersion: props.invoice.rowVersion,
    reason: reason.value,
    facts: {
      invoiceCode: nullable(form.invoiceCode),
      invoiceNumber: nullable(form.invoiceNumber),
      invoiceType: nullable(form.invoiceType),
      isRedInvoice: form.isRedInvoice === '' ? null : form.isRedInvoice === 'true',
      invoiceDate: nullable(form.invoiceDate),
      buyerName: nullable(form.buyerName),
      buyerTaxNo: nullable(form.buyerTaxNo),
      sellerName: nullable(form.sellerName),
      sellerTaxNo: nullable(form.sellerTaxNo),
      amountExcludingTax: nullable(form.amountExcludingTax),
      taxAmount: nullable(form.taxAmount),
      totalAmount: nullable(form.totalAmount),
      currency: form.currency,
    },
    fieldEvidence: evidence.value.fieldEvidence,
    items: form.items.map((item) => ({
      lineNo: item.lineNo,
      itemName: nullable(item.itemName),
      specification: nullable(item.specification),
      unit: nullable(item.unit),
      quantity: nullable(item.quantity),
      unitPrice: nullable(item.unitPrice),
      amountExcludingTax: nullable(item.amountExcludingTax),
      taxRate: nullable(item.taxRate),
      taxAmount: nullable(item.taxAmount),
      totalAmount: nullable(item.totalAmount),
      evidence: evidence.value?.itemEvidence[String(item.lineNo)] ?? [],
    })),
  }
}

function replaceFacts(): void {
  const input = buildFactsInput()
  if (!input || !canReplaceFacts.value) return
  const signature = `facts:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => invoiceApi.replaceFacts(props.invoice.id, input, key, signal),
    '发票事实已完整替换，并保留字段与明细证据。',
  )
}

function decide(decision: 'confirmed' | 'rejected'): void {
  if (!canDecide.value) return
  const input = { rowVersion: props.invoice.rowVersion, decision, reason: reason.value }
  const signature = `decision:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => invoiceApi.decide(props.invoice.id, input, key, signal),
    decision === 'confirmed' ? '发票事实已确认。' : '发票事实已拒绝。',
  )
}

function checkDuplicate(): void {
  if (!canCheckDuplicate.value) return
  const input = { rowVersion: props.invoice.rowVersion, reason: reason.value }
  const signature = `duplicate-check:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => invoiceApi.checkDuplicate(props.invoice.id, input, key, signal),
    '精确重复状态已重新检测。',
  )
}

function decideDuplicate(decision: 'confirmed_duplicate' | 'exception_approved'): void {
  if (!canDecideDuplicate.value) return
  const input = {
    rowVersion: props.invoice.rowVersion,
    candidateId: selectedCandidateId.value,
    decision,
    reason: reason.value,
  }
  const signature = `duplicate-decision:${JSON.stringify(input)}`
  void runWrite(
    signature,
    (key, signal) => invoiceApi.decideDuplicate(props.invoice.id, input, key, signal),
    decision === 'confirmed_duplicate' ? '已人工确认重复发票。' : '已批准重复例外。',
  )
}

function addItem(): void {
  const nextLine = Math.max(0, ...form.items.map((item) => item.lineNo)) + 1
  if (nextLine > 1000) return
  form.items.push({
    lineNo: nextLine,
    itemName: '',
    specification: '',
    unit: '',
    quantity: '',
    unitPrice: '',
    amountExcludingTax: '',
    taxRate: '',
    taxAmount: '',
    totalAmount: '',
  })
  resetWriteFeedback()
}

function removeItem(lineNo: number): void {
  form.items = form.items.filter((item) => item.lineNo !== lineNo)
  resetWriteFeedback()
}

watch(
  () => [props.invoice.id, props.invoice.rowVersion] as const,
  ([invoiceId, rowVersion]) => {
    writeController?.abort()
    editing.value = false
    reason.value = ''
    pendingSignature = ''
    pendingIdempotencyKey = ''
    resetWriteFeedback()
    resetForm(props.invoice)
    void loadSupportingData(invoiceId, rowVersion)
  },
  { immediate: true },
)

watch(
  () => props.duplicateCandidateIds,
  (ids) => {
    if (!ids.includes(selectedCandidateId.value)) selectedCandidateId.value = ids[0] ?? ''
  },
  { immediate: true },
)

onUnmounted(() => {
  supportingController?.abort()
  writeController?.abort()
})
</script>

<template>
  <section class="page-stack" aria-label="发票写操作与审计">
    <div v-if="supportingLoading" class="section-card" role="status" aria-live="polite">
      正在加载发票证据与修正历史…
    </div>

    <div v-if="supportingErrorMessage" class="callout callout-danger" role="alert">
      <div>
        <strong>{{ supportingErrorMessage }}</strong>
        <span v-if="supportingErrorTraceId" class="mono-text"> Trace ID：{{ supportingErrorTraceId }}</span>
      </div>
      <button class="button button-secondary button-small" type="button" @click="emit('refreshRequested')">刷新详情</button>
    </div>

    <div v-if="!canManage" class="callout" role="note">
      <div><strong>只读模式</strong>当前账号没有发票管理权限，可查看证据和修正历史，但不能修改或处置。</div>
    </div>

    <div v-else class="section-card">
      <div class="section-card-header">
        <div><h2>人工操作</h2><p>所有写操作要求当前行版本、幂等键和人工原因，并写入追加式审计。</p></div>
      </div>
      <div class="section-card-body page-stack">
        <div class="form-field">
          <label for="invoice-write-reason">操作原因</label>
          <textarea
            id="invoice-write-reason"
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
          <button class="button button-secondary" type="button" :disabled="!canReplaceFacts || writing" @click="editing = !editing">
            {{ editing ? '收起事实修正' : '修正完整事实' }}
          </button>
          <button class="button button-primary" type="button" :disabled="!canDecide || !validReason || writing" data-testid="confirm-invoice" @click="decide('confirmed')">确认发票</button>
          <button class="button button-danger" type="button" :disabled="!canDecide || !validReason || writing" data-testid="reject-invoice" @click="decide('rejected')">拒绝发票</button>
          <button class="button button-secondary" type="button" :disabled="!canCheckDuplicate || !validReason || writing" data-testid="check-invoice-duplicate" @click="checkDuplicate">重新检测重复状态</button>
        </div>

        <template v-if="duplicateCandidateIds.length">
          <div class="form-field">
            <label for="invoice-duplicate-candidate">精确重复候选</label>
            <select id="invoice-duplicate-candidate" v-model="selectedCandidateId" :disabled="writing">
              <option v-for="candidateId in duplicateCandidateIds" :key="candidateId" :value="candidateId">{{ candidateId }}</option>
            </select>
          </div>
          <div class="inline-actions">
            <button class="button button-danger" type="button" :disabled="!canDecideDuplicate || !validReason || writing" data-testid="confirm-invoice-duplicate" @click="decideDuplicate('confirmed_duplicate')">确认重复</button>
            <button class="button button-secondary" type="button" :disabled="!canDecideDuplicate || !validReason || writing" data-testid="approve-invoice-duplicate-exception" @click="decideDuplicate('exception_approved')">批准例外</button>
          </div>
        </template>

        <div v-if="writeErrorMessage" class="callout callout-danger" role="alert">
          <div><strong>{{ writeErrorMessage }}</strong><span v-if="writeErrorTraceId" class="mono-text"> Trace ID：{{ writeErrorTraceId }}</span></div>
        </div>
        <div v-if="writeSuccessMessage" class="callout callout-success" role="status"><div><strong>{{ writeSuccessMessage }}</strong></div></div>
      </div>
    </div>

    <div v-if="editing && canReplaceFacts" class="section-card">
      <div class="section-card-header"><div><h2>完整事实修正</h2><p>提交会完整替换当前未确认事实；现有来源证据按字段和明细行原样保留。</p></div></div>
      <div class="section-card-body page-stack">
        <div class="callout callout-warning" role="note"><div>人工修正不改变来源文本。确认前仍由后端重新核验证据范围、核心字段完整性与金额恒等式。</div></div>
        <div class="form-grid">
          <div class="form-field"><label for="edit-invoice-code">发票代码</label><input id="edit-invoice-code" v-model.trim="form.invoiceCode" class="text-input" maxlength="50" /></div>
          <div class="form-field"><label for="edit-invoice-number">发票号码</label><input id="edit-invoice-number" v-model.trim="form.invoiceNumber" class="text-input" maxlength="50" /></div>
          <div class="form-field"><label for="edit-invoice-type">发票类型</label><input id="edit-invoice-type" v-model.trim="form.invoiceType" class="text-input" maxlength="40" /></div>
          <div class="form-field"><label for="edit-is-red-invoice">是否红字</label><select id="edit-is-red-invoice" v-model="form.isRedInvoice"><option value="">未识别</option><option value="false">否</option><option value="true">是</option></select></div>
          <div class="form-field"><label for="edit-invoice-date">开票日期</label><input id="edit-invoice-date" v-model="form.invoiceDate" class="text-input" type="date" /></div>
          <div class="form-field"><label for="edit-buyer-name">购买方</label><input id="edit-buyer-name" v-model.trim="form.buyerName" class="text-input" maxlength="300" /></div>
          <div class="form-field"><label for="edit-buyer-tax-no">购买方税号</label><input id="edit-buyer-tax-no" v-model.trim="form.buyerTaxNo" class="text-input" maxlength="32" /></div>
          <div class="form-field"><label for="edit-seller-name">销售方</label><input id="edit-seller-name" v-model.trim="form.sellerName" class="text-input" maxlength="300" /></div>
          <div class="form-field"><label for="edit-seller-tax-no">销售方税号</label><input id="edit-seller-tax-no" v-model.trim="form.sellerTaxNo" class="text-input" maxlength="32" /></div>
          <div class="form-field"><label for="edit-amount-excluding-tax">不含税金额</label><input id="edit-amount-excluding-tax" v-model.trim="form.amountExcludingTax" class="text-input" inputmode="decimal" /></div>
          <div class="form-field"><label for="edit-tax-amount">税额</label><input id="edit-tax-amount" v-model.trim="form.taxAmount" class="text-input" inputmode="decimal" /></div>
          <div class="form-field"><label for="edit-total-amount">价税合计</label><input id="edit-total-amount" v-model.trim="form.totalAmount" class="text-input" inputmode="decimal" /></div>
          <div class="form-field"><label for="edit-currency">币种</label><input id="edit-currency" v-model.trim="form.currency" class="text-input" maxlength="3" /></div>
        </div>

        <div v-for="item in form.items" :key="item.lineNo" class="evidence-card">
          <header><h3>明细行 {{ item.lineNo }}</h3><button class="button button-danger button-small" type="button" @click="removeItem(item.lineNo)">删除行</button></header>
          <div class="form-grid" style="margin-top: 12px">
            <div class="form-field"><label :for="`item-name-${item.lineNo}`">项目</label><input :id="`item-name-${item.lineNo}`" v-model="item.itemName" class="text-input" maxlength="500" /></div>
            <div class="form-field"><label :for="`item-spec-${item.lineNo}`">规格</label><input :id="`item-spec-${item.lineNo}`" v-model="item.specification" class="text-input" maxlength="300" /></div>
            <div class="form-field"><label :for="`item-unit-${item.lineNo}`">单位</label><input :id="`item-unit-${item.lineNo}`" v-model="item.unit" class="text-input" maxlength="50" /></div>
            <div class="form-field"><label :for="`item-quantity-${item.lineNo}`">数量</label><input :id="`item-quantity-${item.lineNo}`" v-model.trim="item.quantity" class="text-input" /></div>
            <div class="form-field"><label :for="`item-unit-price-${item.lineNo}`">单价</label><input :id="`item-unit-price-${item.lineNo}`" v-model.trim="item.unitPrice" class="text-input" /></div>
            <div class="form-field"><label :for="`item-net-${item.lineNo}`">不含税金额</label><input :id="`item-net-${item.lineNo}`" v-model.trim="item.amountExcludingTax" class="text-input" /></div>
            <div class="form-field"><label :for="`item-rate-${item.lineNo}`">税率</label><input :id="`item-rate-${item.lineNo}`" v-model.trim="item.taxRate" class="text-input" /></div>
            <div class="form-field"><label :for="`item-tax-${item.lineNo}`">税额</label><input :id="`item-tax-${item.lineNo}`" v-model.trim="item.taxAmount" class="text-input" /></div>
            <div class="form-field"><label :for="`item-total-${item.lineNo}`">价税合计</label><input :id="`item-total-${item.lineNo}`" v-model.trim="item.totalAmount" class="text-input" /></div>
          </div>
        </div>
        <div class="inline-actions">
          <button class="button button-secondary" type="button" @click="addItem">新增明细行</button>
          <button class="button button-primary" type="button" :disabled="!validReason || writing" data-testid="replace-invoice-facts" @click="replaceFacts">提交完整事实修正</button>
        </div>
      </div>
    </div>

    <div v-if="evidence" class="section-card">
      <div class="section-card-header"><div><h2>字段与明细证据</h2><p>证据版本 {{ evidence.rowVersion }}；当前字段证据 {{ evidence.fieldEvidence.length }} 条。</p></div></div>
      <div class="section-card-body">
        <div v-if="evidence.fieldEvidence.length" class="data-table-wrap">
          <table class="data-table"><thead><tr><th>字段</th><th>页码</th><th>引用文本</th><th>置信度</th><th>解析版本</th></tr></thead><tbody><tr v-for="item in evidence.fieldEvidence" :key="item.fieldCode"><td class="mono-text">{{ item.fieldCode }}</td><td>{{ item.evidence.pageNo }}</td><td>{{ item.evidence.quoteText }}</td><td>{{ item.evidence.confidence ?? '—' }}</td><td class="mono-text">{{ item.evidence.parseVersionId }}</td></tr></tbody></table>
        </div>
        <div v-else class="empty-inline">当前没有字段证据；后端不会允许缺失核心证据的确认。</div>
      </div>
    </div>

    <div v-if="history" class="section-card">
      <div class="section-card-header"><div><h2>发票修正与处置历史</h2><p>追加式记录事实替换、确认、拒绝和重复状态变更。</p></div></div>
      <div class="section-card-body">
        <div v-if="history.items.length" class="data-table-wrap">
          <table class="data-table"><thead><tr><th>字段路径</th><th>原因</th><th>Actor 角色</th><th>时间</th><th>Trace ID</th></tr></thead><tbody><tr v-for="item in history.items" :key="item.id"><td class="mono-text">{{ item.fieldPath }}</td><td>{{ item.reason }}</td><td>{{ item.actorRoleCode }}</td><td>{{ new Date(item.createdAt).toLocaleString('zh-CN', { hour12: false }) }}</td><td class="mono-text">{{ item.traceId }}</td></tr></tbody></table>
        </div>
        <div v-else class="empty-inline">尚无人工修正或处置历史。</div>
      </div>
    </div>
  </section>
</template>
