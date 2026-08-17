<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import {
  supplierApi,
  type Supplier,
  type SupplierCandidateUpdateInput,
} from '@/services/suppliers'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const supplier = ref<Supplier | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const mutating = ref(false)
const mutationError = ref('')
const mutationTraceId = ref('')
const successMessage = ref('')
const form = reactive({ standardName: '', taxNumber: '', reason: '' })
let requestController: AbortController | null = null
let mutationController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const supplierId = computed(() =>
  typeof route.params.supplierId === 'string' ? route.params.supplierId : '',
)
const canCorrect = computed(
  () =>
    auth.hasAllPermissions(['suppliers.correct']) &&
    supplier.value?.confirmationStatus === 'unconfirmed' &&
    supplier.value.status === 'candidate',
)
const sourceLabel = computed(() => {
  if (!supplier.value) return '—'
  if (supplier.value.sourceType === 'contract') return '合同乙方'
  if (supplier.value.sourceType === 'invoice') return '发票销售方'
  return '人工创建'
})
const sourceRoute = computed(() => {
  if (supplier.value?.sourceContractId) {
    return { name: 'contract-detail', params: { contractId: supplier.value.sourceContractId } }
  }
  if (supplier.value?.sourceInvoiceId) {
    return { name: 'invoice-detail', params: { invoiceId: supplier.value.sourceInvoiceId } }
  }
  return null
})
const fieldsChanged = computed(
  () =>
    supplier.value !== null &&
    (form.standardName.trim() !== supplier.value.standardName ||
      (form.taxNumber.trim() || null) !== supplier.value.taxNumber),
)
const validReason = computed(() => form.reason.trim().length >= 1 && form.reason.trim().length <= 1000)

function applySupplier(value: Supplier): void {
  supplier.value = value
  form.standardName = value.standardName
  form.taxNumber = value.taxNumber ?? ''
  form.reason = ''
}

function formatLoadError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '供应商不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取供应商详情。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '供应商详情加载失败，请稍后重试。'
  }
}

