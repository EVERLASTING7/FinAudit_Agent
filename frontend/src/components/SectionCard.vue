<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    compact?: boolean
  }>(),
  {
    description: '',
    compact: false,
  },
)
</script>

<template>
  <section class="section-card" :class="{ 'section-card-compact': compact }">
    <header class="section-card-header">
      <div>
        <h2>{{ title }}</h2>
        <p v-if="description">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="section-card-actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="section-card-body">
      <slot />
    </div>
  </section>
</template>
