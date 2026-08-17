<script setup lang="ts">
import { computed } from 'vue'

type StatusTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'

const props = defineProps<{
  status: string
  label?: string
}>()

const labels: Readonly<Record<string, string>> = {
  active: '有效',
  adjusted: '已调整',
  approved: '已批准',
  archived: '已归档',
  blocked: '已阻断',
  building: '构建中',
  candidate: '候选',
  cancel_requested: '正在请求取消',
  cancelled: '已取消',
  clean: '安全检查通过',
  completed: '已完成',
  confirmed: '已确认',
  confirmed_duplicate: '已确认重复',
  confirmed_primary: '已确认主合同',
  consistency_check: '一致性检查中',
  converting: '转换中',
  disabled: '已停用',
  dismissed: '已驳回',
  draft: '草稿',
  error: '错误',
  evaluation_pending: '待评测',
  exception_approved: '已批准例外',
  expired: '已过期',
  failed: '失败',
  generating: '生成中',
  high: '高风险',
  infected: '检出恶意内容',
  locked: '已锁定',
  low: '低风险',
  manual_review_required: '需要人工纠错',
  medium: '中风险',
  none: '无风险',
  not_applicable: '不适用',
  not_checked: '尚未检测',
  not_configured: '未配置扫描器',
  notice: '提示风险',
  open: '未完成',
  passed: '通过',
  outdated: '已过期',
  pending: '待处理',
  pending_audit_review: '待审计复核',
  pending_business_review: '待业务审批',
  pending_confirmation: '待确认',
  pending_finance_review: '待财务复核',
  published: '已发布',
  quality_review: '质量复核中',
  queued: '已排队',
  ready: '质量通过，待激活',
  rejected: '已拒绝',
  returned_for_correction: '已退回修正',
  review_required: '待复核',
  revoked: '已撤销',
  running: '进行中',
  scan_failed: '安全检查失败',
  stored: '已存储',
  succeeded: '已成功',
  suggested: '已建议',
  suspected: '疑似重复',
  superseded: '已被替代',
  unique: '未发现重复',
  unsupported: '不支持扫描',
  uploaded: '已上传',
  unconfirmed: '未确认',
  validating: '校验中',
}

const tones: Readonly<Record<StatusTone, readonly string[]>> = {
  success: [
    'active',
    'approved',
    'clean',
    'completed',
    'confirmed',
    'confirmed_primary',
    'exception_approved',
    'passed',
    'published',
    'ready',
    'stored',
    'succeeded',
    'unique',
  ],
  info: [
    'adjusted',
    'building',
    'candidate',
    'cancel_requested',
    'consistency_check',
    'converting',
    'generating',
    'notice',
    'open',
    'queued',
    'running',
    'suggested',
    'uploaded',
    'validating',
  ],
  warning: [
    'evaluation_pending',
    'low',
    'manual_review_required',
    'medium',
    'not_checked',
    'not_configured',
    'pending',
    'pending_audit_review',
    'pending_business_review',
    'pending_confirmation',
    'pending_finance_review',
    'quality_review',
    'returned_for_correction',
    'review_required',
    'suspected',
    'unconfirmed',
  ],
  danger: [
    'blocked',
    'confirmed_duplicate',
    'disabled',
    'error',
    'failed',
    'high',
    'infected',
    'locked',
    'rejected',
    'revoked',
    'scan_failed',
    'unsupported',
  ],
  neutral: [
    'archived',
    'cancelled',
    'dismissed',
    'draft',
    'expired',
    'none',
    'not_applicable',
    'outdated',
    'superseded',
  ],
}

const tone = computed<StatusTone>(() => {
  const match = (Object.keys(tones) as StatusTone[]).find((key) => tones[key].includes(props.status))
  return match ?? 'neutral'
})
const text = computed(() => props.label ?? labels[props.status] ?? props.status)
</script>

<template>
  <span class="status-tag" :class="`status-tag-${tone}`" :aria-label="`状态：${text}`">
    <span class="status-dot" aria-hidden="true">●</span>
    {{ text }}
  </span>
</template>
