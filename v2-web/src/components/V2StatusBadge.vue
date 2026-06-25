<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    status?: "pending" | "reviewing" | "in-review" | "complete" | "completed" | "exception" | "error" | "incomplete" | "warning" | "locked";
    label?: string;
  }>(),
  {
    status: "pending",
    label: "",
  },
);

const fallbackLabels: Record<string, string> = {
  pending: "\u5f85\u5904\u7406",
  reviewing: "\u5ba1\u9605\u4e2d",
  "in-review": "\u5ba1\u9605\u4e2d",
  complete: "\u5b8c\u6210",
  completed: "\u5b8c\u6210",
  exception: "\u5f02\u5e38",
  error: "\u5f02\u5e38",
  incomplete: "\u4e0d\u5b8c\u6574",
  warning: "\u4e0d\u5b8c\u6574",
  locked: "\u9501\u5b9a",
};
</script>

<template>
  <span class="v2-status" :class="`v2-status--${props.status}`">
    <slot>{{ props.label || fallbackLabels[props.status] }}</slot>
  </span>
</template>
