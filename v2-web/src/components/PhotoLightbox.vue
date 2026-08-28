<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

defineProps<{
  src: string
  alt: string
}>()

const emit = defineEmits<{
  (event: 'close'): void
}>()

function closeOnEscape(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', closeOnEscape))
onBeforeUnmount(() => window.removeEventListener('keydown', closeOnEscape))
</script>

<template>
  <div
    v-if="src"
    class="photo-lightbox"
    data-testid="photo-lightbox"
    role="dialog"
    aria-modal="true"
    :aria-label="`${alt}大图`"
    @click.self="emit('close')"
  >
    <button type="button" data-testid="close-photo-lightbox" aria-label="关闭大图" @click="emit('close')">关闭</button>
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
