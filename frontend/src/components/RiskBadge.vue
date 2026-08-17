<script setup lang="ts">
type RiskLevel = 'none' | 'notice' | 'low' | 'medium' | 'high'

defineProps<{
  level: RiskLevel
}>()

const labels: Readonly<Record<RiskLevel, string>> = {
  none: '无风险',
  notice: '提示风险',
  low: '低风险',
  medium: '中风险',
  high: '高风险',
}
</script>

<template>
  <span class="risk-badge" :class="`risk-badge-${level}`" :aria-label="`风险等级：${labels[level]}`">
    <span aria-hidden="true">●</span>
    {{ labels[level] }}
  </span>
</template>
