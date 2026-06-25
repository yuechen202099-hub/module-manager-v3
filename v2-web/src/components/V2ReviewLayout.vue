<template>
  <section class="v2-review-layout">
    <aside class="v2-review-pane v2-review-layout__queue">
      <div v-if="$slots.queueHeader" class="v2-review-pane__header">
        <slot name="queueHeader" />
      </div>
      <div class="v2-review-pane__body v2-scrollbar">
        <slot name="queue" />
      </div>
    </aside>

    <main class="v2-review-pane v2-review-layout__stage">
      <div v-if="$slots.stageHeader" class="v2-review-pane__header">
        <slot name="stageHeader" />
      </div>
      <div class="v2-review-pane__body">
        <div class="v2-image-stage">
          <slot name="stage" />
        </div>
      </div>
    </main>

    <aside class="v2-review-pane v2-review-layout__inspector">
      <div v-if="$slots.inspectorHeader" class="v2-review-pane__header">
        <slot name="inspectorHeader" />
      </div>
      <div class="v2-review-pane__body v2-scrollbar">
        <div class="v2-inspector-stack">
          <slot name="inspector" />
        </div>
      </div>
    </aside>
  </section>
</template>
