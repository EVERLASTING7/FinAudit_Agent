<script setup lang="ts">
import ErrorState from '@/components/ErrorState.vue'
</script>

<template>
  <section class="page">
    <ErrorState
      title="无权访问或资源不可用"
      message="当前账号不能访问该页面。系统未加载目标对象信息。"
      code="AUTH_FORBIDDEN"
      suggestion="请返回有权限的页面；权限如有变更，请重新登录后再试。"
    >
      <template #actions>
        <RouterLink class="button button-primary" :to="{ name: 'dashboard' }">返回工作台</RouterLink>
      </template>
    </ErrorState>
  </section>
</template>
