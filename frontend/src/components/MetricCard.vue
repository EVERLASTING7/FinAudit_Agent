<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string
    value: string | number
    hint: string
    tone?: 'brand' | 'gold' | 'success' | 'warning' | 'danger'
  }>(),
  {
    tone: 'brand',
  },
)
</script>

<template>
  <article class="metric-card" :class="`metric-card-${tone}`">
    <span class="metric-label">{{ label }}</span>
    <strong>{{ value }}</strong>
    <span class="metric-hint">{{ hint }}</span>
  </article>
</template>
