<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type AuditTaskStatus = 'open' | 'completed' | 'archived'
type AuditExecutionStatus =
  | 'draft'
  | 'validating'
  | 'queued'
  | 'running'
  | 'pending_finance_review'
  | 'pending_audit_review'
  | 'returned_for_correction'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'outdated'

defineProps<{
  taskStatus: AuditTaskStatus
  executionStatus: AuditExecutionStatus | null
}>()
</script>

<template>
  <dl class="audit-task-execution-statuses" aria-label="审核任务与当前执行状态">
    <div data-status-kind="task">
      <dt>任务状态</dt>
      <dd><StatusTag :status="taskStatus" /></dd>
    </div>
    <div data-status-kind="execution">
      <dt>当前执行状态</dt>
      <dd>
        <StatusTag v-if="executionStatus !== null" :status="executionStatus" />
        <span v-else aria-label="暂无当前执行版本">—</span>
      </dd>
    </div>
  </dl>
</template>
