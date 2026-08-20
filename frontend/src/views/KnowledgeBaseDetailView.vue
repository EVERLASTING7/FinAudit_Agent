<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import PageTabs from '@/components/PageTabs.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError, UUID_PATTERN } from '@/services/api'
import { fileApi, type FileListItem } from '@/services/files'
import {
  knowledgeApi,
  type KnowledgeBase,
  type KnowledgeIndexVersion,
} from '@/services/knowledge'
import {
  policyApi,
  type PendingPolicyRevocationItem,
  type PendingPolicyRevocationListData,
  type PolicyCreateInput,
  type PolicyDocument,
  type PolicyListData,
} from '@/services/policies'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const knowledgeBase = ref<KnowledgeBase | null>(null)
const policyResult = ref<PolicyListData | null>(null)
const pendingRevocations = ref<PendingPolicyRevocationListData | null>(null)
const policyFiles = ref<FileListItem[]>([])
const indexVersion = ref<KnowledgeIndexVersion | null>(null)
const loading = ref(false)
const loadError = ref('')
const loadTraceId = ref('')
const policyLoading = ref(false)
const policyError = ref('')
const policyTraceId = ref('')
const pendingRevocationLoading = ref(false)
const pendingRevocationError = ref('')
const pendingRevocationTraceId = ref('')
const currentPendingRevocationPage = ref(1)
const requestedPendingRevocationPage = ref(1)
const requestedPendingRevocationCursor = ref<string | undefined>()
const pendingRevocationCursorStack = ref<Array<string | undefined>>([undefined])
const currentPolicyPage = ref(1)
const requestedPolicyPage = ref(1)
const requestedPolicyCursor = ref<string | undefined>()
const policyCursorStack = ref<Array<string | undefined>>([undefined])
const activeTab = ref('overview')
const showCreateForm = ref(false)
const mutating = ref(false)
const mutationError = ref('')
const mutationTraceId = ref('')
const mutationSuccess = ref('')
const transitionReasons = reactive<Record<string, string>>({})
const revocationExecutionReasons = reactive<Record<string, string>>({})
const createForm = reactive({
  sourceFileId: '',
  policyCode: '',
  name: '',
  version: '',
  issuingDepartment: '',
  effectiveFrom: new Date().toISOString().slice(0, 10),
  effectiveTo: '',
})
const indexReason = ref('')
let loadController: AbortController | null = null
let policyController: AbortController | null = null
let pendingRevocationController: AbortController | null = null
let mutationController: AbortController | null = null
let indexController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const knowledgeBaseId = computed(() => typeof route.params.kbId === 'string' ? route.params.kbId : '')
const canSubmit = computed(() => auth.hasAllPermissions(['knowledge.submit']))
const canApprove = computed(() => auth.hasAllPermissions(['knowledge.approve']))
const canPublish = computed(() => auth.hasAllPermissions(['knowledge.publish']))
const canRequestRevocation = computed(
  () => canApprove.value && auth.user?.roles.includes('audit_reviewer') === true,
)
const canExecuteRevocation = computed(
  () => canPublish.value && auth.user?.roles.includes('system_admin') === true,
)
const canReadPendingRevocations = computed(
  () => canRequestRevocation.value || canExecuteRevocation.value,
)
const tabs = computed(() => [
  { id: 'overview', label: '概览' },
  { id: 'policies', label: '制度文档', count: policyResult.value?.items.length },
  ...(canPublish.value ? [{ id: 'index', label: '索引构建' }] : []),
])
const createReady = computed(
  () =>
    canSubmit.value &&
    UUID_PATTERN.test(createForm.sourceFileId) &&
    createForm.policyCode.trim().length >= 1 &&
    createForm.name.trim().length >= 1 &&
    createForm.version.trim().length >= 1 &&
    /^\d{4}-\d{2}-\d{2}$/.test(createForm.effectiveFrom) &&
    !mutating.value,
)

function policyStatusLabel(status: PolicyDocument['status']): string | undefined {
  if (status === 'submitted') return '待业务批准'
  if (status === 'business_approved') return '业务已批准'
  return undefined
}

