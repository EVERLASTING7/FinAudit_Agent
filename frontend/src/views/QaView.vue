<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import QaAnswerStatuses from '@/components/QaAnswerStatuses.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import {
  knowledgeApi,
  type KnowledgeBase,
  type QaFeedback,
  type QaQueryResult,
} from '@/services/knowledge'

const route = useRoute()
const knowledgeBases = ref<KnowledgeBase[]>([])
const loadingKnowledgeBases = ref(false)
const knowledgeBaseError = ref('')
const result = ref<QaQueryResult | null>(null)
const asking = ref(false)
const queryError = ref('')
const queryTraceId = ref('')
const feedback = ref<QaFeedback | null>(null)
const feedbackError = ref('')
const feedbackTraceId = ref('')
const feedbackSending = ref(false)
const form = reactive({
  knowledgeBaseId: typeof route.query.knowledge_base_id === 'string' ? route.query.knowledge_base_id : '',
  baselineDate: new Date().toISOString().slice(0, 10),
  question: '',
})
let catalogController: AbortController | null = null
let queryController: AbortController | null = null
let feedbackController: AbortController | null = null
let querySignature = ''
let queryIdempotencyKey = ''
let feedbackSignature = ''
let feedbackIdempotencyKey = ''

const activeKnowledgeBases = computed(() => knowledgeBases.value.filter((item) => item.status === 'active'))
const canAsk = computed(
  () =>
    activeKnowledgeBases.value.some((item) => item.id === form.knowledgeBaseId) &&
    form.question.trim().length >= 1 &&
    form.question.trim().length <= 4000 &&
    /^\d{4}-\d{2}-\d{2}$/.test(form.baselineDate) &&
    !asking.value,
)
const refusalMessage = computed(() => {
  const reason = result.value?.reasonCode
  if (reason === 'NO_ACTIVE_INDEX') return '当前知识库没有可用的活动索引。'
  if (reason === 'NO_RELEVANT_EVIDENCE') return '当前授权且在基准日期有效的证据不足以支持回答。'
  if (reason === 'PROMPT_INJECTION_DETECTED') return '检索内容未通过安全校验，本次不生成回答。'
  if (reason === 'INDEX_DRIFT_DETECTED') return '索引与 PostgreSQL 权威事实不一致，本次已失败关闭。'
  if (reason === 'RETRIEVAL_UNAVAILABLE') return '检索服务当前不可用，本次没有生成回答或引用。'
  return '系统无法基于当前授权证据可靠回答。'
})

async function loadKnowledgeBases(): Promise<void> {
  catalogController?.abort()
  const controller = new AbortController()
  catalogController = controller
  loadingKnowledgeBases.value = true
  knowledgeBaseError.value = ''
  try {
    const page = await knowledgeApi.list(100, undefined, controller.signal)
    if (catalogController !== controller || controller.signal.aborted) return
    knowledgeBases.value = page.items
    const requestedIsAvailable = page.items.some(
      (item) => item.id === form.knowledgeBaseId && item.status === 'active',
    )
    if (!requestedIsAvailable) form.knowledgeBaseId = page.items.find((item) => item.status === 'active')?.id ?? ''
  } catch (error) {
    if (catalogController !== controller || controller.signal.aborted) return
    knowledgeBaseError.value = error instanceof ApiError && error.status === 403
      ? '当前账号无权读取知识库。'
      : '知识库目录加载失败，请稍后重试。'
  } finally {
    if (catalogController === controller) {
      catalogController = null
      loadingKnowledgeBases.value = false
    }
  }
}

function nextQueryKey(signature: string): string {
  if (querySignature !== signature) {
    querySignature = signature
    queryIdempotencyKey = `qa-query.${crypto.randomUUID()}`
  }
  return queryIdempotencyKey
}

