import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

import { resolveEnvDir } from './vite-env-policy.ts'

export default defineConfig({
  envDir: resolveEnvDir(process.env.FINAUDIT_LOCAL_OFFLINE_QUALITY),
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
  },
})
