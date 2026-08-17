<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type PolicyStatus =
  | 'draft'
  | 'pending_business_review'
  | 'approved'
  | 'rejected'
  | 'published'
  | 'superseded'
  | 'revoked'
  | 'archived'
type MarkdownStatus =
  | 'queued'
  | 'converting'
  | 'validating'
  | 'review_required'
  | 'ready'
  | 'active'
  | 'failed'
  | 'superseded'
  | 'archived'
type ChunkSetStatus =
  | 'queued'
  | 'building'
  | 'quality_review'
  | 'ready'
  | 'active'
  | 'failed'
  | 'blocked'
  | 'superseded'
  | 'archived'
type IndexVersionStatus =
  | 'queued'
  | 'building'
  | 'consistency_check'
  | 'evaluation_pending'
  | 'approved'
  | 'active'
  | 'failed'
  | 'rejected'
  | 'superseded'

defineProps<{
  policyStatus: PolicyStatus
  markdownStatus: MarkdownStatus | null
  chunkSetStatus: ChunkSetStatus | null
  indexVersionStatus: IndexVersionStatus | null
}>()
</script>

<template>
  <dl class="policy-pipeline-statuses" aria-label="制度与技术处理状态">
    <div data-status-kind="policy">
      <dt>制度业务状态</dt>
      <dd><StatusTag :status="policyStatus" /></dd>
    </div>
    <div data-status-kind="markdown">
      <dt>Markdown 状态</dt>
      <dd>
        <StatusTag v-if="markdownStatus !== null" :status="markdownStatus" />
        <span v-else>—</span>
      </dd>
    </div>
    <div data-status-kind="chunk-set">
      <dt>分块集合状态</dt>
      <dd>
        <StatusTag v-if="chunkSetStatus !== null" :status="chunkSetStatus" />
        <span v-else>—</span>
      </dd>
    </div>
    <div data-status-kind="index-version">
      <dt>知识库索引状态</dt>
      <dd>
        <StatusTag v-if="indexVersionStatus !== null" :status="indexVersionStatus" />
        <span v-else>—</span>
      </dd>
    </div>
  </dl>
</template>
