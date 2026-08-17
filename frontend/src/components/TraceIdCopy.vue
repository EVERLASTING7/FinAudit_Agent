<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  traceId: string
}>()

type CopyState = 'idle' | 'copying' | 'copied' | 'failed'

const buttonLabels: Readonly<Record<CopyState, string>> = {
  idle: '复制',
  copying: '复制中',
  copied: '已复制',
  failed: '复制失败',
}
const feedbackLabels: Readonly<Record<CopyState, string>> = {
  idle: '',
  copying: '正在复制 Trace ID',
  copied: 'Trace ID 已复制',
  failed: 'Trace ID 复制失败',
}
const copyState = ref<CopyState>('idle')
let copyAttempt = 0

watch(
  () => props.traceId,
  () => {
    copyAttempt += 1
    copyState.value = 'idle'
  },
)

async function copyTraceId(): Promise<void> {
  if (copyState.value === 'copying') {
    return
  }

  const traceId = props.traceId
  const attempt = ++copyAttempt
  copyState.value = 'copying'

  try {
    const clipboard = navigator.clipboard
    if (!clipboard || typeof clipboard.writeText !== 'function') {
      if (attempt === copyAttempt && props.traceId === traceId) {
        copyState.value = 'failed'
      }
      return
    }

    await clipboard.writeText(traceId)
    if (attempt === copyAttempt && props.traceId === traceId) {
      copyState.value = 'copied'
    }
  } catch {
    if (attempt === copyAttempt && props.traceId === traceId) {
      copyState.value = 'failed'
    }
  }
}
</script>

<template>
  <div class="trace-id">
    <span>Trace ID：</span>
    <code>{{ traceId }}</code>
    <button
      class="button button-secondary button-small"
      type="button"
      :disabled="copyState === 'copying'"
      @click="copyTraceId"
    >
      {{ buttonLabels[copyState] }}
    </button>
    <span class="sr-only" role="status" aria-live="polite">{{ feedbackLabels[copyState] }}</span>
  </div>
</template>
