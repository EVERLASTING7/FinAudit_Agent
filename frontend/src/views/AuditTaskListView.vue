<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import { auditApi, type AuditTaskListData } from '@/services/audits'
import { contractApi, type ContractListItem } from '@/services/contracts'
import { invoiceApi, type InvoiceListItem } from '@/services/invoices'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const pageSize = 20
const result = ref<AuditTaskListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const keyword = ref('')
const statusFilter = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
const showCreateForm = ref(false)
const candidatesLoading = ref(false)
const candidatesError = ref('')
const contracts = ref<ContractListItem[]>([])
const invoices = ref<InvoiceListItem[]>([])
const creating = ref(false)
const createError = ref('')
const createTraceId = ref('')
const form = reactive({
  taskNo: '',
  name: '',
  description: '',
  baselineDate: new Date().toISOString().slice(0, 10),
  contractId: '',
  invoiceIds: [] as string[],
})
let listController: AbortController | null = null
let candidateController: AbortController | null = null
let createController: AbortController | null = null
let pendingSignature = ''
let pendingIdempotencyKey = ''

const canCreate = computed(() => auth.hasAllPermissions(['audits.create']))
const filteredTasks = computed(() => {
  const normalized = keyword.value.trim().toLowerCase()
  return (result.value?.items ?? []).filter(
    (task) =>
      (!normalized ||
        task.taskNo.toLowerCase().includes(normalized) ||
        task.name.toLowerCase().includes(normalized)) &&
      (!statusFilter.value || task.status === statusFilter.value),
  )
})
const createReady = computed(
  () =>
    canCreate.value &&
    form.taskNo.length >= 1 &&
    form.name.length >= 1 &&
    form.baselineDate.length === 10 &&
    form.invoiceIds.length >= 1 &&
    !creating.value,
)

function suggestedTaskNo(): string {
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)
  return `AUDIT-${stamp}`
}

function resetCreateForm(): void {
  form.taskNo = suggestedTaskNo()
  form.name = ''
  form.description = ''
  form.baselineDate = new Date().toISOString().slice(0, 10)
  form.contractId = ''
  form.invoiceIds = []
  createError.value = ''
  createTraceId.value = ''
  pendingSignature = ''
  pendingIdempotencyKey = ''
}

function formatListError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取审核任务。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '审核任务加载失败，请稍后重试。'
  }
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  listController?.abort()
  requestedCursor.value = cursor
  requestedPage.value = page
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  const controller = new AbortController()
  listController = controller
  loading.value = true
  try {
    const response = await auditApi.list(pageSize, cursor, controller.signal)
    if (listController === controller && !controller.signal.aborted) {
      result.value = response
      currentPage.value = page
    }
  } catch (error) {
    if (listController === controller && !controller.signal.aborted) formatListError(error)
  } finally {
    if (listController === controller) {
      listController = null
      loading.value = false
    }
  }
}

function retryPage(): void {
  void loadPage(requestedCursor.value, requestedPage.value)
}

function nextPage(): void {
  if (!result.value?.nextCursor) return
  const cursor = result.value.nextCursor
  cursorStack.value = [...cursorStack.value.slice(0, currentPage.value), cursor]
  void loadPage(cursor, currentPage.value + 1)
}

function previousPage(): void {
  if (currentPage.value <= 1) return
  const page = currentPage.value - 1
  cursorStack.value = cursorStack.value.slice(0, page)
  void loadPage(cursorStack.value[page - 1], page)
}