async function loadSupplier(): Promise<void> {
  requestController?.abort()
  supplier.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  mutationError.value = ''
  successMessage.value = ''
  const targetId = supplierId.value
  if (!UUID_PATTERN.test(targetId)) {
    errorMessage.value = '供应商标识无效，未向服务器发送请求。'
    return
  }
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await supplierApi.getDetail(targetId, controller.signal)
    if (requestController === controller && !controller.signal.aborted && supplierId.value === targetId) {
      applySupplier(response)
    }
  } catch (error) {
    if (requestController === controller && !controller.signal.aborted) formatLoadError(error)
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
    pendingIdempotencyKey = `supplier-update.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

function formatMutationError(error: unknown): void {
  mutationTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 409) {
    mutationError.value = '供应商、来源或数据版本已变化，请刷新后重新核对。'
  } else if (error instanceof ApiError && error.status === 403) {
    mutationError.value = '当前账号无权修正供应商候选。'
  } else if (error instanceof ApiError && error.status === 422) {
    mutationError.value = '名称、税务身份、决定或原因不符合约束。'
  } else {
    mutationError.value = '供应商操作失败；可直接重试，系统会复用同一幂等键。'
  }
}

async function mutate(decision?: 'confirmed' | 'rejected'): Promise<void> {
  const current = supplier.value
  if (!current || !canCorrect.value || !validReason.value || (!decision && !fieldsChanged.value)) return
  const input: SupplierCandidateUpdateInput = {
    rowVersion: current.rowVersion,
    reason: form.reason.trim(),
  }
  const standardName = form.standardName.trim()
  const taxNumber = form.taxNumber.trim()
  if (standardName !== current.standardName) input.standardName = standardName
  if ((taxNumber || null) !== current.taxNumber && taxNumber) input.taxNumber = taxNumber
  if (decision) input.decision = decision

  const signature = JSON.stringify(input)
  mutationError.value = ''
  mutationTraceId.value = ''
  successMessage.value = ''
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    const result = await supplierApi.updateCandidate(
      current.id,
      input,
      idempotencyKey(signature),
      controller.signal,
    )
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    successMessage.value = result.reused
      ? '候选已处理，来源已关联到同税务身份的活动供应商。'
      : decision === 'confirmed'
        ? '供应商候选已确认并激活。'
        : decision === 'rejected'
          ? '供应商候选已拒绝并失活。'
          : '供应商候选字段已保存。'
    if (result.supplier.id !== supplierId.value) {
      await router.replace({ name: 'supplier-detail', params: { supplierId: result.supplier.id } })
    } else {
      applySupplier(result.supplier)
    }
  } catch (error) {
    if (mutationController === controller && !controller.signal.aborted) formatMutationError(error)
  } finally {
    if (mutationController === controller) {
      mutationController = null
      mutating.value = false
    }
  }
}

watch(supplierId, loadSupplier, { immediate: true })
onUnmounted(() => {
  requestController?.abort()
  mutationController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="BETA-VS-03"
      :title="supplier?.standardName || '供应商详情'"
      :description="supplier ? `${sourceLabel} · ${supplier.id}` : '供应商事实与人工处理视图'"
      :status="supplier?.status || ''"
      :status-label="supplier?.status === 'inactive' ? '已失活' : ''"
    >
      <template v-if="supplier" #meta>
        <span><strong>确认状态：</strong>{{ supplier.confirmationStatus === 'unconfirmed' ? '待确认' : supplier.confirmationStatus === 'confirmed' ? '已确认' : '已拒绝' }}</span>
        <span><strong>数据版本：</strong>{{ supplier.rowVersion }}</span>
      </template>
      <template #actions>
        <RouterLink class="button button-secondary" :to="{ name: 'suppliers' }">返回列表</RouterLink>
        <RouterLink v-if="sourceRoute" class="button button-primary" :to="sourceRoute">查看来源</RouterLink>
      </template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载供应商详情…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示供应商详情">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="button" data-testid="retry-supplier" @click="loadSupplier">重试</button>
      </div>
    </SectionCard>

    <template v-else-if="supplier">
      <SectionCard title="当前供应商事实" description="名称不作为硬身份；税务身份只使用后端返回的统一公开值。">
        <div class="field-grid">
          <div class="field-item"><span class="field-label">标准名称</span><strong class="field-value">{{ supplier.standardName }}</strong></div>
          <div class="field-item"><span class="field-label">税务身份</span><strong class="field-value mono-text">{{ supplier.taxNumber || '—' }}</strong></div>
          <div class="field-item"><span class="field-label">来源类型</span><strong class="field-value">{{ sourceLabel }}</strong></div>
          <div class="field-item"><span class="field-label">确认 / 业务状态</span><div class="inline-actions"><StatusTag :status="supplier.confirmationStatus" :label="supplier.confirmationStatus === 'unconfirmed' ? '待确认' : undefined" /><StatusTag :status="supplier.status" :label="supplier.status === 'inactive' ? '已失活' : undefined" /></div></div>
          <div class="field-item"><span class="field-label">确认人</span><strong class="field-value mono-text">{{ supplier.confirmedBy || '—' }}</strong></div>
          <div class="field-item"><span class="field-label">确认时间</span><strong class="field-value numeric-text">{{ supplier.confirmedAt || '—' }}</strong></div>
        </div>
      </SectionCard>

      <div v-if="successMessage" class="callout callout-success" role="status"><div>{{ successMessage }}</div></div>

      <SectionCard v-if="canCorrect" title="人工处理候选" description="修改、决定和来源回填由后端在同一事务中校验版本并追加纠错与操作日志。">
        <form class="form-grid" @submit.prevent="mutate()">
          <label class="form-field" for="supplier-standard-name"><span>标准名称</span><input id="supplier-standard-name" v-model="form.standardName" maxlength="300" required /></label>
          <label class="form-field" for="supplier-tax-number"><span>税务身份</span><input id="supplier-tax-number" v-model="form.taxNumber" maxlength="32" autocomplete="off" /></label>
          <label class="form-field form-field-wide" for="supplier-reason"><span>处理原因</span><textarea id="supplier-reason" v-model="form.reason" maxlength="1000" required /></label>
          <div v-if="mutationError" class="callout callout-danger" role="alert"><div><strong>{{ mutationError }}</strong><span v-if="mutationTraceId" class="mono-text"> Trace ID：{{ mutationTraceId }}</span></div></div>
          <div class="form-actions">
            <button class="button button-secondary" type="submit" data-testid="save-supplier" :disabled="mutating || !validReason || !fieldsChanged">保存字段</button>
            <button class="button button-secondary" type="button" data-testid="reject-supplier" :disabled="mutating || !validReason" @click="mutate('rejected')">拒绝候选</button>
            <button class="button button-primary" type="button" data-testid="confirm-supplier" :disabled="mutating || !validReason" @click="mutate('confirmed')">确认并激活</button>
          </div>
        </form>
      </SectionCard>

      <SectionCard v-else title="供应商处理状态">
        <div class="callout"><div>{{ supplier.status === 'candidate' ? '当前账号没有供应商修正权限，只能查看候选事实。' : '该供应商已完成人工处理；P0 不允许通过候选接口重新修改或激活。' }}</div></div>
      </SectionCard>
    </template>
  </section>
</template>
