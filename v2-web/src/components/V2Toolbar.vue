<template>
  <header class="v2-toolbar">
    <div class="v2-toolbar__group">
      <div v-if="$slots.title" class="v2-toolbar__title v2-truncate">
        <slot name="title" />
      </div>
      <slot name="left" />
    </div>
    <div class="v2-toolbar__group">
      <slot />
    </div>
    <div v-if="$slots.right" class="v2-toolbar__group">
      <slot name="right" />
    </div>
  </header>
</template>
