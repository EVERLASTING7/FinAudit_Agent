<script setup lang="ts">
import { onUnmounted, ref } from 'vue'

import { ApiError } from '@/services/api'
import {
  breakGlassApi,
  breakGlassRoleCodes,
  type BreakGlassData,
  type BreakGlassRoleCode,
} from '@/services/breakGlass'
import type { UserListItem } from '@/services/users'
import { roleLabels } from '@/stores/auth'

defineProps<{ users: UserListItem[] }>()

const targetUserId = ref('')
const targetRoleCode = ref<BreakGlassRoleCode>('finance_reviewer')
const durationSeconds = ref(3600)
const requestReason = ref('')
const requestId = ref('')
const rowVersion = ref('')
const decision = ref<'approved' | 'rejected'>('approved')
const decisionReason = ref('')
const revokeReason = ref('')
const requestKey = ref('')
const decisionKey = ref('')
const revokeKey = ref('')
const busy = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const successMessage = ref('')
const lastResult = ref<BreakGlassData | null>(null)
let controller: AbortController | null = null

function nextKey(target: typeof requestKey, prefix: string): string {
  if (!target.value) target.value = `${prefix}.${globalThis.crypto.randomUUID()}`
  return target.value
}

function clearFeedback(): void {
  errorMessage.value = ''
  errorTraceId.value = ''
  successMessage.value = ''
}

function showError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof TypeError) {
    errorMessage.value = '输入不符合临时授权约束。'
  } else if (error instanceof ApiError && error.status === 409) {
    errorMessage.value = '申请状态、数据版本或双人控制资格冲突。'
  } else if (error instanceof ApiError && error.status === 404) {
    errorMessage.value = '目标用户或临时授权申请不存在。'
  } else if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权执行此临时授权操作。'
  } else {
    errorMessage.value = '临时授权操作未完成，请使用相同内容重试。'
  }
}

function applyResult(value: BreakGlassData, message: string): void {
  lastResult.value = value
  requestId.value = value.id
  rowVersion.value = value.rowVersion
  successMessage.value = message
}

async function createRequest(): Promise<void> {
  if (busy.value) return
  clearFeedback()
  busy.value = true
  const active = new AbortController()
  controller = active
  try {
    const value = await breakGlassApi.create(
      {
        targetUserId: targetUserId.value,
        targetRoleCode: targetRoleCode.value,
        requestedDurationSeconds: durationSeconds.value,
        reason: requestReason.value,
      },
      nextKey(requestKey, 'break-glass-request'),
      active.signal,
    )
    requestReason.value = ''
    requestKey.value = ''
    applyResult(value, '临时授权申请已创建，必须由独立审批人决定。')
  } catch (error) {
    if (!active.signal.aborted) showError(error)
  } finally {
    if (controller === active) controller = null
    busy.value = false
  }
}

async function decideRequest(): Promise<void> {
  if (busy.value) return
  clearFeedback()
  busy.value = true
  const active = new AbortController()
  controller = active
  try {
    const value = await breakGlassApi.decide(
      requestId.value,
      decision.value,
      decisionReason.value,
      rowVersion.value,
      nextKey(decisionKey, 'break-glass-decision'),
      active.signal,
    )
    decisionReason.value = ''
    decisionKey.value = ''
    applyResult(value, decision.value === 'approved' ? '临时授权已批准。' : '临时授权已拒绝。')
  } catch (error) {
    if (!active.signal.aborted) showError(error)
  } finally {
    if (controller === active) controller = null
    busy.value = false
  }
}

async function revokeRequest(): Promise<void> {
  if (busy.value) return
  clearFeedback()
  busy.value = true
  const active = new AbortController()
  controller = active
  try {
    const value = await breakGlassApi.revoke(
      requestId.value,
      revokeReason.value,
      rowVersion.value,
      nextKey(revokeKey, 'break-glass-revoke'),
      active.signal,
    )
    revokeReason.value = ''
    revokeKey.value = ''
    applyResult(value, '临时授权已撤销。')
  } catch (error) {
    if (!active.signal.aborted) showError(error)
  } finally {
    if (controller === active) controller = null
    busy.value = false
  }
}

onUnmounted(() => controller?.abort())
</script>

