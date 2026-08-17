<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/services/api'
import { authApi } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const rememberMe = ref(false)
const errorMessage = ref('')
const successMessage = ref('')
const isSubmitting = ref(false)
const isRetryingLogout = ref(false)
const passwordChangeToken = ref<string | null>(null)
const newPassword = ref('')
const confirmPassword = ref('')
const requiresPasswordChange = computed(() => passwordChangeToken.value !== null)

function safeRedirectPath(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/dashboard'
}

function safeErrorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : '请求未完成，请稍后重试。'
}

async function submitLogin(): Promise<void> {
  errorMessage.value = ''
  successMessage.value = ''
  if (!username.value || !password.value) {
    errorMessage.value = '请输入用户名和密码。'
    return
  }

  isSubmitting.value = true
  try {
    await auth.signIn({
      username: username.value,
      password: password.value,
      rememberMe: rememberMe.value,
    })
    await router.replace(safeRedirectPath(route.query.redirect))
  } catch (error: unknown) {
    if (
      error instanceof ApiError &&
      error.code === 'AUTH_PASSWORD_CHANGE_REQUIRED' &&
      error.data
    ) {
      passwordChangeToken.value = error.data.passwordChangeToken
    } else {
      errorMessage.value = safeErrorMessage(error)
    }
  } finally {
    password.value = ''
    isSubmitting.value = false
  }
}

async function submitPasswordChange(): Promise<void> {
  errorMessage.value = ''
  successMessage.value = ''
  const activeToken = passwordChangeToken.value
  if (!activeToken || !newPassword.value) {
    errorMessage.value = '请输入新密码。'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的新密码不一致。'
    return
  }

  isSubmitting.value = true
  try {
    await authApi.changePassword(activeToken, newPassword.value)
    passwordChangeToken.value = null
    successMessage.value = '密码已修改，请使用新密码重新登录。'
  } catch (error: unknown) {
    errorMessage.value = safeErrorMessage(error)
  } finally {
    newPassword.value = ''
    confirmPassword.value = ''
    isSubmitting.value = false
  }
}

function cancelPasswordChange(): void {
  passwordChangeToken.value = null
  newPassword.value = ''
  confirmPassword.value = ''
  errorMessage.value = ''
}

async function retryRemoteLogout(): Promise<void> {
  isRetryingLogout.value = true
  try {
    await auth.signOut()
  } finally {
    isRetryingLogout.value = false
  }
}

onBeforeUnmount(() => {
  passwordChangeToken.value = null
})
</script>

<template>
  <main class="login-page">
    <section class="login-brand" aria-labelledby="product-title">
      <p class="eyebrow">可信 · 可追溯 · 人工最终复核</p>
      <h1 id="product-title">FinAudit Agent</h1>
      <p>统一管理财务文档、审核任务、风险证据和版本化报告。</p>
      <ul class="login-feature-list">
        <li>确定性规则与 AI 解释分层</li>
        <li>合同、发票与制度证据可追溯</li>
        <li>执行快照和报告版本不可覆盖</li>
      </ul>
      <p class="login-disclaimer">AI 解释不替代确定性规则与人工最终复核。</p>
    </section>

    <section class="login-panel" aria-labelledby="login-title">
      <div>
        <p class="eyebrow">安全会话</p>
        <h2 id="login-title">{{ requiresPasswordChange ? '修改初始密码' : '登录' }}</h2>
        <p v-if="requiresPasswordChange">完成一次性受限换密后，请使用新密码重新登录。</p>
        <p v-else>使用组织账号登录。访问权限由后端会话与权限字典统一校验。</p>
      </div>

      <div v-if="auth.remoteLogoutUnconfirmed" class="form-error" role="alert">
        <p>已清除本地登录状态，但服务器端会话撤销尚未确认。</p>
        <p>当前设备上的 Refresh 会话可能仍有效，请勿在共享设备上直接离开。</p>
        <button
          class="button button-secondary"
          type="button"
          :disabled="isRetryingLogout"
          @click="retryRemoteLogout"
        >
          {{ isRetryingLogout ? '重试中…' : '重试服务器退出' }}
        </button>
      </div>

      <form v-if="!requiresPasswordChange" @submit.prevent="submitLogin">
        <label for="username">用户名<span aria-hidden="true"> *</span></label>
        <input
          id="username"
          v-model="username"
          name="username"
          autocomplete="username"
          required
          maxlength="100"
        />

        <label for="password">密码<span aria-hidden="true"> *</span></label>
        <input
          id="password"
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
          maxlength="200"
        />

        <label class="checkbox-field" for="remember-me">
          <input id="remember-me" v-model="rememberMe" type="checkbox" />
          记住我（由后端决定会话期限）
        </label>

        <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
        <p v-if="successMessage" class="form-help" role="status">{{ successMessage }}</p>
        <button class="button button-primary button-full" type="submit" :disabled="isSubmitting">
          {{ isSubmitting ? '登录中…' : '登录' }}
        </button>
      </form>

      <form v-else @submit.prevent="submitPasswordChange">
        <label for="new-password">新密码<span aria-hidden="true"> *</span></label>
        <input
          id="new-password"
          v-model="newPassword"
          name="new-password"
          type="password"
          autocomplete="new-password"
          required
          maxlength="200"
        />

        <label for="confirm-password">确认新密码<span aria-hidden="true"> *</span></label>
        <input
          id="confirm-password"
          v-model="confirmPassword"
          name="confirm-password"
          type="password"
          autocomplete="new-password"
          required
          maxlength="200"
        />

        <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
        <div class="form-actions">
          <button class="button button-secondary" type="button" @click="cancelPasswordChange">
            返回登录
          </button>
          <button class="button button-primary" type="submit" :disabled="isSubmitting">
            {{ isSubmitting ? '修改中…' : '修改密码' }}
          </button>
        </div>
      </form>

      <p class="security-note">Access Token 仅保存在当前页面内存中，Refresh Token 由同源 HttpOnly Cookie 保管。</p>
    </section>
  </main>
</template>
