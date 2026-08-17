<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type QaAnswerStatus = 'answered' | 'refused' | 'error' | 'degraded'
type EvidenceSufficiency = 'sufficient' | 'insufficient' | 'conflicting' | 'unknown'

const answerStatusLabels: Readonly<Record<QaAnswerStatus, string>> = {
  answered: '已回答',
  refused: '已拒答',
  error: '系统错误',
  degraded: '服务降级',
}

const evidenceSufficiencyLabels: Readonly<Record<EvidenceSufficiency, string>> = {
  sufficient: '证据充分',
  insufficient: '证据不足',
  conflicting: '证据冲突',
  unknown: '证据充分性未知',
}

defineProps<{
  answerStatus: QaAnswerStatus
  evidenceSufficiency: EvidenceSufficiency
}>()
</script>

<template>
  <dl class="qa-answer-statuses" aria-label="AI 问答状态">
    <div data-status-kind="answer">
      <dt>回答状态</dt>
      <dd>
        <StatusTag :status="answerStatus" :label="answerStatusLabels[answerStatus]" />
      </dd>
    </div>
    <div data-status-kind="evidence">
      <dt>证据充分性</dt>
      <dd>
        <StatusTag
          :status="evidenceSufficiency"
          :label="evidenceSufficiencyLabels[evidenceSufficiency]"
        />
      </dd>
    </div>
  </dl>
</template>
