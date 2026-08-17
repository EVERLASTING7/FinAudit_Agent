<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import { ApiError } from '@/services/api'
import {
  operationLogApi,
  type OperationActionCode,
  type OperationActorKind,
  type OperationLogListData,
  type OperationOutcome,
} from '@/services/operationLogs'

const actionLabels: Record<OperationActionCode, string> = {
  'auth.login.succeeded': '登录成功',
  'auth.login.failed': '登录失败',
  'auth.logout': '退出登录',
  'authorization.denied': '权限拒绝',
  'users.created': '创建用户',
  'users.status_changed': '变更用户状态',
  'users.password_reset': '重置密码',
  'users.roles_replaced': '替换固定角色',
  'break_glass.requested': '申请临时授权',
  'break_glass.approved': '批准临时授权',
  'break_glass.rejected': '拒绝临时授权',
  'break_glass.revoked': '撤销临时授权',
  'files.uploaded': '上传文件',
}
const actorLabels: Record<OperationActorKind, string> = {
  anonymous: '匿名请求',
  user: '已认证用户',
  system: '系统',
}
const outcomeLabels: Record<OperationOutcome, string> = {
  succeeded: '成功',
  denied: '拒绝',
  failed: '失败',
}
const pageSize = 20
const result = ref<OperationLogListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
let requestController: AbortController | null = null

function formatError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取操作日志。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '操作日志加载失败，请稍后重试。'
  }
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  requestController?.abort()
  requestedCursor.value = cursor
  requestedPage.value = page
  errorMessage.value = ''
  errorTraceId.value = ''
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await operationLogApi.list(pageSize, cursor, controller.signal)
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

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'medium',
    hour12: false,
  }).format(new Date(value))
}

function formatSummary(value: Record<string, unknown>): string {
  return Object.keys(value).length === 0 ? '无业务字段变更' : JSON.stringify(value)
}

void loadPage(undefined, 1)
onUnmounted(() => requestController?.abort())
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-014"
      title="操作日志"
      description="查看认证、授权与用户管理的脱敏追加式审计记录；日志不可修改或删除。"
    />

    <div class="callout">
      <div>
        <strong>可见范围受组织与 Actor 类型约束</strong>
        当前组织日志与匿名认证失败可见；无组织的系统内部记录不会通过此页面返回。
      </div>
    </div>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">
      正在加载操作日志…
    </div>

    <SectionCard v-else-if="errorMessage" title="无法显示操作日志">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button
          class="button button-primary"
          type="button"
          data-testid="retry-operation-logs"
          @click="retryPage"
        >
          重试
        </button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="追加式审计记录"
      :description="`当前页 ${result.items.length} 条记录，按发生时间倒序。`"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>时间 / 操作</th><th>Actor</th><th>结果</th><th>资源</th><th>脱敏摘要</th><th>Trace ID</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in result.items" :key="item.id">
              <td>
                <span class="table-primary">
                  <strong>{{ actionLabels[item.actionCode] }}</strong>
                  <span>{{ formatTime(item.createdAt) }}</span>
                </span>
              </td>
              <td>
                <span class="table-primary">
                  <strong>{{ actorLabels[item.actorKind] }}</strong>
                  <span v-if="item.actorId" class="mono-text">{{ item.actorId }}</span>
                </span>
              </td>
              <td><span class="pill">{{ outcomeLabels[item.outcome] }}</span></td>
              <td>
                <span v-if="item.resourceId" class="table-primary">
                  <strong>{{ item.resourceType }}</strong>
                  <span class="mono-text">{{ item.resourceId }}</span>
                </span>
                <span v-else>—</span>
              </td>
              <td class="mono-text">{{ formatSummary(item.changeSummary) }}</td>
              <td class="mono-text">{{ item.traceId }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前页没有操作日志。</div>
      <div class="pager">
        <span>第 {{ currentPage }} 页 · 每页 {{ result.pageSize }} 条</span>
        <div class="pager-buttons">
          <button
            type="button"
            aria-label="上一页"
            :disabled="currentPage <= 1 || loading"
            @click="loadPreviousPage"
          >
            ‹
          </button>
          <button type="button" aria-current="page" disabled>{{ currentPage }}</button>
          <button
            type="button"
            aria-label="下一页"
            :disabled="!result.nextCursor || loading"
            @click="loadNextPage"
          >
            ›
          </button>
        </div>
      </div>
    </SectionCard>
  </section>
</template>
