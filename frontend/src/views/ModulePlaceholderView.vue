<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import EmptyState from '@/components/EmptyState.vue'
import StatusTag from '@/components/StatusTag.vue'

const route = useRoute()

const title = computed(() => route.meta.title)
const description = computed(() => route.meta.description ?? '业务模块入口')
</script>

<template>
  <section class="page">
    <header class="page-header">
      <div>
        <div class="page-kicker">{{ route.meta.uiCode }} · 基础路由</div>
        <h1>{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
      <StatusTag status="ready" label="路由已就绪" />
    </header>

    <div class="notice-banner" role="note">
      当前仅交付全局布局、权限路由和通用组件；业务数据与操作将在对应后续任务中实现。
    </div>

    <EmptyState title="业务页面尚未实现" description="此占位不会请求接口、生成模拟进度或伪造业务结果。" />
  </section>
</template>
