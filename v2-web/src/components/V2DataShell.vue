<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string;
    meta?: string;
  }>(),
  {
    title: "",
    meta: "",
  },
);
</script>

<template>
  <section class="v2-data-shell">
    <div v-if="title || meta || $slots.actions" class="v2-data-shell__header">
      <div>
        <h2 v-if="title" class="v2-data-shell__title">{{ title }}</h2>
        <div v-if="meta" class="v2-data-shell__meta">{{ meta }}</div>
      </div>
      <div v-if="$slots.actions" class="v2-toolbar__group">
        <slot name="actions" />
      </div>
    </div>
    <div class="v2-data-shell__body">
      <slot />
    </div>
  </section>
</template>
