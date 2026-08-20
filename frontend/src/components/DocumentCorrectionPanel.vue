<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { ApiError } from '@/services/api'
import {
  documentCorrectionApi,
  type DocumentCorrectionBusinessType,
  type DocumentCorrectionAccepted,
  type DocumentCorrectionEvidence,
} from '@/services/documentCorrections'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  businessType: DocumentCorrectionBusinessType
  evidenceItems: readonly DocumentCorrectionEvidence[]
}>()
const emit = defineEmits<{ activated: [] }>()

const auth = useAuthStore()
const selectedIdentity = ref('')
const afterText = ref('')
const correctionReason = ref('')
const activationReason = ref('')
const candidate = ref<DocumentCorrectionAccepted | null>(null)
const candidateActivated = ref(false)
const loading = ref(false)
const message = ref('')
const errorMessage = ref('')
const errorTraceId = ref('')
let controller: AbortController | null = null
let correctionSignature = ''
let correctionKey = ''
let activationSignature = ''
let activationKey = ''

const uniqueEvidence = computed(() => {
  const byIdentity = new Map<string, DocumentCorrectionEvidence>()
  for (const item of props.evidenceItems) {
    const identity = `${item.parseVersionId}:${item.blockId}`
    if (!byIdentity.has(identity)) byIdentity.set(identity, item)
  }
  return [...byIdentity.values()].sort(
    (left, right) => left.pageNo - right.pageNo || left.blockId.localeCompare(right.blockId),
  )
})
const selectedEvidence = computed(
  () =>
    uniqueEvidence.value.find(
      (item) => `${item.parseVersionId}:${item.blockId}` === selectedIdentity.value,
    ) ?? null,
)
const hasPermission = computed(
  () =>
    auth.user?.permissions.some((permission) =>
      ['files.manage', 'system.configure'].includes(permission),
    ) ?? false,
)
const hasBusinessRole = computed(() => {
  const roles = auth.user?.roles ?? []
  const allowed: Readonly<Record<DocumentCorrectionBusinessType, readonly string[]>> = {
    contract: ['finance_reviewer', 'contract_admin', 'system_admin'],
    supplementary_agreement: ['contract_admin', 'system_admin'],
    invoice: ['finance_reviewer', 'system_admin'],
    policy: ['audit_reviewer', 'system_admin'],
  }
  return roles.some((role) => allowed[props.businessType].includes(role))
})
const canCorrect = computed(() => hasPermission.value && hasBusinessRole.value)
const validCorrection = computed(
  () =>
    selectedEvidence.value !== null &&
    afterText.value.length >= 1 &&
    afterText.value.length <= 1_000_000 &&
    correctionReason.value.length >= 1 &&
    correctionReason.value.length <= 1000 &&
    correctionReason.value === correctionReason.value.trim(),
)
const validActivation = computed(
  () =>
    candidate.value !== null &&
    !candidateActivated.value &&
    activationReason.value.length >= 1 &&
    activationReason.value.length <= 1000 &&
    activationReason.value === activationReason.value.trim(),
)

function clearFeedback(): void {
  message.value = ''
  errorMessage.value = ''
  errorTraceId.value = ''
}

function errorText(error: unknown, operation: 'correct' | 'activate'): string {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (!(error instanceof ApiError)) return '文档纠错响应校验失败，请刷新后重试。'
  if (error.code === 'PARSE_PARENT_STALE') return '来源解析版本已过期，请刷新证据后重新生成候选。'
  if (error.code === 'PARSE_STATE_CONFLICT') return '候选快照尚未完成，请等待 Worker 后再尝试激活。'
  if (error.code === 'PARSE_QUALITY_GATE_FAILED') return '候选未通过 Markdown 与来源映射质量门禁。'
  if (error.status === 403) return '当前账号缺少文档纠错权限或对应业务角色。'
  if (error.status === 404) return '来源块或解析版本已不可见。'
  if (error.status === 409) return operation === 'correct' ? '来源解析版本已变化，请刷新证据。' : '候选状态已变化，请刷新后核对。'
  if (error.status === 422) return '修正文本或原因不符合约束。'
  return '文档纠错服务暂不可用，请稍后重试。'
}

function nextKey(signature: string, operation: 'correct' | 'activate'): string {
  if (operation === 'correct') {
    if (correctionSignature !== signature) {
      correctionSignature = signature
      correctionKey = `document-correction.${crypto.randomUUID()}`
    }
    return correctionKey
  }
  if (activationSignature !== signature) {
    activationSignature = signature
    activationKey = `document-activation.${crypto.randomUUID()}`
  }
  return activationKey
}

async function submitCorrection(): Promise<void> {
  const evidence = selectedEvidence.value
  if (!canCorrect.value || !validCorrection.value || evidence === null || loading.value) return
  clearFeedback()
  const signature = JSON.stringify({
    blockId: evidence.blockId,
    sourceParseVersionId: evidence.parseVersionId,
    afterText: afterText.value,
    reason: correctionReason.value,
  })
  const activeController = new AbortController()
  controller = activeController
  loading.value = true
  try {
    const result = await documentCorrectionApi.correctBlock(
      evidence.blockId,
      {
        fieldName: 'text_content',
        afterValue: afterText.value,
        reason: correctionReason.value,
        sourceParseVersionId: evidence.parseVersionId,
      },
      nextKey(signature, 'correct'),
      activeController.signal,
    )
    if (controller !== activeController || activeController.signal.aborted) return
    candidate.value = result
    candidateActivated.value = false
    activationReason.value = correctionReason.value
    message.value = '候选快照已排队；当前活动解析版本尚未改变。'
  } catch (error) {
    if (controller === activeController && !activeController.signal.aborted) {
      errorMessage.value = errorText(error, 'correct')
    }
  } finally {
    if (controller === activeController) {
      controller = null
      loading.value = false
    }
  }
}

