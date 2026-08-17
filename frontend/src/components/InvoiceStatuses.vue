<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type InvoiceConfirmationStatus = 'unconfirmed' | 'confirmed' | 'rejected'
type InvoiceDuplicateStatus =
  | 'not_checked'
  | 'unique'
  | 'suspected'
  | 'confirmed_duplicate'
  | 'exception_approved'

const confirmationLabels: Readonly<Record<InvoiceConfirmationStatus, string>> = {
  unconfirmed: '未确认',
  confirmed: '已确认',
  rejected: '已拒绝',
}

const duplicateLabels: Readonly<Record<InvoiceDuplicateStatus, string>> = {
  not_checked: '尚未检测',
  unique: '当前未发现重复',
  suspected: '疑似重复，需要人工处理',
  confirmed_duplicate: '已确认重复',
  exception_approved: '已批准例外',
}

defineProps<{
  confirmationStatus: InvoiceConfirmationStatus
  duplicateStatus: InvoiceDuplicateStatus
}>()
</script>

<template>
  <dl class="invoice-statuses" aria-label="发票确认状态与重复状态">
    <div data-status-kind="confirmation">
      <dt>确认状态</dt>
      <dd>
        <StatusTag
          :status="confirmationStatus"
          :label="confirmationLabels[confirmationStatus]"
        />
      </dd>
    </div>
    <div data-status-kind="duplicate">
      <dt>重复状态</dt>
      <dd><StatusTag :status="duplicateStatus" :label="duplicateLabels[duplicateStatus]" /></dd>
    </div>
  </dl>
</template>
