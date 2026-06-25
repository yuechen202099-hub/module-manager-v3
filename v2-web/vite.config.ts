import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/vue/',
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../v2-api/app/static/vue',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, '/')
          if (!normalized.includes('/node_modules/')) return
          if (
            normalized.includes('/node_modules/vue/') ||
            normalized.includes('/node_modules/vue-router/') ||
            normalized.includes('/node_modules/pinia/')
          ) {
            return 'vue-vendor'
          }
          if (normalized.includes('/node_modules/@element-plus/icons-vue/')) {
            return 'element-icons'
          }
          const elementComponent = normalized.match(/\/node_modules\/element-plus\/(?:es|lib)\/components\/([^/]+)\//)
          if (elementComponent) {
            return 'element-components'
          }
          if (normalized.includes('/node_modules/@vueuse/')) {
            return 'vueuse-vendor'
          }
          if (
            normalized.includes('/node_modules/element-plus/') ||
            normalized.includes('/node_modules/@element-plus/')
          ) {
            return 'element-vendor'
          }
          if (
            normalized.includes('/node_modules/async-validator/') ||
            normalized.includes('/node_modules/dayjs/') ||
            normalized.includes('/node_modules/lodash-unified/')
          ) {
            return 'element-utils'
          }
          if (normalized.includes('/node_modules/axios/')) {
            return 'http-vendor'
          }
          return 'vendor'
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
