<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import BreakGlassPanel from '@/components/BreakGlassPanel.vue'
import PageHeader from '@/components/PageHeader.vue'
import SectionCard from '@/components/SectionCard.vue'
import StatusTag from '@/components/StatusTag.vue'
import { ApiError } from '@/services/api'
import { roleCodes, type RoleCode } from '@/services/auth'
import { userApi, type UserListData, type UserListItem } from '@/services/users'
import { roleLabels } from '@/stores/auth'

const pageSize = 20
const result = ref<UserListData | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const errorTraceId = ref('')
const writeErrorMessage = ref('')
const writeTraceId = ref('')
const successMessage = ref('')
const mutationLoading = ref(false)
const currentPage = ref(1)
const requestedPage = ref(1)
const requestedCursor = ref<string | undefined>()
const cursorStack = ref<Array<string | undefined>>([undefined])
const selectedUserId = ref('')
const editStatus = ref<'active' | 'disabled'>('active')
const editPassword = ref('')
const editRoles = ref<RoleCode[]>([])
const createUsername = ref('')
const createDisplayName = ref('')
const createPassword = ref('')
const createRoles = ref<RoleCode[]>(['read_only'])
const createIdempotencyKey = ref('')
const statusIdempotencyKey = ref('')
const passwordIdempotencyKey = ref('')
const rolesIdempotencyKey = ref('')
let requestController: AbortController | null = null
let writeController: AbortController | null = null

const selectedUser = computed(
  () => result.value?.items.find((user) => user.id === selectedUserId.value) ?? null,
)

function formatListError(error: unknown): void {
  errorTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof ApiError && error.status === 403) {
    errorMessage.value = '当前账号无权读取用户列表。'
  } else if (error instanceof ApiError && error.status === 401) {
    errorMessage.value = '登录状态已失效，请重新登录。'
  } else {
    errorMessage.value = '用户列表加载失败，请稍后重试。'
  }
}

function formatWriteError(error: unknown): void {
  writeTraceId.value = error instanceof ApiError ? error.traceId : ''
  if (error instanceof TypeError) {
    writeErrorMessage.value = '输入不符合约束，请检查必填项、密码和角色。'
  } else if (error instanceof ApiError && error.status === 409) {
    writeErrorMessage.value = '操作与当前数据版本冲突，请刷新列表后重试。'
  } else if (error instanceof ApiError && error.status === 403) {
    writeErrorMessage.value = '当前账号无权执行此操作。'
  } else if (error instanceof ApiError && error.status === 401) {
    writeErrorMessage.value = '登录状态已失效，请重新登录。'
  } else if (error instanceof ApiError && error.status === 422) {
    writeErrorMessage.value = '请求内容不符合服务端约束。'
  } else {
    writeErrorMessage.value = '操作未完成，请稍后使用相同内容重试。'
  }
}

function resetWriteFeedback(): void {
  writeErrorMessage.value = ''
  writeTraceId.value = ''
  successMessage.value = ''
}

function mutationKey(target: typeof createIdempotencyKey, prefix: string): string {
  if (!target.value) target.value = `${prefix}.${globalThis.crypto.randomUUID()}`
  return target.value
}

async function loadPage(cursor: string | undefined, page: number): Promise<void> {
  requestController?.abort()
  requestController = null
  requestedCursor.value = cursor
  requestedPage.value = page
  errorMessage.value = ''
  errorTraceId.value = ''
  loading.value = false

  const controller = new AbortController()
  requestController = controller
  loading.value = true
  try {
    const response = await userApi.list(pageSize, cursor, controller.signal)
    if (requestController === controller && !controller.signal.aborted) {
      result.value = response
      currentPage.value = page
      if (!response.items.some((user) => user.id === selectedUserId.value)) {
        selectedUserId.value = ''
      }
    }
  } catch (error) {
    if (requestController === controller && !controller.signal.aborted) formatListError(error)
  } finally {
    if (requestController === controller) {
      requestController = null
      loading.value = false
    }
  }
}

