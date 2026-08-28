<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{
  src: string
  alt: string
}>()

const emit = defineEmits<{
  (event: 'close'): void
}>()

const dialog = ref<HTMLElement | null>(null)
const closeButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
let listening = false

function focusableElements() {
  if (!dialog.value) return []
  return Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => element.getAttribute('aria-hidden') !== 'true')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  if (event.key !== 'Tab') return

  const focusable = focusableElements()
  if (focusable.length === 0) {
    event.preventDefault()
    dialog.value?.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && (active === first || !dialog.value?.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !dialog.value?.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}

function activate() {
  if (listening) return
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  window.addEventListener('keydown', handleKeydown)
  listening = true
  void nextTick(() => {
    if (props.src) closeButton.value?.focus()
  })
}

function deactivate() {
  if (listening) {
    window.removeEventListener('keydown', handleKeydown)
    listening = false
  }
  if (previousFocus?.isConnected) previousFocus.focus()
  previousFocus = null
}

watch(
  () => props.src,
  (src, previousSrc) => {
    if (src && !previousSrc) activate()
    else if (!src && previousSrc) deactivate()
  },
  { immediate: true },
)
onBeforeUnmount(deactivate)
</script>

<template>
  <div
    v-if="src"
    ref="dialog"
    class="photo-lightbox"
    data-testid="photo-lightbox"
    role="dialog"
    aria-modal="true"
    tabindex="-1"
    :aria-label="`${alt}大图`"
    @click.self="emit('close')"
  >
    <button ref="closeButton" type="button" data-testid="close-photo-lightbox" aria-label="关闭大图" @click="emit('close')">关闭</button>
    <figure>
      <img data-testid="photo-lightbox-image" :src="src" :alt="alt" />
      <figcaption>{{ alt }}</figcaption>
    </figure>
  </div>
</template>

<style scoped>
.photo-lightbox {
  position: fixed;
  z-index: 4000;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 56px 20px 24px;
  background: rgb(8 15 28 / 92%);
}
.photo-lightbox > button {
  position: absolute;
  top: 16px;
  right: 20px;
  min-width: 72px;
  min-height: 38px;
  border: 1px solid rgb(255 255 255 / 55%);
  border-radius: 6px;
  background: rgb(255 255 255 / 12%);
  color: #fff;
  cursor: pointer;
  font: inherit;
}
.photo-lightbox figure { display: grid; gap: 10px; max-width: 96vw; max-height: calc(100vh - 80px); margin: 0; }
.photo-lightbox img { display: block; max-width: 96vw; max-height: calc(100vh - 116px); object-fit: contain; }
.photo-lightbox figcaption { overflow: hidden; color: #fff; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
</style>