async function activateCandidate(): Promise<void> {
  const current = candidate.value
  if (!canCorrect.value || !validActivation.value || current === null || loading.value) return
  clearFeedback()
  const signature = JSON.stringify({
    parseVersionId: current.resultParseVersionId,
    reason: activationReason.value,
  })
  const activeController = new AbortController()
  controller = activeController
  loading.value = true
  try {
    await documentCorrectionApi.activateParse(
      current.resultParseVersionId,
      activationReason.value,
      nextKey(signature, 'activate'),
      activeController.signal,
    )
    if (controller !== activeController || activeController.signal.aborted) return
    candidateActivated.value = true
    message.value = '候选解析版本已独立激活，旧版本保留为可追溯历史。'
    emit('activated')
  } catch (error) {
    if (controller === activeController && !activeController.signal.aborted) {
      errorMessage.value = errorText(error, 'activate')
    }
  } finally {
    if (controller === activeController) {
      controller = null
      loading.value = false
    }
  }
}

watch(selectedEvidence, (value) => {
  controller?.abort()
  controller = null
  afterText.value = value?.quoteText ?? ''
  correctionReason.value = ''
  activationReason.value = ''
  candidate.value = null
  candidateActivated.value = false
  correctionSignature = ''
  correctionKey = ''
  activationSignature = ''
  activationKey = ''
  loading.value = false
  clearFeedback()
})
watch(uniqueEvidence, (items) => {
  if (
    selectedIdentity.value &&
    !items.some((item) => `${item.parseVersionId}:${item.blockId}` === selectedIdentity.value)
  ) {
    selectedIdentity.value = ''
  }
})
onUnmounted(() => controller?.abort())
</script>

<template>
  <div class="section-card" data-testid="document-correction-panel">
    <div class="section-card-header">
      <div>
        <h2>来源文本纠错</h2>
        <p>从当前业务证据选择结构块；创建候选与激活是两个独立动作，不自动发送第二步。</p>
      </div>
    </div>
    <div class="section-card-body page-stack">
      <div v-if="!canCorrect" class="callout" role="note"><div>当前账号缺少 files.manage/system.configure 或对应业务角色，只能查看现有证据。</div></div>
      <div v-else-if="!uniqueEvidence.length" class="empty-inline">当前没有可定位到 Parse 与 Block 的业务证据，不能安全发起纠错。</div>
      <template v-else>
        <div class="form-grid">
          <div class="form-field form-field-full">
            <label for="document-correction-source">来源结构块</label>
            <select id="document-correction-source" v-model="selectedIdentity" :disabled="loading || candidate !== null">
              <option value="">请选择来源证据</option>
              <option v-for="item in uniqueEvidence" :key="`${item.parseVersionId}:${item.blockId}`" :value="`${item.parseVersionId}:${item.blockId}`">
                第 {{ item.pageNo }} 页 · {{ item.quoteText.slice(0, 80) }}
              </option>
            </select>
          </div>
          <div class="form-field form-field-full">
            <label for="document-correction-text">修正后的块文本</label>
            <textarea id="document-correction-text" v-model="afterText" rows="5" maxlength="1000000" :disabled="loading || candidate !== null" />
          </div>
          <div class="form-field form-field-full">
            <label for="document-correction-reason">纠错原因</label>
            <textarea id="document-correction-reason" v-model="correctionReason" rows="3" maxlength="1000" :disabled="loading || candidate !== null" />
          </div>
        </div>
        <div v-if="candidate" class="callout" role="status">
          <div>
            <strong>候选 {{ candidate.resultParseVersionId }}</strong>
            <span class="mono-text"> Job：{{ candidate.jobId }}</span>
          </div>
        </div>
        <div v-if="candidate && !candidateActivated" class="form-field">
          <label for="document-activation-reason">独立激活原因</label>
          <textarea id="document-activation-reason" v-model="activationReason" rows="3" maxlength="1000" :disabled="loading" />
          <span class="form-help">Worker 完成候选快照后才可激活；过早提交会保持旧活动版本并返回状态冲突。</span>
        </div>
        <div v-if="message" class="callout callout-success" role="status"><div><strong>{{ message }}</strong></div></div>
        <div v-if="errorMessage" class="callout callout-danger" role="alert"><div><strong>{{ errorMessage }}</strong><span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span></div></div>
        <div class="inline-actions">
          <button v-if="!candidate" class="button button-secondary" type="button" data-testid="submit-document-correction" :disabled="loading || !validCorrection" @click="submitCorrection">创建候选快照</button>
          <button v-else-if="!candidateActivated" class="button button-primary" type="button" data-testid="activate-document-correction" :disabled="loading || !validActivation" @click="activateCandidate">尝试独立激活</button>
        </div>
      </template>
    </div>
  </div>
</template>