async function loadCandidates(): Promise<void> {
  candidateController?.abort()
  const controller = new AbortController()
  candidateController = controller
  candidatesLoading.value = true
  candidatesError.value = ''
  try {
    const [contractPage, invoicePage] = await Promise.all([
      contractApi.list(100, undefined, controller.signal),
      invoiceApi.list(100, undefined, controller.signal),
    ])
    if (candidateController !== controller || controller.signal.aborted) return
    contracts.value = contractPage.items.filter(
      (contract) => contract.confirmationStatus === 'confirmed' && contract.status === 'active',
    )
    invoices.value = invoicePage.items.filter(
      (invoice) =>
        invoice.confirmationStatus === 'confirmed' &&
        invoice.status === 'confirmed' &&
        invoice.duplicateStatus !== 'confirmed_duplicate',
    )
  } catch {
    if (candidateController === controller && !controller.signal.aborted) {
      candidatesError.value = '已确认合同和发票候选加载失败，请收起后重试。'
    }
  } finally {
    if (candidateController === controller) {
      candidateController = null
      candidatesLoading.value = false
    }
  }
}

function toggleCreateForm(): void {
  showCreateForm.value = !showCreateForm.value
  if (!showCreateForm.value) {
    candidateController?.abort()
    return
  }
  resetCreateForm()
  void loadCandidates()
}

function idempotencyKey(signature: string): string {
  if (signature !== pendingSignature) {
    pendingSignature = signature
    pendingIdempotencyKey = `audit-create.${crypto.randomUUID()}`
  }
  return pendingIdempotencyKey
}

function formatCreateError(error: unknown): void {
  createTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 409) {
    createError.value = '审核编号、事实版本或对象状态已变化，请刷新候选后核对。'
  } else if (error instanceof ApiError && error.status === 403) {
    createError.value = '当前账号无权创建审核任务。'
  } else if (error instanceof ApiError && error.status === 422) {
    createError.value = '创建参数不符合约束，请检查编号、日期和审核对象。'
  } else {
    createError.value = '审核任务创建失败；可直接重试，系统会复用同一幂等键。'
  }
}

async function createTask(): Promise<void> {
  if (!createReady.value) return
  createError.value = ''
  createTraceId.value = ''
  const input = {
    taskNo: form.taskNo,
    name: form.name,
    description: form.description || null,
    baselineDate: form.baselineDate,
    contractId: form.contractId || null,
    invoiceIds: [...form.invoiceIds].sort(),
  }
  const signature = JSON.stringify(input)
  const controller = new AbortController()
  createController = controller
  creating.value = true
  try {
    const created = await auditApi.createTask(input, idempotencyKey(signature), controller.signal)
    if (createController !== controller || controller.signal.aborted) return
    pendingSignature = ''
    pendingIdempotencyKey = ''
    await router.push({ name: 'audit-task-detail', params: { taskId: created.task.id } })
  } catch (error) {
    if (createController === controller && !controller.signal.aborted) formatCreateError(error)
  } finally {
    if (createController === controller) {
      createController = null
      creating.value = false
    }
  }
}

