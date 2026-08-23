<script setup lang="ts">
import { computed } from 'vue'

import { code128Bars } from '@/features/collectorTransfer/code128'

const props = withDefaults(defineProps<{ value?: string | null; label?: string }>(), {
  label: '条形码',
})

const displayValue = computed(() => props.value ?? '')

const barcode = computed(() => {
  if (!displayValue.value.trim()) return null
  try {
    return code128Bars(displayValue.value)
  } catch {
    return null
  }
})
</script>

<template>
  <figure class="code128">
    <svg
      v-if="barcode"
      class="code128__svg"
      :viewBox="`0 0 ${barcode.moduleCount} 54`"
      role="img"
      :aria-label="`${label}：${displayValue}`"
      preserveAspectRatio="none"
      shape-rendering="crispEdges"
    >
      <title>{{ label }} {{ displayValue }}</title>
      <rect width="100%" height="54" fill="#fff" />
      <rect
        v-for="(bar, index) in barcode.bars"
        :key="`${bar.x}-${index}`"
        :x="bar.x"
        y="0"
        :width="bar.width"
        height="54"
        fill="#111"
      />
    </svg>
    <div v-else class="code128__empty">编号为空或包含条形码不支持的字符</div>
    <figcaption>{{ displayValue.trim() ? displayValue : '未提供编号' }}</figcaption>
  </figure>
</template>

<style scoped>
.code128 {
  display: grid;
  gap: 7px;
  margin: 0;
  padding: 12px 14px 9px;
  border: 1px solid #e1e3e1;
  border-radius: 7px;
  background: #fff;
}

.code128__svg {
  width: 100%;
  height: 54px;
}

.code128__empty {
  display: grid;
  min-height: 54px;
  place-items: center;
  color: #9f3630;
  font-size: 12px;
}

figcaption {
  overflow-wrap: anywhere;
  color: #17211b;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-align: center;
}
</style>
