<script setup lang="ts">
import StatusTag from './StatusTag.vue'

withDefaults(
  defineProps<{
    uiCode: string
    title: string
    description: string
    status?: string
    statusLabel?: string
  }>(),
  {
    status: '',
    statusLabel: '',
  },
)
</script>

<template>
  <header class="page-header">
    <div class="page-header-copy">
      <div class="page-kicker">{{ uiCode }}</div>
      <h1>{{ title }}</h1>
      <p>{{ description }}</p>
      <div v-if="$slots.meta" class="page-header-meta">
        <slot name="meta" />
      </div>
    </div>
    <div class="page-header-actions">
      <StatusTag v-if="status" :status="status" :label="statusLabel || undefined" />
      <slot name="actions" />
    </div>
  </header>
</template>