function retryPage(): void {
  void loadPage(requestedCursor.value, requestedPage.value)
}

function loadNextPage(): void {
  if (!result.value?.nextCursor) return
  const cursor = result.value.nextCursor
  cursorStack.value = [...cursorStack.value.slice(0, currentPage.value), cursor]
  void loadPage(cursor, currentPage.value + 1)
}

function loadPreviousPage(): void {
  if (currentPage.value <= 1) return
  const targetPage = currentPage.value - 1
  cursorStack.value = cursorStack.value.slice(0, targetPage)
  void loadPage(cursorStack.value[targetPage - 1], targetPage)
}

function selectUser(user: UserListItem): void {
  selectedUserId.value = user.id
  editStatus.value = user.status === 'disabled' ? 'disabled' : 'active'
  editPassword.value = ''
  editRoles.value = [...user.fixedRoles]
  statusIdempotencyKey.value = ''
  passwordIdempotencyKey.value = ''
  rolesIdempotencyKey.value = ''
  resetWriteFeedback()
}

function applyMutationResult(user: UserListItem, message: string): void {
  if (result.value) {
    result.value = {
      ...result.value,
      items: result.value.items.map((item) => (item.id === user.id ? user : item)),
    }
  }
  selectUser(user)
  successMessage.value = message
}

async function createUser(): Promise<void> {
  if (mutationLoading.value) return
  resetWriteFeedback()
  mutationLoading.value = true
  const controller = new AbortController()
  writeController = controller
  try {
    await userApi.create(
      {
        username: createUsername.value,
        displayName: createDisplayName.value,
        initialPassword: createPassword.value,
        fixedRoles: [...createRoles.value].sort(),
      },
      mutationKey(createIdempotencyKey, 'user-create'),
      controller.signal,
    )
    createUsername.value = ''
    createDisplayName.value = ''
    createPassword.value = ''
    createRoles.value = ['read_only']
    createIdempotencyKey.value = ''
    successMessage.value = '用户已创建；首次登录必须修改初始密码。'
    await loadPage(undefined, 1)
  } catch (error) {
    if (!controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) writeController = null
    mutationLoading.value = false
  }
}

async function updateStatus(): Promise<void> {
  const user = selectedUser.value
  if (!user || mutationLoading.value) return
  resetWriteFeedback()
  mutationLoading.value = true
  const controller = new AbortController()
  writeController = controller
  try {
    const updated = await userApi.updateStatus(
      user.id,
      editStatus.value,
      user.rowVersion,
      mutationKey(statusIdempotencyKey, 'user-status'),
      controller.signal,
    )
    statusIdempotencyKey.value = ''
    applyMutationResult(updated, '用户状态已更新，现有会话已按规则处理。')
  } catch (error) {
    if (!controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) writeController = null
    mutationLoading.value = false
  }
}

async function resetPassword(): Promise<void> {
  const user = selectedUser.value
  if (!user || mutationLoading.value) return
  resetWriteFeedback()
  mutationLoading.value = true
  const controller = new AbortController()
  writeController = controller
  try {
    const updated = await userApi.resetPassword(
      user.id,
      editPassword.value,
      user.rowVersion,
      mutationKey(passwordIdempotencyKey, 'user-password'),
      controller.signal,
    )
    editPassword.value = ''
    passwordIdempotencyKey.value = ''
    applyMutationResult(updated, '密码已重置，目标用户的现有会话已撤销。')
  } catch (error) {
    if (!controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) writeController = null
    mutationLoading.value = false
  }
}

