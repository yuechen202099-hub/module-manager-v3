<script setup lang="ts">
import { Close, Connection, Crop, Grid, Odometer, Search } from '@element-plus/icons-vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

type BarcodeType = 'meter' | 'module' | 'collector'
type NormalizedRegion = { x: number; y: number; width: number; height: number }
type ContentRect = { left: number; top: number; width: number; height: number }
type Point = { x: number; y: number }

const MAGNIFIER_SCALE = 2.5
const MIN_SELECTION_CSS_PIXELS = 12
const MAGNIFIER_SIZE = 160

const props = withDefaults(defineProps<{
  src: string
  alt: string
  loading: boolean
  disabled?: boolean
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  scan: [payload: { barcodeType: BarcodeType; region: NormalizedRegion }]
  'image-load': [event: Event]
  'image-error': [event: Event]
  open: []
}>()

const stage = ref<HTMLElement | null>(null)
const contentRect = ref<ContentRect>({ left: 0, top: 0, width: 0, height: 0 })
const naturalSize = ref({ width: 0, height: 0 })
const pointer = ref<Point | null>(null)
const selectionStart = ref<Point | null>(null)
const selectionEnd = ref<Point | null>(null)
const selectedRegion = ref<NormalizedRegion | null>(null)
const barcodeType = ref<BarcodeType | null>(null)
const mode = ref<'view' | 'selecting' | 'ready' | 'submitting'>('view')

let resizeObserver: ResizeObserver | null = null

const selectionStyle = computed(() => {
  const rect = contentRect.value
  const region = selectedRegion.value
  if (!region) return null

  return {
    left: `${rect.left + region.x * rect.width}px`,
    top: `${rect.top + region.y * rect.height}px`,
    width: `${region.width * rect.width}px`,
    height: `${region.height * rect.height}px`,
  }
})

const draftingSelectionStyle = computed(() => {
  const start = selectionStart.value
  const end = selectionEnd.value
  if (!start || !end) return null

  return {
    left: `${Math.min(start.x, end.x)}px`,
    top: `${Math.min(start.y, end.y)}px`,
    width: `${Math.abs(end.x - start.x)}px`,
    height: `${Math.abs(end.y - start.y)}px`,
  }
})

const magnifierStyle = computed(() => {
  const point = pointer.value
  const rect = contentRect.value
  const stageElement = stage.value
  if (!point || !stageElement || !rect.width || !rect.height) return {}

  const left = Math.min(Math.max(0, point.x - MAGNIFIER_SIZE / 2), stageElement.clientWidth - MAGNIFIER_SIZE)
  const top = Math.min(Math.max(0, point.y - MAGNIFIER_SIZE / 2), stageElement.clientHeight - MAGNIFIER_SIZE)
  const imageX = point.x - rect.left
  const imageY = point.y - rect.top

  return {
    left: `${left}px`,
    top: `${top}px`,
    backgroundImage: `url("${props.src.replace(/"/g, '\\"')}")`,
    backgroundSize: `${rect.width * MAGNIFIER_SCALE}px ${rect.height * MAGNIFIER_SCALE}px`,
    backgroundPosition: `${MAGNIFIER_SIZE / 2 - imageX * MAGNIFIER_SCALE}px ${MAGNIFIER_SIZE / 2 - imageY * MAGNIFIER_SCALE}px`,
  }
})

const canScan = computed(() => Boolean(
  !props.disabled &&
  mode.value === 'ready' &&
  barcodeType.value &&
  selectedRegion.value,
))

function updateContentRect() {
  const stageElement = stage.value
  const { width: naturalWidth, height: naturalHeight } = naturalSize.value
  if (!stageElement || !naturalWidth || !naturalHeight) {
    contentRect.value = { left: 0, top: 0, width: 0, height: 0 }
    return
  }

  const scale = Math.min(stageElement.clientWidth / naturalWidth, stageElement.clientHeight / naturalHeight)
  const width = naturalWidth * scale
  const height = naturalHeight * scale
  contentRect.value = {
    left: (stageElement.clientWidth - width) / 2,
    top: (stageElement.clientHeight - height) / 2,
    width,
    height,
  }
}

function rawPoint(event: PointerEvent): Point | null {
  const stageElement = stage.value
  if (!stageElement) return null
  const bounds = stageElement.getBoundingClientRect()
  return { x: event.clientX - bounds.left, y: event.clientY - bounds.top }
}

function pointInContent(event: PointerEvent): Point | null {
  const point = rawPoint(event)
  const rect = contentRect.value
  if (!point || !rect.width || !rect.height) return null
  if (point.x < rect.left || point.x > rect.left + rect.width || point.y < rect.top || point.y > rect.top + rect.height) {
    return null
  }
  return point
}

function clampedContentPoint(event: PointerEvent): Point | null {
  const point = rawPoint(event)
  const rect = contentRect.value
  if (!point || !rect.width || !rect.height) return null
  return {
    x: Math.min(rect.left + rect.width, Math.max(rect.left, point.x)),
    y: Math.min(rect.top + rect.height, Math.max(rect.top, point.y)),
  }
}

function normalizedRegion(start: Point, end: Point): NormalizedRegion {
  const rect = contentRect.value
  const left = Math.min(start.x, end.x)
  const top = Math.min(start.y, end.y)
  const width = Math.abs(end.x - start.x)
  const height = Math.abs(end.y - start.y)
  return {
    x: Math.min(1, Math.max(0, (left - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (top - rect.top) / rect.height)),
    width: Math.min(1, Math.max(0, width / rect.width)),
    height: Math.min(1, Math.max(0, height / rect.height)),
  }
}

function resetSelection() {
  pointer.value = null
  selectionStart.value = null
  selectionEnd.value = null
  selectedRegion.value = null
  mode.value = 'view'
}

function beginSelection() {
  if (props.disabled || mode.value === 'submitting') return
  resetSelection()
  mode.value = 'selecting'
}

function cancelSelection() {
  resetSelection()
}

function handlePointerMove(event: PointerEvent) {
  if (mode.value === 'selecting' && selectionStart.value) {
    selectionEnd.value = clampedContentPoint(event)
    return
  }
  pointer.value = mode.value === 'view' ? pointInContent(event) : null
}

function handlePointerDown(event: PointerEvent) {
  if (props.disabled || mode.value !== 'selecting') return
  const point = pointInContent(event)
  if (!point) return
  const target = event.currentTarget
  if (target instanceof HTMLElement) target.setPointerCapture(event.pointerId)
  pointer.value = null
  selectionStart.value = point
  selectionEnd.value = point
  selectedRegion.value = null
}

function handlePointerUp(event: PointerEvent) {
  const start = selectionStart.value
  const end = clampedContentPoint(event)
  const target = event.currentTarget
  if (target instanceof HTMLElement && target.hasPointerCapture(event.pointerId)) target.releasePointerCapture(event.pointerId)
  if (!start || !end || mode.value !== 'selecting') return

  selectionStart.value = null
  selectionEnd.value = null
  if (Math.abs(end.x - start.x) < MIN_SELECTION_CSS_PIXELS || Math.abs(end.y - start.y) < MIN_SELECTION_CSS_PIXELS) return

  selectedRegion.value = normalizedRegion(start, end)
  mode.value = 'ready'
}

function handleImageLoad(event: Event) {
  const image = event.target as HTMLImageElement
  naturalSize.value = { width: image.naturalWidth, height: image.naturalHeight }
  updateContentRect()
  emit('image-load', event)
}

function handleImageError(event: Event) {
  naturalSize.value = { width: 0, height: 0 }
  updateContentRect()
  resetSelection()
  emit('image-error', event)
}

function requestScan() {
  if (!canScan.value || !barcodeType.value || !selectedRegion.value) return
  mode.value = 'submitting'
  emit('scan', { barcodeType: barcodeType.value, region: selectedRegion.value })
}

watch(() => props.src, () => {
  naturalSize.value = { width: 0, height: 0 }
  resetSelection()
  nextTick(updateContentRect)
})

watch(() => props.disabled, (disabled) => {
  if (!disabled && mode.value === 'submitting' && selectedRegion.value) mode.value = 'ready'
})

onMounted(() => {
  resizeObserver = new ResizeObserver(updateContentRect)
  if (stage.value) resizeObserver.observe(stage.value)
  updateContentRect()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resetSelection()
})

defineExpose({ resetSelection })
</script>

<template>
  <section class="review-image-inspector" :class="{ 'is-loading': loading, 'is-disabled': disabled }">
    <div class="review-image-inspector__toolbar">
      <el-tooltip content="框选扫码" placement="top">
        <el-button circle :icon="Crop" :disabled="disabled || mode === 'selecting' || mode === 'submitting'" @click="beginSelection" />
      </el-tooltip>
      <el-radio-group v-model="barcodeType" :disabled="disabled || mode === 'submitting'" aria-label="barcode type">
        <el-tooltip content="表计" placement="top"><el-radio-button value="meter"><el-icon><Odometer /></el-icon></el-radio-button></el-tooltip>
        <el-tooltip content="模块" placement="top"><el-radio-button value="module"><el-icon><Grid /></el-icon></el-radio-button></el-tooltip>
        <el-tooltip content="采集器" placement="top"><el-radio-button value="collector"><el-icon><Connection /></el-icon></el-radio-button></el-tooltip>
      </el-radio-group>
      <el-tooltip content="识别选区" placement="top">
        <el-button circle type="primary" :icon="Search" :disabled="!canScan" @click="requestScan" />
      </el-tooltip>
      <el-tooltip content="取消框选" placement="top">
        <el-button circle :icon="Close" :disabled="disabled || mode === 'view' || mode === 'submitting'" @click="cancelSelection" />
      </el-tooltip>
    </div>

    <div
      ref="stage"
      class="review-image-inspector__stage"
      :class="`is-${mode}`"
      @pointermove="handlePointerMove"
      @pointerleave="mode === 'view' && (pointer = null)"
      @pointerdown="handlePointerDown"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerUp"
      @dblclick="emit('open')"
    >
      <img
        v-if="src"
        class="review-image-inspector__image"
        :src="src"
        :alt="alt"
        :draggable="false"
        @load="handleImageLoad"
        @error="handleImageError"
      >
      <div v-if="mode === 'selecting' && draftingSelectionStyle" class="review-image-inspector__selection is-drafting" :style="draftingSelectionStyle" />
      <div v-if="selectionStyle" class="review-image-inspector__selection" :style="selectionStyle" />
      <div v-if="mode === 'view' && pointer" class="review-image-inspector__magnifier" :style="magnifierStyle" />
    </div>
  </section>
</template>

<style scoped>
.review-image-inspector {
  display: grid;
  grid-template-rows: auto minmax(420px, 1fr);
  gap: 8px;
  min-width: 640px;
  height: 100%;
}

.review-image-inspector__toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.review-image-inspector__stage {
  position: relative;
  min-height: 420px;
  overflow: hidden;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color);
  touch-action: none;
}

.review-image-inspector__stage.is-selecting { cursor: crosshair; }

.review-image-inspector__image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
  user-select: none;
}

.review-image-inspector__selection {
  position: absolute;
  box-sizing: border-box;
  min-width: 12px;
  min-height: 12px;
  pointer-events: none;
  border: 2px solid var(--el-color-primary);
  background: color-mix(in srgb, var(--el-color-primary) 15%, transparent);
}

.review-image-inspector__selection.is-drafting { border-style: dashed; }

.review-image-inspector__magnifier {
  position: absolute;
  z-index: 1;
  width: 160px;
  height: 160px;
  pointer-events: none;
  border: 2px solid var(--el-color-primary);
  border-radius: 50%;
  background-repeat: no-repeat;
  box-shadow: 0 2px 12px rgb(0 0 0 / 24%);
}

.review-image-inspector.is-loading .review-image-inspector__stage::after {
  position: absolute;
  inset: 0;
  content: '';
  background: rgb(255 255 255 / 38%);
}

.review-image-inspector.is-disabled .review-image-inspector__stage { cursor: not-allowed; }
</style>
