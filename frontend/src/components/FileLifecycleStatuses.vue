<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type FileStatus = 'uploaded' | 'validating' | 'stored' | 'rejected' | 'archived'
type SecurityScanStatus =
  | 'pending'
  | 'clean'
  | 'infected'
  | 'scan_failed'
  | 'unsupported'
  | 'not_configured'
type ParseStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'manual_review_required'
  | 'active'
  | 'failed'
  | 'superseded'
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

defineProps<{
  fileStatus: FileStatus
  securityScanStatus: SecurityScanStatus
  parseStatus: ParseStatus | null
  markdownStatus: MarkdownStatus | null
}>()
</script>

<template>
  <dl class="file-lifecycle-statuses" aria-label="文件生命周期状态">
    <div data-status-kind="file">
      <dt>文件状态</dt>
      <dd><StatusTag :status="fileStatus" /></dd>
    </div>
    <div data-status-kind="security-scan">
      <dt>安全扫描状态</dt>
      <dd><StatusTag :status="securityScanStatus" /></dd>
    </div>
    <div data-status-kind="parse">
      <dt>解析状态</dt>
      <dd>
        <StatusTag v-if="parseStatus !== null" :status="parseStatus" />
        <span v-else>—</span>
      </dd>
    </div>
    <div data-status-kind="markdown">
      <dt>Markdown 状态</dt>
      <dd>
        <StatusTag v-if="markdownStatus !== null" :status="markdownStatus" />
        <span v-else>—</span>
      </dd>
    </div>
  </dl>
</template>
