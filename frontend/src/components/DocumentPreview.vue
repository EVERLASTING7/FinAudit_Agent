<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    page?: number
    pageCount?: number
    highlightLabel?: string
  }>(),
  {
    page: 1,
    pageCount: 1,
    highlightLabel: '',
  },
)
</script>

<template>
  <section class="document-preview" :aria-label="`${title} 原文件预览演示`">
    <header class="document-preview-toolbar">
      <div>
        <strong>{{ title }}</strong>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
      </div>
      <div class="document-preview-tools" aria-label="预览工具演示">
        <button type="button" title="缩小" disabled>−</button>
        <span>100%</span>
        <button type="button" title="放大" disabled>＋</button>
        <button type="button" disabled>适应宽度</button>
      </div>
    </header>
    <div class="document-canvas">
      <article class="document-paper">
        <div class="document-logo">FinAudit · 文档预览</div>
        <h3>{{ title }}</h3>
        <p class="document-meta-line">文件内容仅用于界面布局演示，不包含真实业务数据。</p>
        <div class="document-line document-line-long" />
        <div class="document-line" />
        <div class="document-line document-line-short" />
        <div v-if="highlightLabel" class="document-highlight">
          <span>{{ highlightLabel }}</span>
          <div class="document-line document-line-long" />
          <div class="document-line" />
        </div>
        <div v-else class="document-table-mock">
          <span v-for="cell in 12" :key="cell" />
        </div>
        <div class="document-line document-line-long" />
        <div class="document-line document-line-short" />
      </article>
    </div>
    <footer class="document-preview-foot">
      <span v-if="highlightLabel">已定位：{{ highlightLabel }}</span>
      <span v-else>可用文本证据替代视图</span>
    </footer>
  </section>
</template>