onMounted(() => void loadPage(undefined, 1))
onUnmounted(() => {
  listController?.abort()
  candidateController?.abort()
  createController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader ui-code="UI-011" title="审核任务" description="读取持久化审核任务，并创建绑定已确认合同、发票和基准日期的版本化执行。">
      <template #actions>
        <button v-if="canCreate" class="button button-primary" type="button" data-testid="toggle-audit-create" @click="toggleCreateForm">{{ showCreateForm ? '收起创建表单' : '创建审核任务' }}</button>
      </template>
    </PageHeader>

    <SectionCard v-if="showCreateForm" title="创建审核任务" description="后端会重新校验确认状态、主合同关系、组织边界和冻结快照。">
      <form class="form-grid" @submit.prevent="createTask">
        <div class="form-field"><label for="task-no">任务编号</label><input id="task-no" v-model.trim="form.taskNo" class="text-input" maxlength="80" required /></div>
        <div class="form-field"><label for="task-date">审核基准日期</label><input id="task-date" v-model="form.baselineDate" class="text-input" type="date" required /></div>
        <div class="form-field form-field-full"><label for="task-name">任务名称</label><input id="task-name" v-model.trim="form.name" class="text-input" maxlength="300" required /></div>
        <div class="form-field form-field-full"><label for="task-description">说明</label><textarea id="task-description" v-model.trim="form.description" rows="2" maxlength="4000" /></div>
        <div class="form-field"><label for="task-contract">已确认合同（可选）</label><select id="task-contract" v-model="form.contractId" class="select-input" :disabled="candidatesLoading"><option value="">不关联合同</option><option v-for="contract in contracts" :key="contract.id" :value="contract.id">{{ contract.contractNo || '编号待补' }} · {{ contract.name }}</option></select></div>
        <div class="form-field"><label for="task-invoices">已确认发票</label><select id="task-invoices" v-model="form.invoiceIds" class="select-input" multiple size="5" :disabled="candidatesLoading" required><option v-for="invoice in invoices" :key="invoice.id" :value="invoice.id">{{ invoice.invoiceNumber || '号码待补' }} · {{ invoice.totalAmount || '金额待补' }} {{ invoice.currency }}</option></select></div>
        <div v-if="candidatesLoading" class="form-field-full" role="status">正在加载已确认审核对象…</div>
        <div v-if="candidatesError" class="callout callout-danger form-field-full" role="alert"><div><strong>{{ candidatesError }}</strong></div></div>
        <div v-if="createError" class="callout callout-danger form-field-full" role="alert"><div><strong>{{ createError }}</strong><span v-if="createTraceId" class="mono-text"> Trace ID：{{ createTraceId }}</span></div></div>
        <div class="form-actions form-field-full"><button class="button button-secondary" type="button" @click="toggleCreateForm">取消</button><button class="button button-primary" type="submit" :disabled="!createReady" data-testid="create-audit-task">{{ creating ? '正在创建…' : '创建并排队执行' }}</button></div>
      </form>
    </SectionCard>

    <SectionCard title="查询当前页" description="关键字和状态筛选只作用于当前服务端分页。">
      <form class="filter-bar" @submit.prevent><div class="filter-field filter-field-wide"><label for="task-keyword">关键字</label><input id="task-keyword" v-model="keyword" class="text-input" placeholder="任务编号或名称" /></div><div class="filter-field"><label for="task-status">任务状态</label><select id="task-status" v-model="statusFilter" class="select-input"><option value="">全部</option><option value="open">未完成</option><option value="completed">已完成</option><option value="archived">已归档</option></select></div></form>
    </SectionCard>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载审核任务…</div>
    <SectionCard v-else-if="errorMessage" title="无法显示审核任务"><div class="callout callout-danger" role="alert"><div><strong>{{ errorMessage }}</strong><span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span></div></div><div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-audit-list" @click="retryPage">重试</button></div></SectionCard>
    <SectionCard v-else-if="result" title="审核任务列表" :description="`当前服务端页 ${result.items.length} 条，筛选后 ${filteredTasks.length} 条。`" compact>
      <div v-if="filteredTasks.length" class="data-table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>状态</th><th>当前执行</th><th>负责人</th><th>更新时间</th><th>操作</th></tr></thead><tbody><tr v-for="task in filteredTasks" :key="task.id"><td><span class="table-primary"><strong>{{ task.taskNo }}</strong><span>{{ task.name }}</span><span class="mono-text">{{ task.id }}</span></span></td><td><StatusTag :status="task.status" /></td><td class="mono-text">{{ task.currentExecutionId || '—' }}</td><td class="mono-text">{{ task.ownerId }}</td><td>{{ new Date(task.updatedAt).toLocaleString('zh-CN', { hour12: false }) }}</td><td><RouterLink class="button button-secondary button-small" :to="{ name: 'audit-task-detail', params: { taskId: task.id } }">查看</RouterLink></td></tr></tbody></table></div>
      <div v-else class="empty-inline">当前服务端页没有符合条件的审核任务。</div>
      <div class="pager"><span>第 {{ currentPage }} 页 · 每页 {{ pageSize }} 条</span><div class="pager-buttons"><button type="button" aria-label="上一页" :disabled="currentPage <= 1" @click="previousPage">‹</button><button type="button" aria-current="page">{{ currentPage }}</button><button type="button" aria-label="下一页" :disabled="!result.nextCursor" @click="nextPage">›</button></div></div>
    </SectionCard>
  </section>
</template>
