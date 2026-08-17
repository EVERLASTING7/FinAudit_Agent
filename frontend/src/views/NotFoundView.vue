<script setup lang="ts">
import ErrorState from '@/components/ErrorState.vue'
</script>

<template>
  <section class="page">
    <ErrorState
      title="页面不存在"
      message="请求的页面不存在或已被移除。"
      code="RESOURCE_NOT_FOUND"
      suggestion="请返回工作台并从导航重新进入。"
    >
      <template #actions>
        <RouterLink class="button button-primary" :to="{ name: 'dashboard' }">返回工作台</RouterLink>
      </template>
    </ErrorState>
  </section>
</template>
