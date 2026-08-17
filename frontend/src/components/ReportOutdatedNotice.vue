<script setup lang="ts">
type ReportStatus = 'queued' | 'generating' | 'ready' | 'failed' | 'outdated' | 'archived'

defineProps<{
  status: ReportStatus
  isOutdated?: boolean
}>()
</script>

<template>
  <div
    v-if="status === 'outdated' || isOutdated"
    class="notice-banner"
    role="alert"
    aria-atomic="true"
  >
    <strong>报告已过期：</strong>该报告基于旧事实版本，仅供历史追溯
  </div>
</template>