async function replaceRoles(): Promise<void> {
  const user = selectedUser.value
  if (!user || mutationLoading.value) return
  resetWriteFeedback()
  mutationLoading.value = true
  const controller = new AbortController()
  writeController = controller
  try {
    const updated = await userApi.replaceRoles(
      user.id,
      [...editRoles.value].sort(),
      user.rowVersion,
      mutationKey(rolesIdempotencyKey, 'user-roles'),
      controller.signal,
    )
    rolesIdempotencyKey.value = ''
    applyMutationResult(updated, '固定角色已替换，历史授权记录已保留。')
  } catch (error) {
    if (!controller.signal.aborted) formatWriteError(error)
  } finally {
    if (writeController === controller) writeController = null
    mutationLoading.value = false
  }
}

void loadPage(undefined, 1)
onUnmounted(() => {
  requestController?.abort()
  writeController?.abort()
})
</script>

<template>
  <section class="page page-stack">
    <PageHeader
      ui-code="UI-014"
      title="用户管理"
      description="创建用户，管理启停、密码和固定角色；所有写操作均受幂等、并发版本与操作日志保护。"
    />

    <div v-if="successMessage" class="callout callout-success" role="status">
      <div><strong>{{ successMessage }}</strong></div>
    </div>
    <div v-if="writeErrorMessage" class="callout callout-danger" role="alert">
      <div>
        <strong>{{ writeErrorMessage }}</strong>
        <span v-if="writeTraceId" class="mono-text"> Trace ID：{{ writeTraceId }}</span>
      </div>
    </div>

    <SectionCard title="创建用户" description="初始密码不会显示在列表中；目标用户首次登录必须修改密码。">
      <form class="form-grid" data-testid="create-user-form" @submit.prevent="createUser">
        <div class="form-field">
          <label for="create-username">用户名</label>
          <input
            id="create-username"
            v-model="createUsername"
            class="text-input"
            maxlength="100"
            pattern="[a-z0-9][a-z0-9._-]{0,99}"
            autocomplete="off"
            required
            @input="createIdempotencyKey = ''"
          />
        </div>
        <div class="form-field">
          <label for="create-display-name">显示名称</label>
          <input
            id="create-display-name"
            v-model="createDisplayName"
            class="text-input"
            maxlength="100"
            autocomplete="off"
            required
            @input="createIdempotencyKey = ''"
          />
        </div>
        <div class="form-field form-field-full">
          <label for="create-password">初始密码</label>
          <input
            id="create-password"
            v-model="createPassword"
            class="text-input"
            type="password"
            minlength="6"
            maxlength="512"
            autocomplete="new-password"
            required
            @input="createIdempotencyKey = ''"
          />
          <p class="form-help">密码至少 6 个字符，常见弱密码仍会被拒绝；表单不会持久化密码。</p>
        </div>
        <fieldset class="form-field form-field-full">
          <legend>固定角色</legend>
          <label v-for="role in roleCodes" :key="role" class="checkbox-label">
            <input
              v-model="createRoles"
              type="checkbox"
              :value="role"
              @change="createIdempotencyKey = ''"
            />
            {{ roleLabels[role] }}
          </label>
        </fieldset>
        <div class="form-actions">
          <button class="button button-primary" type="submit" :disabled="mutationLoading">
            {{ mutationLoading ? '提交中…' : '创建用户' }}
          </button>
        </div>
      </form>
    </SectionCard>

    <div v-if="loading" class="section-card" role="status" aria-live="polite">
      正在加载用户列表…
    </div>

    <SectionCard v-else-if="errorMessage" title="无法显示用户列表">
      <div class="callout callout-danger" role="alert">
        <div>
          <strong>{{ errorMessage }}</strong>
          <span v-if="errorTraceId" class="mono-text"> Trace ID：{{ errorTraceId }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button
          class="button button-primary"
          type="button"
          data-testid="retry-user-list"
          @click="retryPage"
        >
          重试
        </button>
      </div>
    </SectionCard>

    <SectionCard
      v-else-if="result"
      title="用户与固定角色"
      :description="`当前页 ${result.items.length} 条记录；列表不返回认证敏感信息。`"
      compact
    >
      <div v-if="result.items.length" class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr><th>用户</th><th>状态</th><th>固定角色</th><th>版本</th><th>写操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="user in result.items" :key="user.id">
              <td>
                <span class="table-primary">
                  <strong>{{ user.displayName }}</strong>
                  <span>{{ user.username }}</span>
                </span>
              </td>
              <td><StatusTag :status="user.status" /></td>
              <td>
                <template v-if="user.fixedRoles.length">
                  <span v-for="role in user.fixedRoles" :key="role" class="pill">
                    {{ roleLabels[role] }}
                  </span>
                </template>
                <span v-else>无固定角色</span>
              </td>
              <td class="mono-text">{{ user.rowVersion }}</td>
              <td>
                <button
                  class="button button-secondary button-small"
                  type="button"
                  :data-testid="`manage-user-${user.id}`"
                  @click="selectUser(user)"
                >
                  管理
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty-inline">当前页没有用户。</div>
      <div class="pager">
        <span>第 {{ currentPage }} 页 · 每页 {{ result.pageSize }} 条</span>
        <div class="pager-buttons">
          <button
            type="button"
            aria-label="上一页"
            :disabled="currentPage <= 1 || loading"
            @click="loadPreviousPage"
          >
            ‹
          </button>
          <button type="button" aria-current="page" disabled>{{ currentPage }}</button>
          <button
            type="button"
            aria-label="下一页"
            :disabled="!result.nextCursor || loading"
            @click="loadNextPage"
          >
            ›
          </button>
        </div>
      </div>
    </SectionCard>

    <SectionCard
      v-if="selectedUser"
      title="用户写操作"
      :description="`${selectedUser.displayName}（${selectedUser.username}），当前版本 ${selectedUser.rowVersion}`"
    >
      <div class="form-grid">
        <form class="form-field" data-testid="user-status-form" @submit.prevent="updateStatus">
          <label for="edit-status">账号状态</label>
          <select
            id="edit-status"
            v-model="editStatus"
            class="select-input"
            @change="statusIdempotencyKey = ''"
          >
            <option value="active">启用</option>
            <option value="disabled">停用</option>
          </select>
          <button class="button button-secondary" type="submit" :disabled="mutationLoading">
            更新状态
          </button>
        </form>

        <form class="form-field" data-testid="user-password-form" @submit.prevent="resetPassword">
          <label for="edit-password">新密码</label>
          <input
            id="edit-password"
            v-model="editPassword"
            class="text-input"
            type="password"
            minlength="6"
            maxlength="512"
            autocomplete="new-password"
            required
            @input="passwordIdempotencyKey = ''"
          />
          <p class="form-help">密码至少 6 个字符，最终由服务端统一校验。</p>
          <button class="button button-secondary" type="submit" :disabled="mutationLoading">
            重置密码并撤销会话
          </button>
        </form>

        <form class="form-field form-field-full" data-testid="user-roles-form" @submit.prevent="replaceRoles">
          <fieldset class="form-field">
            <legend>替换固定角色</legend>
            <label v-for="role in roleCodes" :key="role" class="checkbox-label">
              <input
                v-model="editRoles"
                type="checkbox"
                :value="role"
                @change="rolesIdempotencyKey = ''"
              />
              {{ roleLabels[role] }}
            </label>
          </fieldset>
          <p class="form-help">提交的是完整替换集合；系统会保护最后一名有效长期管理员并校验职责分离。</p>
          <button class="button button-secondary" type="submit" :disabled="mutationLoading">
            替换固定角色
          </button>
        </form>
      </div>
    </SectionCard>

    <SectionCard
      title="Break-glass 临时授权"
      description="创建、独立审批或提前撤销限时角色；业务原因仅进入授权事实，不写入操作日志摘要。"
    >
      <BreakGlassPanel :users="result?.items ?? []" />
    </SectionCard>
  </section>
</template>