<template>
  <div class="page-stack">
    <div class="callout callout-warning">
      <div>
        <strong>双人控制与最长四小时</strong>
        申请人和目标用户都不能审批该申请；批准后仍可由有权限的独立用户提前撤销。
      </div>
    </div>
    <div v-if="successMessage" class="callout callout-success" role="status">
      <div><strong>{{ successMessage }}</strong></div>
    </div>
    <div v-if="errorMessage" class="callout callout-danger" role="alert">
      <div>
        <strong>{{ errorMessage }}</strong>
        <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
      </div>
    </div>

    <form class="form-grid" data-testid="break-glass-create-form" @submit.prevent="createRequest">
      <div class="form-field">
        <label for="break-glass-target">目标用户 ID</label>
        <input
          id="break-glass-target"
          v-model="targetUserId"
          class="text-input mono-text"
          list="break-glass-users"
          required
          @input="requestKey = ''"
        />
        <datalist id="break-glass-users">
          <option v-for="user in users" :key="user.id" :value="user.id">
            {{ user.displayName }}（{{ user.username }}）
          </option>
        </datalist>
      </div>
      <div class="form-field">
        <label for="break-glass-role">临时角色</label>
        <select
          id="break-glass-role"
          v-model="targetRoleCode"
          class="select-input"
          @change="requestKey = ''"
        >
          <option v-for="role in breakGlassRoleCodes" :key="role" :value="role">
            {{ roleLabels[role] }}
          </option>
        </select>
      </div>
      <div class="form-field">
        <label for="break-glass-duration">授权时长（秒）</label>
        <input
          id="break-glass-duration"
          v-model.number="durationSeconds"
          class="text-input"
          type="number"
          min="1"
          max="14400"
          step="1"
          required
          @input="requestKey = ''"
        />
      </div>
      <div class="form-field form-field-full">
        <label for="break-glass-reason">申请原因</label>
        <textarea
          id="break-glass-reason"
          v-model="requestReason"
          class="textarea-input"
          maxlength="500"
          required
          @input="requestKey = ''"
        />
      </div>
      <div class="form-actions">
        <button class="button button-primary" type="submit" :disabled="busy">
          创建临时授权申请
        </button>
      </div>
    </form>

    <div v-if="lastResult" class="callout">
      <div>
        <strong>最近结果：{{ lastResult.status }}</strong>
        <span class="mono-text"> 申请 {{ lastResult.id }} · 版本 {{ lastResult.rowVersion }}</span>
      </div>
    </div>

    <form class="form-grid" data-testid="break-glass-decision-form" @submit.prevent="decideRequest">
      <div class="form-field">
        <label for="break-glass-request-id">申请 ID</label>
        <input
          id="break-glass-request-id"
          v-model="requestId"
          class="text-input mono-text"
          required
          @input="decisionKey = ''; revokeKey = ''"
        />
      </div>
      <div class="form-field">
        <label for="break-glass-row-version">当前版本</label>
        <input
          id="break-glass-row-version"
          v-model="rowVersion"
          class="text-input mono-text"
          inputmode="numeric"
          required
          @input="decisionKey = ''; revokeKey = ''"
        />
      </div>
      <div class="form-field">
        <label for="break-glass-decision">审批决定</label>
        <select
          id="break-glass-decision"
          v-model="decision"
          class="select-input"
          @change="decisionKey = ''"
        >
          <option value="approved">批准</option>
          <option value="rejected">拒绝</option>
        </select>
      </div>
      <div class="form-field form-field-full">
        <label for="break-glass-decision-reason">审批原因</label>
        <textarea
          id="break-glass-decision-reason"
          v-model="decisionReason"
          class="textarea-input"
          maxlength="500"
          required
          @input="decisionKey = ''"
        />
      </div>
      <div class="form-actions">
        <button class="button button-secondary" type="submit" :disabled="busy">提交审批决定</button>
      </div>
    </form>

    <form class="form-grid" data-testid="break-glass-revoke-form" @submit.prevent="revokeRequest">
      <div class="form-field form-field-full">
        <label for="break-glass-revoke-reason">提前撤销原因</label>
        <textarea
          id="break-glass-revoke-reason"
          v-model="revokeReason"
          class="textarea-input"
          maxlength="500"
          required
          @input="revokeKey = ''"
        />
      </div>
      <div class="form-actions">
        <button class="button button-danger" type="submit" :disabled="busy">撤销临时授权</button>
      </div>
    </form>
  </div>
</template>
