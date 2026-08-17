<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type RiskLevel = 'none' | 'notice' | 'low' | 'medium' | 'high'
type RiskReviewStatus = 'pending' | 'confirmed' | 'dismissed' | 'adjusted' | 'returned'

defineProps<{
  originalLevel: RiskLevel
  effectiveLevel: RiskLevel
  reviewStatus: RiskReviewStatus
}>()
</script>

<template>
  <dl class="risk-review-statuses" aria-label="风险等级与复核状态">
    <div data-risk-kind="original">
      <dt>原始等级</dt>
      <dd><StatusTag :status="originalLevel" /></dd>
    </div>
    <div data-risk-kind="effective">
      <dt>有效等级</dt>
      <dd><StatusTag :status="effectiveLevel" /></dd>
    </div>
    <div data-risk-kind="review">
      <dt>复核状态</dt>
      <dd><StatusTag :status="reviewStatus" /></dd>
    </div>
  </dl>
</template>
