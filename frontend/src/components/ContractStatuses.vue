<script setup lang="ts">
import StatusTag from './StatusTag.vue'

type ContractConfirmationStatus = 'unconfirmed' | 'confirmed' | 'rejected'
type ContractStatus = 'draft' | 'active' | 'expired' | 'terminated' | 'archived'

const confirmationLabels: Readonly<Record<ContractConfirmationStatus, string>> = {
  unconfirmed: '未确认',
  confirmed: '已确认',
  rejected: '已拒绝',
}

const contractLabels: Readonly<Record<ContractStatus, string>> = {
  draft: '草稿',
  active: '有效',
  expired: '到期',
  terminated: '终止',
  archived: '归档',
}

defineProps<{
  confirmationStatus: ContractConfirmationStatus
  contractStatus: ContractStatus
}>()
</script>

<template>
  <dl class="contract-statuses" aria-label="合同确认状态与合同状态">
    <div data-status-kind="confirmation">
      <dt>确认状态</dt>
      <dd>
        <StatusTag
          :status="confirmationStatus"
          :label="confirmationLabels[confirmationStatus]"
        />
      </dd>
    </div>
    <div data-status-kind="contract">
      <dt>合同状态</dt>
      <dd><StatusTag :status="contractStatus" :label="contractLabels[contractStatus]" /></dd>
    </div>
  </dl>
</template>
