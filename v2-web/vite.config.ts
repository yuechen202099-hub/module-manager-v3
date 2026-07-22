import { createHash } from 'node:crypto'
import { fileURLToPath, URL } from 'node:url'

import { defineConfig, type Rollup } from 'vite'
import vue from '@vitejs/plugin-vue'
import versionArtifact from './src/version.json'

const entryAttestationPrefix =
  `globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={"version":"${versionArtifact.version}"};\n`
const configuredOutDir = process.env.MODULE_MANAGER_VUE_OUT_DIR?.trim()

export default defineConfig({
  base: '/vue/',
  plugins: [
    vue(),
    {
      name: 'emit-runtime-version-artifact',
      enforce: 'post',
      generateBundle: {
        order: 'post',
        handler(_, bundle) {
          const entryChunks = Object.values(bundle).filter(
            (item): item is Rollup.OutputChunk => item.type === 'chunk' && item.isEntry,
          )
          if (entryChunks.length !== 1) {
            throw new Error('Vue build must produce exactly one entry chunk')
          }
          const entryChunk = entryChunks[0]
          entryChunk.code = `${entryAttestationPrefix}${entryChunk.code}`
          const assets = Object.values(bundle)
            .filter((item) => item.fileName !== 'version.json')
            .map((item) => {
              const content = Buffer.from(item.type === 'chunk' ? item.code : item.source)
              return {
                path: item.fileName,
                size: content.byteLength,
                sha256: createHash('sha256').update(content).digest('hex'),
              }
            })
            .sort((left, right) => {
              if (left.path < right.path) return -1
              if (left.path > right.path) return 1
              return 0
            })
          const runtimeVersionArtifact = `${JSON.stringify({
            version: versionArtifact.version,
            entry: entryChunk.fileName,
            entrySha256: createHash('sha256').update(entryChunk.code).digest('hex'),
            assets,
          })}\n`
          this.emitFile({
            type: 'asset',
            fileName: 'version.json',
            source: runtimeVersionArtifact,
          })
        },
      },
    },
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: configuredOutDir || '../v2-api/app/static/vue',
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
