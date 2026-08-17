<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import { knowledgeApi, type KnowledgeBaseListData } from '@/services/knowledge'

const pageSize = 20
const result = ref<KnowledgeBaseListData | null>(null)
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
    errorMessage.value = '当前账号无权读取制度知识库。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '知识库目录加载失败，请稍后重试。'
  }
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  requestController?.abort()
  requestedCursor.value = cursor
  requestedPage.value = page
  result.value = null
  errorMessage.value = ''
  errorTraceId.value = ''
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await knowledgeApi.list(pageSize, cursor, controller.signal)
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

void loadPage(undefined, 1)
onUnmounted(() => requestController?.abort())
</script>

<template>
  <section class="page page-stack">
    <PageHeader ui-code="UI-009" title="制度知识库" description="读取当前组织可见的真实知识库目录、状态与固定检索参数。">
      <template #actions><RouterLink class="button button-primary" :to="{ name: 'qa' }">进入制度问答</RouterLink></template>
    </PageHeader>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">正在加载知识库目录…</div>

    <SectionCard v-else-if="errorMessage" title="无法显示知识库目录">
      <div class="callout callout-danger" role="alert"><div><strong>{{ errorMessage }}</strong><span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span></div></div>
      <div class="form-actions"><button class="button button-primary" type="button" data-testid="retry-knowledge-list" @click="loadPage(requestedCursor, requestedPage)">重试</button></div>
    </SectionCard>

    <SectionCard v-else-if="result" title="知识库列表" description="Top-K 固定为 5；当前基线不设置相似度阈值。" compact>
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead><tr><th>代码 / 名称</th><th>说明</th><th>状态</th><th>默认 Top-K</th><th>数据版本</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="knowledgeBase in result.items" :key="knowledgeBase.id">
              <td><span class="table-primary"><strong>{{ knowledgeBase.name }}</strong><span class="mono-text">{{ knowledgeBase.code }}</span></span></td>
              <td>{{ knowledgeBase.description || '—' }}</td>
              <td><StatusTag :status="knowledgeBase.status" /></td>
              <td class="numeric-text">{{ knowledgeBase.defaultTopK }}</td>
              <td class="numeric-text">{{ knowledgeBase.rowVersion }}</td>
              <td><div class="inline-actions"><RouterLink class="button button-secondary button-small" :to="{ name: 'knowledge-base-detail', params: { kbId: knowledgeBase.id } }">查看</RouterLink><RouterLink v-if="knowledgeBase.status === 'active'" class="button button-primary button-small" :to="{ name: 'qa', query: { knowledge_base_id: knowledgeBase.id } }">提问</RouterLink></div></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前组织没有可见知识库。</div>
      <div class="pager">
        <span>第 {{ currentPage }} 页 · 每页 {{ result.pageSize }} 条</span>
        <div class="pager-buttons"><button type="button" aria-label="上一页" :disabled="currentPage <= 1 || loading" @click="previousPage">‹</button><button type="button" aria-current="page" disabled>{{ currentPage }}</button><button type="button" aria-label="下一页" :disabled="!result.nextCursor || loading" @click="nextPage">›</button></div>
      </div>
    </SectionCard>
  </section>
</template>
