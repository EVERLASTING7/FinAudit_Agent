<script setup lang="ts">
import TraceIdCopy from './TraceIdCopy.vue'

withDefaults(
  defineProps<{
    title?: string
    message: string
    code: string
    suggestion?: string
    traceId?: string
  }>(),
  {
    title: '请求未完成',
    suggestion: '请稍后重试，问题持续时请联系系统管理员。',
    traceId: '',
  },
)
</script>

<template>
  <section class="state-card state-card-error" role="alert">
    <span class="state-icon" aria-hidden="true">!</span>
    <div>
      <h2>{{ title }}</h2>
      <p>{{ message }}</p>
      <dl class="state-details">
        <div>
          <dt>错误码</dt>
          <dd><code>{{ code }}</code></dd>
        </div>
        <div>
          <dt>建议操作</dt>
          <dd>{{ suggestion }}</dd>
        </div>
      </dl>
      <TraceIdCopy v-if="traceId" :trace-id="traceId" />
      <div v-if="$slots.actions" class="state-actions">
        <slot name="actions" />
      </div>
    </div>
  </section>
</template>
