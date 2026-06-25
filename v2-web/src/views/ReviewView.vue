<script setup lang="ts">
import { Check, Close, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import StatusTag from '@/components/StatusTag.vue'
import type { MaterialGroup, ReviewPhoto, TaskStatus } from '@/api/types'
import { useWorkspaceStore } from '@/stores/workspace'

const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const activePhotoId = ref('')
const photoCategory = ref('表前')
const reviewNote = ref('')

const activePhoto = computed<ReviewPhoto | undefined>(() => {
  return workspace.activePhotos.find((photo) => photo.id === activePhotoId.value) || workspace.activePhotos[0]
})

watch(
  () => route.params.groupId,
  async (groupId) => {
    await workspace.loadReviewGroup(String(groupId || 'g-001'))
    activePhotoId.value = workspace.activePhotos[0]?.id || ''
  },
  { immediate: true },
)

onMounted(() => {
  if (!workspace.groups.length) {
    void workspace.bootstrap()
  }
})

async function save(status: TaskStatus) {
  await workspace.saveReview(status)
  ElMessage.success('审阅状态已保存到占位接口')
}

function openGroup(group: MaterialGroup) {
  void router.push(`/review/${group.id}`)
}
</script>

<template>
  <div class="review-grid" v-loading="workspace.loading">
    <section class="panel review-column">
      <div class="panel-header">
        <h3>资料组队列</h3>
      </div>
      <div class="panel-body review-list">
        <div
          v-for="group in workspace.groups"
          :key="group.id"
          class="queue-item"
          :class="{ active: group.id === workspace.activeGroup?.id }"
          @click="openGroup(group)"
        >
          <strong>{{ group.meterNo }}</strong>
          <p class="muted">{{ group.address }}</p>
          <StatusTag :status="group.status" />
        </div>
      </div>
    </section>

    <section class="image-stage">
      <img v-if="activePhoto" :src="activePhoto.url" :alt="activePhoto.name" />
      <ElEmpty v-else description="暂无照片" />
    </section>

    <section class="panel review-column">
      <div class="panel-header">
        <h3>审阅信息</h3>
        <StatusTag v-if="workspace.activeGroup" :status="workspace.activeGroup.status" />
      </div>
      <div class="panel-body page-stack">
        <ElDescriptions v-if="workspace.activeGroup" :column="1" border size="small">
          <ElDescriptionsItem label="安装地址">{{ workspace.activeGroup.address }}</ElDescriptionsItem>
          <ElDescriptionsItem label="原始表号">{{ workspace.activeGroup.meterNo }}</ElDescriptionsItem>
          <ElDescriptionsItem label="终端">{{ workspace.activeGroup.terminal }}</ElDescriptionsItem>
          <ElDescriptionsItem label="照片数">{{ workspace.activeGroup.photoCount }}</ElDescriptionsItem>
        </ElDescriptions>

        <div>
          <h3>照片分类</h3>
          <ElSegmented
            v-model="activePhotoId"
            :options="workspace.activePhotos.map((photo) => ({ label: photo.name, value: photo.id }))"
            block
          />
        </div>

        <ElRadioGroup v-model="photoCategory">
          <ElRadioButton label="表前" />
          <ElRadioButton label="表后" />
          <ElRadioButton label="铭牌" />
          <ElRadioButton label="其他" />
        </ElRadioGroup>

        <ElInput v-model="reviewNote" type="textarea" :rows="4" placeholder="异常说明或补充备注" />

        <div class="toolbar">
          <ElButton type="success" :icon="Check" @click="save('complete')">完成</ElButton>
          <ElButton type="warning" :icon="Warning" @click="save('incomplete')">不完整</ElButton>
          <ElButton type="danger" :icon="Close" @click="save('exception')">异常</ElButton>
        </div>
      </div>
    </section>
  </div>
</template>
