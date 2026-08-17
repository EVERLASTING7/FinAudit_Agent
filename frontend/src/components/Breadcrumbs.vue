<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const parent = computed(() => route.meta.parent)
</script>

<template>
  <nav class="breadcrumbs" aria-label="面包屑">
    <RouterLink v-if="route.name !== 'dashboard'" :to="{ name: 'dashboard' }">工作台</RouterLink>
    <span v-else aria-current="page">工作台</span>
    <template v-if="parent">
      <span aria-hidden="true">/</span>
      <RouterLink :to="{ name: parent.name }">{{ parent.title }}</RouterLink>
    </template>
    <template v-if="route.name !== 'dashboard'">
      <span aria-hidden="true">/</span>
      <span aria-current="page">{{ route.meta.title }}</span>
    </template>
  </nav>
</template>