async function ask(): Promise<void> {
  if (!canAsk.value) return
  const input = { question: form.question.trim(), baselineDate: form.baselineDate }
  const signature = JSON.stringify({ knowledgeBaseId: form.knowledgeBaseId, ...input })
  queryError.value = ''
  queryTraceId.value = ''
  result.value = null
  feedback.value = null
  feedbackError.value = ''
  const controller = new AbortController()
  queryController = controller
  asking.value = true
  try {
    const response = await knowledgeApi.query(
      form.knowledgeBaseId,
      input,
      nextQueryKey(signature),
      controller.signal,
    )
    if (queryController !== controller || controller.signal.aborted) return
    result.value = response
    querySignature = ''
    queryIdempotencyKey = ''
  } catch (error) {
    if (queryController !== controller || controller.signal.aborted) return
    queryTraceId.value = error instanceof ApiError ? error.traceId : ''
    if (error instanceof ApiError && error.status === 409) {
      queryError.value = '知识索引状态已变化，请直接重试以重新核对当前活动版本。'
    } else if (error instanceof ApiError && error.status === 403) {
      queryError.value = '当前账号无权使用该知识库。'
    } else if (error instanceof ApiError && error.status === 422) {
      queryError.value = '问题或基准日期不符合约束。'
    } else {
      queryError.value = '问答请求失败；可直接重试，系统会复用同一幂等键。'
    }
  } finally {
    if (queryController === controller) {
      queryController = null
      asking.value = false
    }
  }
}

function nextFeedbackKey(signature: string): string {
  if (feedbackSignature !== signature) {
    feedbackSignature = signature
    feedbackIdempotencyKey = `qa-feedback.${crypto.randomUUID()}`
  }
  return feedbackIdempotencyKey
}

async function sendFeedback(rating: 'helpful' | 'unhelpful'): Promise<void> {
  if (!result.value || feedback.value || feedbackSending.value) return
  const signature = JSON.stringify({ queryId: result.value.id, rating })
  feedbackError.value = ''
  feedbackTraceId.value = ''
  const controller = new AbortController()
  feedbackController = controller
  feedbackSending.value = true
  try {
    const response = await knowledgeApi.feedback(
      result.value.id,
      { rating },
      nextFeedbackKey(signature),
      controller.signal,
    )
    if (feedbackController !== controller || controller.signal.aborted) return
    feedback.value = response
    feedbackSignature = ''
    feedbackIdempotencyKey = ''
  } catch (error) {
    if (feedbackController !== controller || controller.signal.aborted) return
    feedbackTraceId.value = error instanceof ApiError ? error.traceId : ''
    feedbackError.value = error instanceof ApiError && error.status === 409
      ? '本次问答已经提交过反馈。'
      : '反馈提交失败；可直接重试，系统会复用同一幂等键。'
  } finally {
    if (feedbackController === controller) {
      feedbackController = null
      feedbackSending.value = false
    }
  }
}

