<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    description?: string
  }>(),
  {
    title: '暂无数据',
    description: '当前条件下没有可显示的内容。',
  },
)
</script>

<template>
  <section class="state-card state-card-empty">
    <span class="state-icon" aria-hidden="true">—</span>
    <div>
      <h2>{{ title }}</h2>
      <p>{{ description }}</p>
      <div v-if="$slots.actions" class="state-actions">
        <slot name="actions" />
      </div>
    </div>
  </section>
</template>
