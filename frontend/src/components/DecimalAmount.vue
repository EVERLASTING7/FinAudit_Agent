<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  amount: string | null
}>()

const decimalLiteralPattern = /^[+-]?\d+(?:\.\d+)?$/
const thousandsSeparatorPattern = /\B(?=(\d{3})+(?!\d))/g

const formattedAmount = computed(() => {
  if (props.amount === null) {
    return '—'
  }

  if (!decimalLiteralPattern.test(props.amount)) {
    return props.amount
  }

  const decimalPointIndex = props.amount.indexOf('.')
  const integerEnd = decimalPointIndex === -1 ? props.amount.length : decimalPointIndex
  const integerPart = props.amount.slice(0, integerEnd)
  const fractionalPart = props.amount.slice(integerEnd)

  return `${integerPart.replace(thousandsSeparatorPattern, ',')}${fractionalPart}`
})
</script>

<template>
  <span>{{ formattedAmount }}</span>
</template>