function formatLoadError(error: unknown): void {
  loadTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 404) {
    loadError.value = '知识库不存在，或当前账号无权访问。'
  } else if (error instanceof ApiError && error.status === 403) {
    loadError.value = '当前账号无权读取知识库。'
  } else {
    loadError.value = '知识库详情加载失败，请稍后重试。'
  }
}

async function loadKnowledgeBase(): Promise<void> {
  loadController?.abort()
  knowledgeBase.value = null
  loadError.value = ''
  loadTraceId.value = ''
  const targetId = knowledgeBaseId.value
  if (!UUID_PATTERN.test(targetId)) {
    loadError.value = '知识库标识无效，未向服务器发送请求。'
    return
  }
  const controller = new AbortController()
  loadController = controller
  loading.value = true
  try {
    const response = await knowledgeApi.getDetail(targetId, controller.signal)
    if (loadController === controller && !controller.signal.aborted && knowledgeBaseId.value === targetId) {
      knowledgeBase.value = response
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

async function loadPolicyPage(cursor: string | undefined, page: number): Promise<void> {
  policyController?.abort()
  policyResult.value = null
  policyError.value = ''
  policyTraceId.value = ''
  requestedPolicyCursor.value = cursor
  requestedPolicyPage.value = page
  const targetId = knowledgeBaseId.value
  if (!UUID_PATTERN.test(targetId)) return
  const controller = new AbortController()
  policyController = controller
  policyLoading.value = true
  try {
    const response = await policyApi.list(20, cursor, targetId, controller.signal)
    if (policyController === controller && !controller.signal.aborted && knowledgeBaseId.value === targetId) {
      policyResult.value = response
      currentPolicyPage.value = page
    }
  } catch (error) {
    if (policyController !== controller || controller.signal.aborted) return
    policyTraceId.value = error instanceof ApiError ? error.traceId : ''
    policyError.value = error instanceof ApiError && error.status === 403
      ? '当前账号无权读取制度文档。'
      : '制度文档加载失败，请稍后重试。'
  } finally {
    if (policyController === controller) {
      policyController = null
      policyLoading.value = false
    }
  }
}

async function loadPendingRevocationPage(
  cursor: string | undefined,
  page: number,
): Promise<void> {
  pendingRevocationController?.abort()
  pendingRevocations.value = null
  pendingRevocationError.value = ''
  pendingRevocationTraceId.value = ''
  requestedPendingRevocationCursor.value = cursor
  requestedPendingRevocationPage.value = page
  const targetId = knowledgeBaseId.value
  if (!canReadPendingRevocations.value || !UUID_PATTERN.test(targetId)) return
  const controller = new AbortController()
  pendingRevocationController = controller
  pendingRevocationLoading.value = true
  try {
    const response = await policyApi.listPendingRevocations(targetId, 50, cursor, controller.signal)
    if (
      pendingRevocationController === controller &&
      !controller.signal.aborted &&
      knowledgeBaseId.value === targetId
    ) {
      pendingRevocations.value = response
      currentPendingRevocationPage.value = page
    }
  } catch (error) {
    if (pendingRevocationController !== controller || controller.signal.aborted) return
    pendingRevocationTraceId.value = error instanceof ApiError ? error.traceId : ''
    pendingRevocationError.value =
      error instanceof ApiError && error.status === 403
        ? '当前账号无权读取制度撤销待办。'
        : '制度撤销待办加载失败，请稍后重试。'
  } finally {
    if (pendingRevocationController === controller) {
      pendingRevocationController = null
      pendingRevocationLoading.value = false
    }
  }
}

async function loadPolicyFiles(): Promise<void> {
  if (!canSubmit.value || !UUID_PATTERN.test(knowledgeBaseId.value)) return
  try {
    const page = await fileApi.list(100)
    policyFiles.value = page.items.filter(
      (item) =>
        item.intendedBusinessType === 'policy' &&
        item.targetKnowledgeBaseId === knowledgeBaseId.value &&
        item.status === 'stored' &&
        item.jobStatus === 'succeeded',
    )
  } catch {
    policyFiles.value = []
  }
}

async function loadIndexFromRoute(): Promise<void> {
  indexController?.abort()
  indexVersion.value = null
  if (!canPublish.value) return
  const raw = route.query.index_version_id
  const indexId = typeof raw === 'string' ? raw : ''
  if (!UUID_PATTERN.test(indexId) || !UUID_PATTERN.test(knowledgeBaseId.value)) return
  const controller = new AbortController()
  indexController = controller
  try {
    const response = await knowledgeApi.getIndex(knowledgeBaseId.value, indexId, controller.signal)
    if (indexController === controller && !controller.signal.aborted) indexVersion.value = response
  } catch (error) {
    if (indexController !== controller || controller.signal.aborted) return
    mutationTraceId.value = error instanceof ApiError ? error.traceId : ''
    mutationError.value = '索引版本加载失败，请核对标识或稍后重试。'
  } finally {
    if (indexController === controller) indexController = null
  }
}

function nextPolicyPage(): void {
  if (!policyResult.value?.nextCursor) return
  const cursor = policyResult.value.nextCursor
  policyCursorStack.value = [...policyCursorStack.value.slice(0, currentPolicyPage.value), cursor]
  void loadPolicyPage(cursor, currentPolicyPage.value + 1)
}

function previousPolicyPage(): void {
  if (currentPolicyPage.value <= 1) return
  const page = currentPolicyPage.value - 1
  policyCursorStack.value = policyCursorStack.value.slice(0, page)
  void loadPolicyPage(policyCursorStack.value[page - 1], page)
}

function nextPendingRevocationPage(): void {
  if (!pendingRevocations.value?.nextCursor) return
  const cursor = pendingRevocations.value.nextCursor
  pendingRevocationCursorStack.value = [
    ...pendingRevocationCursorStack.value.slice(0, currentPendingRevocationPage.value),
    cursor,
  ]
  void loadPendingRevocationPage(cursor, currentPendingRevocationPage.value + 1)
}

function previousPendingRevocationPage(): void {
  if (currentPendingRevocationPage.value <= 1) return
  const page = currentPendingRevocationPage.value - 1
  pendingRevocationCursorStack.value = pendingRevocationCursorStack.value.slice(0, page)
  void loadPendingRevocationPage(pendingRevocationCursorStack.value[page - 1], page)
}

function nextIdempotencyKey(signature: string, prefix: string): string {
  if (pendingSignature !== signature) {
    pendingSignature = signature
    pendingIdempotencyKey = `${prefix}.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

function formatMutationError(error: unknown): void {
  mutationTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 409) {
    mutationError.value = '制度、索引、职责分离或质量门禁状态已变化，请刷新后核对。'
  } else if (error instanceof ApiError && error.status === 403) {
    mutationError.value = '当前账号没有执行该知识管理动作的权限。'
  } else if (error instanceof ApiError && error.status === 422) {
    mutationError.value = '提交字段不符合当前知识管理合同。'
  } else {
    mutationError.value = '知识管理操作失败；可直接重试，系统会复用同一幂等键。'
  }
}

function resetMutationMessages(): void {
  mutationError.value = ''
  mutationTraceId.value = ''
  mutationSuccess.value = ''
}

async function createPolicy(): Promise<void> {
  if (!createReady.value) return
  const input: PolicyCreateInput = {
    knowledgeBaseId: knowledgeBaseId.value,
    sourceFileId: createForm.sourceFileId,
    policyCode: createForm.policyCode.trim(),
    name: createForm.name.trim(),
    version: createForm.version.trim(),
    issuingDepartment: createForm.issuingDepartment.trim() || null,
    effectiveFrom: createForm.effectiveFrom,
    effectiveTo: createForm.effectiveTo || null,
    scope: {},
  }
  const signature = JSON.stringify(input)
  resetMutationMessages()
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    const response = await policyApi.create(input, nextIdempotencyKey(signature, 'policy-create'), controller.signal)
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    mutationSuccess.value = `制度草稿 ${response.policy.policyCode} 已创建。`
    showCreateForm.value = false
    await loadPolicyPage(undefined, 1)
  } catch (error) {
    if (mutationController === controller && !controller.signal.aborted) formatMutationError(error)
  } finally {
    if (mutationController === controller) {
      mutationController = null
      mutating.value = false
    }
  }
}

async function transitionPolicy(policy: PolicyDocument, action: 'submit-review' | 'approve' | 'publish'): Promise<void> {
  const reason = (transitionReasons[policy.id] ?? '').trim()
  if (!reason || mutating.value) return
  const signature = JSON.stringify({ policyId: policy.id, action, rowVersion: policy.rowVersion, reason })
  resetMutationMessages()
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    const response = await policyApi.transition(
      policy.id,
      action,
      policy.rowVersion,
      reason,
      nextIdempotencyKey(signature, 'policy-transition'),
      controller.signal,
    )
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    transitionReasons[policy.id] = ''
    mutationSuccess.value = `制度 ${response.policy.policyCode} 已推进到 ${policyStatusLabel(response.policy.status) ?? response.policy.status}。`
    if (policyResult.value) {
      policyResult.value = {
        ...policyResult.value,
        items: policyResult.value.items.map((item) => item.id === response.policy.id ? response.policy : item),
      }
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

async function requestPolicyRevocation(policy: PolicyDocument): Promise<void> {
  const reason = (transitionReasons[policy.id] ?? '').trim()
  if (!canRequestRevocation.value || !reason || mutating.value) return
  const signature = JSON.stringify({
    action: 'request-revocation',
    policyId: policy.id,
    rowVersion: policy.rowVersion,
    reason,
  })
  resetMutationMessages()
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    await policyApi.requestRevocation(
      policy.id,
      policy.rowVersion,
      reason,
      nextIdempotencyKey(signature, 'policy-revocation-request'),
      controller.signal,
    )
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    transitionReasons[policy.id] = ''
    await loadPendingRevocationPage(undefined, 1)
    mutationSuccess.value = `制度 ${policy.policyCode} 的撤销确认已提交，等待系统管理员独立执行。`
  } catch (error) {
    if (mutationController === controller && !controller.signal.aborted) formatMutationError(error)
  } finally {
    if (mutationController === controller) {
      mutationController = null
      mutating.value = false
    }
  }
}

async function revokePolicy(request: PendingPolicyRevocationItem): Promise<void> {
  const reason = (revocationExecutionReasons[request.revocationRequestId] ?? '').trim()
  if (
    !canExecuteRevocation.value ||
    !reason ||
    mutating.value
  ) return
  const signature = JSON.stringify({
    action: 'revoke',
    policyId: request.policyId,
    rowVersion: request.policyRowVersion,
    revocationRequestId: request.revocationRequestId,
    reason,
  })
  resetMutationMessages()
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    const response = await policyApi.revoke(
      request.policyId,
      request.policyRowVersion,
      request.revocationRequestId,
      reason,
      nextIdempotencyKey(signature, 'policy-revoke'),
      controller.signal,
    )
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    revocationExecutionReasons[request.revocationRequestId] = ''
    mutationSuccess.value = `制度 ${response.policy.policyCode} 已撤销，新检索将立即排除该制度。`
    if (policyResult.value) {
      policyResult.value = {
        ...policyResult.value,
        items: policyResult.value.items.map((item) =>
          item.id === response.policy.id ? response.policy : item,
        ),
      }
    }
    await loadPendingRevocationPage(undefined, 1)
  } catch (error) {
    if (mutationController === controller && !controller.signal.aborted) formatMutationError(error)
  } finally {
    if (mutationController === controller) {
      mutationController = null
      mutating.value = false
    }
  }
}

async function buildIndex(): Promise<void> {
  if (!canPublish.value || mutating.value) return
  const signature = JSON.stringify({ action: 'build-index', knowledgeBaseId: knowledgeBaseId.value })
  resetMutationMessages()
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    const response = await knowledgeApi.buildIndex(
      knowledgeBaseId.value,
      nextIdempotencyKey(signature, 'knowledge-index-build'),
      controller.signal,
    )
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    indexVersion.value = response
    mutationSuccess.value = `索引候选 V${response.versionNo} 已创建，Job 状态为 ${response.jobStatus ?? '—'}。`
    await router.replace({ query: { ...route.query, index_version_id: response.id } })
  } catch (error) {
    if (mutationController === controller && !controller.signal.aborted) formatMutationError(error)
  } finally {
    if (mutationController === controller) {
      mutationController = null
      mutating.value = false
    }
  }
}

async function refreshIndex(): Promise<void> {
  if (!indexVersion.value) return
  await router.replace({ query: { ...route.query, index_version_id: indexVersion.value.id } })
  await loadIndexFromRoute()
}

async function activateIndex(): Promise<void> {
  const current = indexVersion.value
  const reason = indexReason.value.trim()
  if (!current || current.status !== 'ready' || !reason || mutating.value) return
  const signature = JSON.stringify({ action: 'activate-index', indexId: current.id, rowVersion: current.rowVersion, reason })
  resetMutationMessages()
  const controller = new AbortController()
  mutationController = controller
  mutating.value = true
  try {
    const response = await knowledgeApi.activateIndex(
      knowledgeBaseId.value,
      current.id,
      current.rowVersion,
      reason,
      nextIdempotencyKey(signature, 'knowledge-index-activate'),
      controller.signal,
    )
    if (mutationController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    indexVersion.value = response
    indexReason.value = ''
    mutationSuccess.value = `索引 V${response.versionNo} 已激活。`
  } catch (error) {
    if (mutationController === controller && !controller.signal.aborted) formatMutationError(error)
  } finally {
    if (mutationController === controller) {
      mutationController = null
      mutating.value = false
    }
  }
}

async function loadAll(): Promise<void> {
  policyCursorStack.value = [undefined]
  currentPolicyPage.value = 1
  pendingRevocationCursorStack.value = [undefined]
  currentPendingRevocationPage.value = 1
  await Promise.all([
    loadKnowledgeBase(),
    loadPolicyPage(undefined, 1),
    loadPendingRevocationPage(undefined, 1),
    loadPolicyFiles(),
  ])
  await loadIndexFromRoute()
}

watch(knowledgeBaseId, loadAll, { immediate: true })
watch(() => route.query.index_version_id, loadIndexFromRoute)
onUnmounted(() => {
  loadController?.abort()
  policyController?.abort()
  pendingRevocationController?.abort()
  mutationController?.abort()
  indexController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader ui-code="UI-009" :title="knowledgeBase?.name || '知识库详情'" :description="knowledgeBase ? `${knowledgeBase.code} · ${knowledgeBase.id}` : '制度、索引与问答入口'" :status="knowledgeBase?.status || ''">
      <template v-if="knowledgeBase" #meta><span><strong>默认 Top-K：</strong>{{ knowledgeBase.defaultTopK }}</span><span><strong>数据版本：</strong>{{ knowledgeBase.rowVersion }}</span></template>
      <template #actions><RouterLink class="button button-secondary" :to="{ name: 'knowledge-bases' }">返回目录</RouterLink><RouterLink v-if="knowledgeBase?.status === 'active'" class="button button-primary" :to="{ name: 'qa', query: { knowledge_base_id: knowledgeBase.id } }">使用制度问答</RouterLink></template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载知识库详情…</div>
    <SectionCard v-else-if="loadError" title="无法显示知识库详情"><div class="callout callout-danger" role="alert"><div><strong>{{ loadError }}</strong><span v-if="loadTraceId" class="mono-text"> Trace ID：{{ loadTraceId }}</span></div></div><div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-knowledge-detail" @click="loadAll">重试</button></div></SectionCard>

    <template v-else-if="knowledgeBase">
      <PageTabs v-model="activeTab" :items="tabs" label="知识库详情标签" />
      <div v-if="mutationError" class="callout callout-danger" role="alert"><div><strong>{{ mutationError }}</strong><span v-if="mutationTraceId" class="mono-text"> Trace ID：{{ mutationTraceId }}</span></div></div>
      <div v-if="mutationSuccess" class="callout callout-success" role="status"><div>{{ mutationSuccess }}</div></div>

      <div v-if="activeTab === 'overview'" id="overview-panel" class="tab-panel page-stack" role="tabpanel" aria-labelledby="overview-tab">
        <SectionCard title="知识库事实" description="本页只展示 PostgreSQL 当前目录事实，不把制度数量、索引或评测状态合并成推测摘要。">
          <div class="field-grid"><div class="field-item"><span class="field-label">代码</span><strong class="field-value mono-text">{{ knowledgeBase.code }}</strong></div><div class="field-item"><span class="field-label">名称</span><strong class="field-value">{{ knowledgeBase.name }}</strong></div><div class="field-item"><span class="field-label">说明</span><strong class="field-value">{{ knowledgeBase.description || '—' }}</strong></div><div class="field-item"><span class="field-label">状态</span><StatusTag :status="knowledgeBase.status" /></div><div class="field-item"><span class="field-label">默认 Top-K</span><strong class="field-value numeric-text">{{ knowledgeBase.defaultTopK }}</strong></div><div class="field-item"><span class="field-label">相似度阈值</span><strong class="field-value">未设置</strong></div></div>
        </SectionCard>
        <SectionCard title="安全边界"><div class="callout callout-warning"><div>知识问答仍使用本地确定性 Embedding 与答案生成器；真实 Provider、50/100 条正式评测、容量和 production 验收仍需独立证据。</div></div></SectionCard>
      </div>

      <div v-else-if="activeTab === 'policies'" id="policies-panel" class="tab-panel page-stack" role="tabpanel" aria-labelledby="policies-tab">
        <SectionCard v-if="canSubmit" title="创建制度草稿" description="只允许选择已完成处理、目标为当前知识库的制度文件。">
          <template #actions><button class="button button-secondary" type="button" @click="showCreateForm = !showCreateForm">{{ showCreateForm ? '收起' : '新建草稿' }}</button></template>
          <form v-if="showCreateForm" class="form-grid" @submit.prevent="createPolicy">
            <label class="form-field form-field-wide" for="policy-source-file"><span>来源文件 ID</span><input id="policy-source-file" v-model="createForm.sourceFileId" class="mono-text" list="policy-file-candidates" autocomplete="off" required /><datalist id="policy-file-candidates"><option v-for="file in policyFiles" :key="file.fileId" :value="file.fileId">{{ file.originalName }}</option></datalist><span class="form-help">候选来自当前可见文件页；也可粘贴当前知识库已处理制度文件的 canonical UUID。</span></label>
            <label class="form-field" for="policy-code"><span>制度编号</span><input id="policy-code" v-model="createForm.policyCode" maxlength="100" required /></label><label class="form-field" for="policy-name"><span>制度名称</span><input id="policy-name" v-model="createForm.name" maxlength="300" required /></label><label class="form-field" for="policy-version"><span>制度版本</span><input id="policy-version" v-model="createForm.version" maxlength="50" required /></label><label class="form-field" for="policy-department"><span>发布部门</span><input id="policy-department" v-model="createForm.issuingDepartment" maxlength="200" /></label><label class="form-field" for="policy-effective-from"><span>生效日期</span><input id="policy-effective-from" v-model="createForm.effectiveFrom" type="date" required /></label><label class="form-field" for="policy-effective-to"><span>失效日期（可选）</span><input id="policy-effective-to" v-model="createForm.effectiveTo" type="date" /></label>
            <div class="form-actions"><button class="button button-primary" type="submit" data-testid="create-policy" :disabled="!createReady">{{ mutating ? '正在创建…' : '创建制度草稿' }}</button></div>
          </form>
        </SectionCard>

        <SectionCard v-if="canReadPendingRevocations" title="撤销待执行请求" description="只展示仍为 published 且尚未执行的最小技术元数据；执行时后端重新校验职责分离和数据版本。" compact>
          <div v-if="pendingRevocationLoading" role="status" aria-live="polite">正在加载制度撤销待办…</div>
          <div v-else-if="pendingRevocationError" class="callout callout-danger" role="alert"><div><strong>{{ pendingRevocationError }}</strong><span v-if="pendingRevocationTraceId" class="mono-text"> Trace ID：{{ pendingRevocationTraceId }}</span></div><div class="form-actions"><button class="button button-secondary" type="button" @click="loadPendingRevocationPage(requestedPendingRevocationCursor, requestedPendingRevocationPage)">重试</button></div></div>
          <div v-else-if="pendingRevocations?.items.length" class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>制度</th><th>请求时间</th><th>请求人</th><th>数据版本</th><th>独立执行</th></tr></thead>
              <tbody>
                <tr v-for="request in pendingRevocations.items" :key="request.revocationRequestId">
                  <td><span class="table-primary"><strong>{{ request.policyName }}</strong><span class="mono-text">{{ request.policyCode }} · {{ request.policyId }}</span></span></td>
                  <td class="numeric-text">{{ request.requestedAt }}</td>
                  <td class="mono-text">{{ request.requestedBy }}</td>
                  <td class="numeric-text">{{ request.policyRowVersion }}</td>
                  <td>
                    <form v-if="canExecuteRevocation" class="page-stack" :data-testid="`revoke-policy-form-${request.policyId}`" @submit.prevent="revokePolicy(request)">
                      <input v-model="revocationExecutionReasons[request.revocationRequestId]" :aria-label="`${request.policyCode} 撤销执行原因`" placeholder="填写独立执行原因" maxlength="1000" required />
                      <button class="button button-danger button-small" type="submit" :data-testid="`revoke-policy-${request.policyId}`" :disabled="mutating || !(revocationExecutionReasons[request.revocationRequestId] || '').trim()">执行撤销</button>
                    </form>
                    <span v-else>等待系统管理员执行</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-inline">当前没有待执行的制度撤销请求。</div>
          <div v-if="pendingRevocations" class="pager"><span>第 {{ currentPendingRevocationPage }} 页 · 每页 {{ pendingRevocations.pageSize }} 条</span><div class="pager-buttons"><button type="button" aria-label="撤销待办上一页" :disabled="currentPendingRevocationPage <= 1 || pendingRevocationLoading" @click="previousPendingRevocationPage">‹</button><button type="button" aria-current="page" disabled>{{ currentPendingRevocationPage }}</button><button type="button" aria-label="撤销待办下一页" :disabled="!pendingRevocations.nextCursor || pendingRevocationLoading" @click="nextPendingRevocationPage">›</button></div></div>
        </SectionCard>

        <div v-if="policyLoading" class="section-card" role="status" aria-live="polite">正在加载制度文档…</div>
        <SectionCard v-else-if="policyError" title="无法显示制度文档"><div class="callout callout-danger" role="alert"><div><strong>{{ policyError }}</strong><span v-if="policyTraceId" class="mono-text"> Trace ID：{{ policyTraceId }}</span></div></div><div class="form-actions"><button class="button button-primary" type="button" @click="loadPolicyPage(requestedPolicyCursor, requestedPolicyPage)">重试</button></div></SectionCard>
        <SectionCard v-else-if="policyResult" title="制度文档" description="业务审批、撤销确认与技术执行保持独立；职责分离由后端强制。" compact>
          <div v-if="policyResult.items.length" class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>制度</th><th>版本 / 生效期</th><th>状态</th><th>来源</th><th>数据版本</th><th>人工动作</th></tr></thead>
              <tbody>
                <tr v-for="policy in policyResult.items" :key="policy.id">
                  <td><span class="table-primary"><strong>{{ policy.name }}</strong><span class="mono-text">{{ policy.policyCode }} · {{ policy.id }}</span></span></td>
                  <td><span class="table-primary"><strong>{{ policy.version }}</strong><span>{{ policy.effectiveFrom }} 至 {{ policy.effectiveTo || '长期' }}</span></span></td>
                  <td><span class="table-primary"><StatusTag :status="policy.status" :label="policyStatusLabel(policy.status)" /><span v-if="policy.revokeReason">{{ policy.revokeReason }}</span></span></td>
                  <td><RouterLink class="text-link mono-text" :to="{ name: 'file-detail', params: { fileId: policy.sourceFileId } }">{{ policy.sourceFileId }}</RouterLink></td>
                  <td class="numeric-text">{{ policy.rowVersion }}</td>
                  <td>
                    <div
                      v-if="
                        (policy.status === 'draft' && canSubmit) ||
                        (policy.status === 'submitted' && canApprove) ||
                        (policy.status === 'business_approved' && canPublish) ||
                        (policy.status === 'published' && canRequestRevocation)
                      "
                      class="page-stack"
                    >
                      <input v-model="transitionReasons[policy.id]" :aria-label="`${policy.policyCode} 操作原因`" placeholder="填写操作原因" maxlength="1000" />
                      <button v-if="policy.status === 'draft' && canSubmit" class="button button-secondary button-small" type="button" :data-testid="`submit-policy-${policy.id}`" :disabled="mutating || !(transitionReasons[policy.id] || '').trim()" @click="transitionPolicy(policy, 'submit-review')">提交审批</button>
                      <button v-if="policy.status === 'submitted' && canApprove" class="button button-secondary button-small" type="button" :disabled="mutating || !(transitionReasons[policy.id] || '').trim()" @click="transitionPolicy(policy, 'approve')">业务批准</button>
                      <button v-if="policy.status === 'business_approved' && canPublish" class="button button-primary button-small" type="button" :disabled="mutating || !(transitionReasons[policy.id] || '').trim()" @click="transitionPolicy(policy, 'publish')">技术发布</button>
                      <button v-if="policy.status === 'published' && canRequestRevocation" class="button button-secondary button-small" type="button" :data-testid="`request-policy-revocation-${policy.id}`" :disabled="mutating || !(transitionReasons[policy.id] || '').trim()" @click="requestPolicyRevocation(policy)">提交撤销确认</button>
                    </div>
                    <span v-else>—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty-inline">当前页没有制度文档。</div>
          <div class="pager"><span>第 {{ currentPolicyPage }} 页 · 每页 {{ policyResult.pageSize }} 条</span><div class="pager-buttons"><button type="button" aria-label="制度上一页" :disabled="currentPolicyPage <= 1 || policyLoading" @click="previousPolicyPage">‹</button><button type="button" aria-current="page" disabled>{{ currentPolicyPage }}</button><button type="button" aria-label="制度下一页" :disabled="!policyResult.nextCursor || policyLoading" @click="nextPolicyPage">›</button></div></div>
        </SectionCard>
      </div>

      <div v-else id="index-panel" class="tab-panel page-stack" role="tabpanel" aria-labelledby="index-tab">
        <SectionCard title="索引构建" description="构建冻结当前活动分块成员；候选失败不会替换旧活动索引。"><template #actions><button class="button button-primary" type="button" data-testid="build-knowledge-index" :disabled="mutating || knowledgeBase.status !== 'active'" @click="buildIndex">构建候选索引</button></template><div class="callout callout-warning"><div>索引激活仍要求已批准的正式评测集和通过的正式评测运行；后端会拒绝绕过门禁。</div></div></SectionCard>
        <SectionCard v-if="indexVersion" title="当前跟踪的索引版本" :description="`候选 V${indexVersion.versionNo} · ${indexVersion.id}`"><template #actions><button class="button button-secondary" type="button" @click="refreshIndex">刷新状态</button></template><div class="field-grid"><div class="field-item"><span class="field-label">状态</span><StatusTag :status="indexVersion.status" /></div><div class="field-item"><span class="field-label">Job</span><strong class="field-value mono-text">{{ indexVersion.jobId || '—' }} · {{ indexVersion.jobStatus || '—' }}</strong></div><div class="field-item"><span class="field-label">成员数</span><strong class="field-value numeric-text">{{ indexVersion.memberCount }}</strong></div><div class="field-item"><span class="field-label">Embedding</span><strong class="field-value">{{ indexVersion.embeddingModelId }} / {{ indexVersion.vectorDimension }}</strong></div><div class="field-item"><span class="field-label">失败代码</span><strong class="field-value mono-text">{{ indexVersion.failureCode || '—' }}</strong></div><div class="field-item"><span class="field-label">数据版本</span><strong class="field-value numeric-text">{{ indexVersion.rowVersion }}</strong></div></div><form v-if="indexVersion.status === 'ready'" class="form-grid" @submit.prevent="activateIndex"><label class="form-field form-field-wide" for="index-activation-reason"><span>激活原因</span><textarea id="index-activation-reason" v-model="indexReason" maxlength="1000" required /></label><div class="form-actions"><button class="button button-primary" type="submit" data-testid="activate-knowledge-index" :disabled="mutating || !indexReason.trim()">通过门禁后激活</button></div></form></SectionCard>
      </div>
    </template>
  </section>
</template>