void loadKnowledgeBases()
onUnmounted(() => {
  catalogController?.abort()
  queryController?.abort()
  feedbackController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader ui-code="UI-010" title="制度问答" description="只使用当前账号获准、在基准日期有效且通过最终校验的制度证据。">
      <template #actions><StatusTag status="notice" label="AI 仅辅助审核" /></template>
    </PageHeader>

    <SectionCard title="提问" description="前端不读取系统 Prompt，也不会把拒答改写成推测答案。">
      <form class="form-grid" @submit.prevent="ask">
        <label class="form-field" for="qa-knowledge-base"><span>知识库</span><select id="qa-knowledge-base" v-model="form.knowledgeBaseId" :disabled="loadingKnowledgeBases || asking"><option value="" disabled>{{ loadingKnowledgeBases ? '正在加载…' : '请选择知识库' }}</option><option v-for="item in activeKnowledgeBases" :key="item.id" :value="item.id">{{ item.name }}（{{ item.code }}）</option></select></label>
        <label class="form-field" for="qa-baseline-date"><span>基准日期</span><input id="qa-baseline-date" v-model="form.baselineDate" type="date" :disabled="asking" required /></label>
        <label class="form-field form-field-wide" for="qa-question"><span>问题</span><textarea id="qa-question" v-model="form.question" maxlength="4000" :disabled="asking" required /><span class="form-help">本地确定性生成器仍在使用；该页面不构成真实 Provider 证据。</span></label>
        <div v-if="knowledgeBaseError" class="callout callout-danger" role="alert"><div><strong>{{ knowledgeBaseError }}</strong><button class="button button-secondary button-small" type="button" @click="loadKnowledgeBases">重试目录</button></div></div>
        <div v-if="queryError" class="callout callout-danger" role="alert"><div><strong>{{ queryError }}</strong><span v-if="queryTraceId" class="mono-text"> Trace ID：{{ queryTraceId }}</span></div></div>
        <div class="form-actions"><button class="button button-primary" type="submit" data-testid="submit-qa-query" :disabled="!canAsk">{{ asking ? '正在检索与校验…' : '提交问题' }}</button></div>
      </form>
    </SectionCard>

    <SectionCard v-if="result" title="问答结果" :description="`检索命中 ${result.retrievedCount} 条；基准日期 ${result.baselineDate}。`">
      <template #actions><QaAnswerStatuses :answer-status="result.status === 'service_degraded' ? 'degraded' : result.status" :evidence-sufficiency="result.status === 'answered' ? 'sufficient' : result.status === 'refused' ? 'insufficient' : 'unknown'" /></template>
      <div class="page-stack">
        <div v-if="result.status === 'answered'" class="callout callout-success" role="status"><div><strong>基于授权证据的回答</strong><p>{{ result.answer }}</p></div></div>
        <div v-else :class="['callout', result.status === 'service_degraded' ? 'callout-danger' : 'callout-warning']" role="status"><div><strong>{{ result.status === 'service_degraded' ? '服务降级' : '明确拒答' }}</strong><p>{{ refusalMessage }}</p><span class="mono-text">原因代码：{{ result.reasonCode }}</span></div></div>

        <div v-if="result.citations.length" class="content-grid content-grid-balanced" aria-label="回答引用">
          <article v-for="(citation, index) in result.citations" :key="citation.chunkId" class="evidence-card">
            <header><h3>引用 {{ index + 1 }} · 制度版本 {{ citation.policyVersion }}</h3><StatusTag status="passed" label="引用已校验" /></header>
            <blockquote>{{ citation.quote }}</blockquote>
            <div class="card-meta"><span>{{ citation.titlePath.join(' / ') || '无标题路径' }}</span><span>页码 {{ citation.pageRange }}</span><span class="mono-text">制度 {{ citation.policyDocumentId }}</span><span class="mono-text">Chunk {{ citation.chunkId }} · Index {{ citation.indexVersionId }}</span></div>
          </article>
        </div>

        <div class="inline-actions" aria-label="回答反馈"><span class="table-secondary">反馈不会直接修改制度、索引或审核结论。</span><button class="button button-secondary button-small" type="button" data-testid="qa-helpful" :disabled="feedbackSending || Boolean(feedback)" @click="sendFeedback('helpful')">有帮助</button><button class="button button-secondary button-small" type="button" data-testid="qa-unhelpful" :disabled="feedbackSending || Boolean(feedback)" @click="sendFeedback('unhelpful')">无帮助</button></div>
        <div v-if="feedback" class="callout callout-success" role="status"><div>反馈已记录：{{ feedback.rating === 'helpful' ? '有帮助' : '无帮助' }}。</div></div>
        <div v-if="feedbackError" class="callout callout-danger" role="alert"><div><strong>{{ feedbackError }}</strong><span v-if="feedbackTraceId" class="mono-text"> Trace ID：{{ feedbackTraceId }}</span></div></div>
      </div>
    </SectionCard>
  </section>
</template>
