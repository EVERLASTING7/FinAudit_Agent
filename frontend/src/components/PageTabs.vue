<script setup lang="ts">
export interface PageTabItem {
  id: string
  label: string
  count?: number
}

const props = defineProps<{
  items: readonly PageTabItem[]
  modelValue: string
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

function handleKeydown(event: KeyboardEvent, currentIndex: number): void {
  let nextIndex: number
  if (event.key === 'ArrowRight') {
    nextIndex = (currentIndex + 1) % props.items.length
  } else if (event.key === 'ArrowLeft') {
    nextIndex = (currentIndex - 1 + props.items.length) % props.items.length
  } else if (event.key === 'Home') {
    nextIndex = 0
  } else if (event.key === 'End') {
    nextIndex = props.items.length - 1
  } else {
    return
  }

  event.preventDefault()
  const item = props.items[nextIndex]
  const currentTab = event.currentTarget as HTMLButtonElement | null
  const tabs = currentTab?.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  const nextTab = tabs?.[nextIndex]
  if (!item || !nextTab) return

  emit('update:modelValue', item.id)
  nextTab.focus()
}
</script>

<template>
  <div class="page-tabs" role="tablist" aria-orientation="horizontal" :aria-label="label">
    <button
      v-for="(item, index) in items"
      :id="`${item.id}-tab`"
      :key="item.id"
      class="page-tab"
      :class="{ 'page-tab-active': modelValue === item.id }"
      type="button"
      role="tab"
      :aria-selected="modelValue === item.id"
      :aria-controls="`${item.id}-panel`"
      :tabindex="modelValue === item.id ? 0 : -1"
      @click="emit('update:modelValue', item.id)"
      @keydown="handleKeydown($event, index)"
    >
      {{ item.label }}
      <span v-if="item.count !== undefined" class="page-tab-count">{{ item.count }}</span>
    </button>
  </div>
</template>
