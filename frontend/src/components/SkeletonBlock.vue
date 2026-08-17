<script setup lang="ts">
withDefaults(
  defineProps<{
    rows?: number
    label?: string
  }>(),
  {
    rows: 3,
    label: '内容加载中',
  },
)
</script>

<template>
  <div class="skeleton" role="status" :aria-label="label">
    <span v-for="row in rows" :key="row" class="skeleton-line" />
    <span class="sr-only">{{ label }}</span>
  </div>
</template>
