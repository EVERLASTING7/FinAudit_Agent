<script setup lang="ts">
import { computed } from 'vue'

import StatusTag from './StatusTag.vue'

type JobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancel_requested'
  | 'cancelled'

const props = defineProps<{
  status: JobStatus
  stage: string | null
  attemptNo: number
  maxAttempts: number
}>()

const stageLabels: Readonly<Record<string, string>> = {
  security_scan: '正在进行文件安全检查',
  parsing: '正在解析文档',
  ocr: '正在执行 OCR 识别',
  field_extraction: '正在提取业务字段',
  markdown_converting: '正在转换 Markdown',
  markdown_validating: '正在校验 Markdown',
  chunk_building: '正在生成文档分块',
  embedding: '正在生成向量',
  index_consistency_check: '正在校验索引一致性',
  retrieval_evaluation: '正在执行检索评测',
  snapshot_building: '正在冻结审核快照',
  rule_execution: '正在执行审核规则',
  policy_retrieval: '正在检索制度证据',
  risk_explanation: '正在生成风险解释',
  report_generating: '正在生成审核报告',
}

const stageText = computed(() => {
  if (props.stage === null) {
    return null
  }
  return stageLabels[props.stage] ?? props.stage
})
</script>

<template>
  <div class="job-stage-indicator" role="status" aria-live="polite" aria-atomic="true">
    <StatusTag :status="status" />
    <span v-if="stageText !== null" class="job-stage-label">{{ stageText }}</span>
    <span class="job-stage-attempt">
      第 {{ attemptNo }} 次尝试（最多 {{ maxAttempts }} 次）
    </span>
  </div>
</template>
