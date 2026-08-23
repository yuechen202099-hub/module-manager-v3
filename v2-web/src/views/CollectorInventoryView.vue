<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

import {
  createCollectorTransferRun,
  fetchCollectorTransferRuns,
  importCollectorInventory,
  scanPhysicalCollector,
  uploadPhysicalCollectorPhoto,
} from '@/api/services'
import type {
  CollectorInventoryDecision,
  CollectorInventoryImportResult,
  CollectorTransferRun,
} from '@/api/types'
import { inventoryResultPresentation } from '@/features/collectorTransfer/state'
import { useWorkspaceStore } from '@/stores/workspace'

type MobileView = 'scan' | 'records' | 'import'
type CameraStatus = 'idle' | 'starting' | 'scanning' | 'unsupported' | 'denied'
type UploadStatus = 'idle' | 'uploading' | 'success' | 'error'
type DetectedBarcode = { rawValue?: string }
type NativeBarcodeDetector = { detect: (source: HTMLVideoElement) => Promise<DetectedBarcode[]> }
type NativeBarcodeDetectorConstructor = new (options?: { formats?: string[] }) => NativeBarcodeDetector

const workspace = useWorkspaceStore()
const runs = ref<CollectorTransferRun[]>([])
const selectedRunId = ref('')
const mobileView = ref<MobileView>('scan')
const collectorNo = ref('')
const result = ref<CollectorInventoryDecision | null>(null)
const recent = ref<CollectorInventoryDecision[]>([])
const loading = ref(false)
const cameraActive = ref(false)
const cameraStatus = ref<CameraStatus>('idle')
const scanFeedback = ref('')
const video = ref<HTMLVideoElement | null>(null)
const photoInput = ref<HTMLInputElement | null>(null)
const workbookFile = ref<File | null>(null)
const inventoryPhotos = ref<File[]>([])
const importResult = ref<CollectorInventoryImportResult | null>(null)
const setupOpen = ref(false)
const setupProjectId = ref('')
const setupName = ref(`采集器盘点 ${new Date().toLocaleDateString('zh-CN')}`)
const localPhotoUrl = ref('')
const uploadStatus = ref<UploadStatus>('idle')
const uploadMessage = ref('')
let mediaStream: MediaStream | null = null
let barcodeDetector: NativeBarcodeDetector | null = null
let animationFrameId = 0
let cameraSession = 0
let scanInFlight = false
let lastDecodedValue = ''
let lastDecodedAt = 0

const selectedRun = computed(() => runs.value.find((item) => item.id === selectedRunId.value) || null)
const presentation = computed(() => result.value
  ? inventoryResultPresentation({
      decision: result.value.decision,
      requiresPhoto: result.value.requires_photo,
      addToPool: result.value.add_to_pool,
    })
  : null)
const photoUrl = computed(() => {
  if (localPhotoUrl.value) return localPhotoUrl.value
  const photo = result.value?.photo
  return photo?.preview_url || photo?.image_url || photo?.thumbnail_url || ''
})
const poolSemantics = computed(() => {
  if (!result.value) return ''
  if (result.value.decision === 'assignment_reuse') return '不重复入池'
  if (result.value.add_to_pool) return result.value.requires_photo ? '补图后加入替换池' : '已加入替换池'
  if (result.value.decision === 'direct_needs_photo') return '直接匹配，不入池'
  return '不加入替换池'
})
const primaryActionLabel = computed(() => uploadStatus.value === 'error' ? '重新上传' : presentation.value?.primaryAction || '')
const cameraStatusMessage = computed(() => {
  if (cameraStatus.value === 'starting') return '正在请求摄像头权限…'
  if (cameraStatus.value === 'scanning') return scanFeedback.value || '连续扫码已开启'
  if (cameraStatus.value === 'unsupported') return '此浏览器不支持摄像头扫码，请使用手工输入或外接扫码枪'
  if (cameraStatus.value === 'denied') return '摄像头不可用，请使用手工输入或外接扫码枪'
  return '手工输入与外接扫码枪始终可用'
})
const runProgress = computed(() => {
  const run = selectedRun.value
  if (!run) return '尚未选择批次'
  return `${run.assignment_count || 0} 已分配 / ${run.collector_requirement_count || 0} 个需求`
})

onMounted(async () => {
  await Promise.all([
    loadRuns(),
    workspace.projects.length ? Promise.resolve() : workspace.loadProjects(),
  ])
  setupProjectId.value = workspace.activeProject?.id || workspace.projects[0]?.id || ''
})

onUnmounted(() => {
  stopCamera()
  releaseLocalPhotoUrl()
})

async function loadRuns() {
  try {
    runs.value = await fetchCollectorTransferRuns()
    if (!selectedRunId.value || !runs.value.some((item) => item.id === selectedRunId.value)) {
      selectedRunId.value = runs.value[0]?.id || ''
    }
    if (!runs.value.length) setupOpen.value = true
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '盘点批次加载失败')
  }
}

async function createRun() {
  if (!setupProjectId.value) {
    ElMessage.warning('请先选择项目')
    return
  }
  loading.value = true
  try {
    const created = await createCollectorTransferRun(setupProjectId.value, setupName.value.trim() || '采集器盘点')
    await loadRuns()
    selectedRunId.value = created.id
    setupOpen.value = false
    ElMessage.success('已根据现有数据生成终端和采集器需求')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '新建盘点批次失败')
  } finally {
    loading.value = false
  }
}

async function submitScan(rawValue = collectorNo.value) {
  const value = rawValue.trim()
  if (!selectedRunId.value) {
    ElMessage.warning('请先选择盘点批次')
    setupOpen.value = true
    return
  }
  if (!value) {
    ElMessage.warning('请输入或扫描采集器号')
    return
  }
  if (scanInFlight) {
    scanFeedback.value = value === lastDecodedValue
      ? '已识别该采集器，正在查询，请勿重复扫码'
      : '正在处理上一条扫码，请稍候'
    return
  }
  scanInFlight = true
  loading.value = true
  try {
    const decision = await scanPhysicalCollector(selectedRunId.value, value)
    releaseLocalPhotoUrl()
    uploadStatus.value = 'idle'
    uploadMessage.value = ''
    result.value = decision
    collectorNo.value = decision.collector_no
    recent.value = [decision, ...recent.value.filter((item) => item.collector_id !== decision.collector_id)].slice(0, 20)
    stopCamera()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '采集器扫码判断失败')
  } finally {
    scanInFlight = false
    loading.value = false
  }
}

async function startCamera() {
  if (cameraActive.value) return
  if (!selectedRunId.value) {
    setupOpen.value = true
    return
  }
  result.value = null
  releaseLocalPhotoUrl()
  uploadStatus.value = 'idle'
  uploadMessage.value = ''
  scanFeedback.value = ''
  const Detector = (globalThis as typeof globalThis & { BarcodeDetector?: NativeBarcodeDetectorConstructor }).BarcodeDetector
  if (!Detector || !navigator.mediaDevices?.getUserMedia) {
    cameraStatus.value = 'unsupported'
    return
  }
  const session = ++cameraSession
  cameraStatus.value = 'starting'
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' } },
    })
    if (session !== cameraSession) {
      for (const track of stream.getTracks()) track.stop()
      return
    }
    mediaStream = stream
    cameraActive.value = true
    cameraStatus.value = 'scanning'
    await nextTick()
    if (!video.value) throw new Error('摄像头画面尚未就绪')
    video.value.srcObject = stream
    barcodeDetector = new Detector({ formats: ['code_128', 'code_39', 'ean_13'] })
    void detectNextFrame(session)
  } catch (error) {
    stopCamera()
    cameraStatus.value = 'denied'
    ElMessage.warning(error instanceof Error ? error.message : '无法打开摄像头，请使用手工输入')
  }
}

function stopCamera() {
  cameraSession += 1
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
  animationFrameId = 0
  barcodeDetector = null
  cameraActive.value = false
  if (mediaStream) for (const track of mediaStream.getTracks()) track.stop()
  mediaStream = null
  if (video.value) video.value.srcObject = null
}

async function detectNextFrame(session: number) {
  if (!cameraActive.value || session !== cameraSession || !barcodeDetector || !video.value) return
  try {
    const detected = await barcodeDetector.detect(video.value)
    const value = detected[0]?.rawValue?.trim() || ''
    const now = Date.now()
    if (value) {
      if (scanInFlight && value === lastDecodedValue) {
        scanFeedback.value = '已识别该采集器，正在查询，请勿重复扫码'
      } else if (value !== lastDecodedValue || now - lastDecodedAt >= 1800) {
        lastDecodedValue = value
        lastDecodedAt = now
        collectorNo.value = value
        void submitScan(value)
      }
    }
  } catch {
    scanFeedback.value = '本帧未识别，请继续对准条形码'
  } finally {
    if (cameraActive.value && session === cameraSession) {
      animationFrameId = requestAnimationFrame(() => void detectNextFrame(session))
    }
  }
}

function resetForNextScan() {
  result.value = null
  collectorNo.value = ''
  mobileView.value = 'scan'
  void startCamera()
}

function requestPhoto() {
  photoInput.value?.click()
}

async function uploadPhoto(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !result.value || !selectedRunId.value) return
  releaseLocalPhotoUrl()
  localPhotoUrl.value = URL.createObjectURL(file)
  uploadStatus.value = 'uploading'
  uploadMessage.value = '照片上传中…'
  loading.value = true
  try {
    const uploaded = await uploadPhysicalCollectorPhoto(selectedRunId.value, result.value.collector_id, file)
    result.value = {
      ...result.value,
      requires_photo: false,
      pool_status: uploaded.pool_status as CollectorInventoryDecision['pool_status'],
      photo: (uploaded.photo || result.value.photo) as CollectorInventoryDecision['photo'],
    }
    recent.value = [result.value, ...recent.value.filter((item) => item.collector_id !== result.value?.collector_id)]
    uploadStatus.value = 'success'
    uploadMessage.value = result.value.add_to_pool
      ? '上传成功，照片已加入替换池'
      : '上传成功，照片已直接匹配且不入池'
    ElMessage.success(result.value.add_to_pool ? '照片已保存，采集器已进入替换池' : '照片已保存并完成同号直配')
  } catch (error) {
    uploadStatus.value = 'error'
    uploadMessage.value = `上传失败：${error instanceof Error ? error.message : '请重试'}`
    ElMessage.error(error instanceof Error ? error.message : '采集器照片上传失败')
  } finally {
    loading.value = false
    ;(event.target as HTMLInputElement).value = ''
  }
}

function releaseLocalPhotoUrl() {
  if (!localPhotoUrl.value) return
  URL.revokeObjectURL(localPhotoUrl.value)
  localPhotoUrl.value = ''
}

function selectWorkbook(event: Event) {
  workbookFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

function selectInventoryPhotos(event: Event) {
  inventoryPhotos.value = Array.from((event.target as HTMLInputElement).files || [])
}

async function submitImport() {
  if (!selectedRunId.value) {
    ElMessage.warning('请先选择盘点批次')
    return
  }
  if (!workbookFile.value && !inventoryPhotos.value.length) {
    ElMessage.warning('请选择 Excel 或按采集器号命名的照片')
    return
  }
  loading.value = true
  try {
    importResult.value = await importCollectorInventory(
      selectedRunId.value,
      workbookFile.value,
      inventoryPhotos.value,
    )
    ElMessage.success(`批量盘点完成，共处理 ${importResult.value.total} 条`)
    await loadRuns()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '批量盘点失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="inventory-page">
    <section class="phone-surface" :aria-busy="loading">
      <header class="inventory-appbar">
        <div>
          <strong>采集器盘点</strong>
          <small>手机摄像头扫码</small>
        </div>
        <button class="round-button" type="button" aria-label="选择盘点批次" @click="setupOpen = true">•••</button>
      </header>

      <div class="stage-banner">仅做盘点与补拍 · 不录入甲方平台</div>
      <div class="batch-row">
        <label>
          <span>当前批次</span>
          <select v-model="selectedRunId" aria-label="当前盘点批次">
            <option value="">请选择</option>
            <option v-for="run in runs" :key="run.id" :value="run.id">{{ run.name }}</option>
          </select>
        </label>
        <strong>{{ runProgress }}</strong>
      </div>

      <main class="inventory-body">
        <section v-if="mobileView === 'scan'" class="scan-view">
          <template v-if="!result">
            <div class="camera-stage">
              <video v-show="cameraActive" ref="video" autoplay muted playsinline />
              <div v-if="!cameraActive" class="camera-empty">
                <span class="camera-glyph" aria-hidden="true">⌗</span>
                <strong>连续扫描实物条码</strong>
                <small>摄像头只读取采集器号，不录入甲方平台</small>
                <button class="primary-button" data-testid="start-camera" type="button" @click="startCamera">打开摄像头扫码</button>
                <span class="camera-status" data-testid="camera-status" aria-live="polite">{{ cameraStatusMessage }}</span>
              </div>
              <div v-if="cameraActive" class="scan-frame"><span /></div>
              <p v-if="cameraActive" class="scan-hint" data-testid="scan-feedback" aria-live="polite">{{ scanFeedback || '对准条形码，识别后自动判断是否需要拍照' }}</p>
            </div>

            <form class="manual-entry" @submit.prevent="submitScan()">
              <label for="collector-number">摄像头无法识别时，可手工输入或使用扫码枪</label>
              <div>
                <input id="collector-number" v-model="collectorNo" inputmode="text" autocomplete="off" placeholder="扫描或输入采集器号" />
                <button class="primary-button" type="submit" :disabled="loading">查询</button>
              </div>
            </form>
          </template>

          <section v-else class="result-view" :class="`tone-${presentation?.tone}`">
            <div class="result-heading">
              <span class="result-icon">{{ presentation?.tone === 'success' ? '✓' : '!' }}</span>
              <h1 data-testid="decision-title">{{ presentation?.title }}</h1>
              <p>{{ presentation?.description }}</p>
            </div>

            <div class="collector-card">
              <div class="collector-preview">
                <img v-if="photoUrl" :src="photoUrl" data-testid="photo-preview" alt="已登记的采集器照片" />
                <div v-else class="device-placeholder"><span>{{ result.collector_no }}</span></div>
              </div>
              <dl>
                <div><dt>采集器号</dt><dd>{{ result.collector_no }}</dd></div>
                <div><dt>登记结果</dt><dd>{{ result.add_to_pool ? '替换池候选' : '同号直接匹配' }}</dd></div>
                <div><dt>替换池</dt><dd data-testid="pool-semantics">{{ poolSemantics }}</dd></div>
              </dl>
            </div>

            <p class="boundary-note">本页只确认盘点结果。这里不会跳转甲方平台，也不会录入甲方平台资料。</p>
            <p v-if="uploadStatus !== 'idle'" class="upload-status" :class="`status-${uploadStatus}`" data-testid="upload-status" aria-live="polite">{{ uploadMessage }}</p>
            <div class="result-actions">
              <button v-if="result.requires_photo" class="primary-button wide" data-testid="decision-primary-action" type="button" :disabled="uploadStatus === 'uploading'" @click="requestPhoto">{{ primaryActionLabel }}</button>
              <button v-else class="primary-button wide" data-testid="decision-primary-action" type="button" @click="resetForNextScan">{{ presentation?.primaryAction }}</button>
              <button class="secondary-button wide" type="button" @click="mobileView = 'records'">查看盘点记录</button>
            </div>
          </section>
        </section>

        <section v-else-if="mobileView === 'records'" class="records-view">
          <header><h1>本机盘点记录</h1><p>显示本次打开页面后的扫码结果。</p></header>
          <div v-if="recent.length" class="record-list">
            <article v-for="(item, index) in recent" :key="`${item.collector_id}-${index}`">
              <span class="record-index">{{ recent.length - index }}</span>
              <div><strong>{{ item.collector_no }}</strong><small>{{ inventoryResultPresentation({ decision: item.decision, requiresPhoto: item.requires_photo, addToPool: item.add_to_pool }).title }}</small></div>
              <i :class="item.add_to_pool ? 'pool' : item.requires_photo ? 'photo' : 'direct'" />
            </article>
          </div>
          <div v-else class="empty-state">还没有扫码记录</div>
        </section>

        <section v-else class="import-view">
          <header><h1>Excel 与照片初始化</h1><p>照片文件名使用采集器号；导入仍执行与手机扫码相同的判定规则。</p></header>
          <label class="upload-field"><span>采集器 Excel（可选）</span><input type="file" accept=".xlsx" @change="selectWorkbook" /><small>{{ workbookFile?.name || '支持“采集器 / 采集器号 / 扫码内容”列' }}</small></label>
          <label class="upload-field"><span>按条码命名的照片（可多选）</span><input type="file" accept="image/*" multiple @change="selectInventoryPhotos" /><small>已选择 {{ inventoryPhotos.length }} 张</small></label>
          <button class="primary-button wide" type="button" :disabled="loading" @click="submitImport">开始批量盘点</button>
          <div v-if="importResult" class="import-summary">
            <strong>处理完成 · {{ importResult.total }} 条</strong>
            <div><span>新增 {{ importResult.inserted }}</span><span>复用 {{ importResult.reused }}</span><span>待补拍 {{ importResult.needs_photo }}</span><span>无效 {{ importResult.invalid }}</span></div>
          </div>
        </section>
      </main>

      <nav class="bottom-nav" aria-label="采集器盘点功能">
        <button :class="{ active: mobileView === 'scan' }" type="button" @click="mobileView = 'scan'"><span>⌗</span>扫码</button>
        <button :class="{ active: mobileView === 'records' }" type="button" @click="mobileView = 'records'"><span>▤</span>盘点记录</button>
        <button :class="{ active: mobileView === 'import' }" type="button" @click="mobileView = 'import'"><span>⇧</span>批量导入</button>
      </nav>
    </section>

    <input ref="photoInput" class="visually-hidden" data-testid="photo-input" type="file" accept="image/*" capture="environment" :disabled="!result?.requires_photo" @change="uploadPhoto" />

    <div v-if="setupOpen" class="setup-backdrop" @click.self="setupOpen = false">
      <form class="setup-dialog" @submit.prevent="createRun">
        <header><h2>选择或新建盘点批次</h2><button type="button" aria-label="关闭" @click="setupOpen = false">×</button></header>
        <label><span>已有批次</span><select v-model="selectedRunId" @change="setupOpen = false"><option value="">无</option><option v-for="run in runs" :key="run.id" :value="run.id">{{ run.name }}</option></select></label>
        <div class="setup-divider">根据现有数据新建</div>
        <label><span>项目</span><select v-model="setupProjectId"><option v-for="project in workspace.projects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label>
        <label><span>批次名称</span><input v-model="setupName" /></label>
        <button class="primary-button wide" type="submit" :disabled="loading">生成终端与采集器需求</button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.inventory-page {
  --ink: #17211b;
  --muted: #68756d;
  --line: #dbe4dc;
  --paper: #eef2ee;
  --green: #176b43;
  --green-soft: #e8f5ed;
  --amber: #9b610d;
  --amber-soft: #fff5dc;
  --red: #9f3630;
  --red-soft: #fff0ee;
  --blue: #275d7b;
  --blue-soft: #e9f3f8;
  min-height: calc(100dvh - 36px);
  padding: 18px;
  background: var(--paper);
  color: var(--ink);
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
}

button, input, select { font: inherit; }

.phone-surface {
  position: relative;
  display: flex;
  width: min(100%, 460px);
  min-height: min(820px, calc(100dvh - 36px));
  margin: 0 auto;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 28px;
  background: #f7f9f6;
  box-shadow: 0 22px 42px rgba(31, 47, 37, 0.16);
}

.inventory-appbar {
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}

.inventory-appbar strong { display: block; font-size: 17px; }
.inventory-appbar small { display: block; margin-top: 2px; color: var(--muted); font-size: 11px; }

.round-button {
  width: 38px;
  height: 38px;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: #fff;
  color: var(--ink);
  font-weight: 800;
}

.stage-banner {
  padding: 9px 13px;
  border-bottom: 1px solid #c6dae6;
  background: var(--blue-soft);
  color: var(--blue);
  font-size: 11px;
  font-weight: 800;
  text-align: center;
}

.batch-row {
  display: grid;
  gap: 6px;
  padding: 10px 15px;
  border-bottom: 1px solid var(--line);
  background: #fff;
}

.batch-row label { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 9px; color: var(--muted); font-size: 11px; }
.batch-row select { min-width: 0; border: 0; background: transparent; color: var(--ink); font-weight: 800; }
.batch-row strong { color: var(--muted); font-size: 10px; font-weight: 600; }

.inventory-body { flex: 1; padding-bottom: 72px; }
.scan-view { min-height: 100%; }

.camera-stage {
  position: relative;
  display: grid;
  min-height: 390px;
  place-items: center;
  overflow: hidden;
  background: #17221c;
  color: #fff;
}

.camera-stage::before {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(90deg, rgba(255,255,255,.07) 1px, transparent 1px), linear-gradient(rgba(255,255,255,.07) 1px, transparent 1px);
  background-size: 32px 32px;
  content: "";
  opacity: .2;
}

.camera-stage video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }

.camera-empty { position: relative; z-index: 1; display: grid; max-width: 270px; justify-items: center; gap: 10px; text-align: center; }
.camera-empty strong { font-size: 18px; }
.camera-empty small { color: #b8c4bc; line-height: 1.6; }
.camera-status { max-width: 290px; color: #b8c4bc; font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }
.camera-glyph { display: grid; width: 68px; height: 68px; place-items: center; border: 1px solid #607168; border-radius: 18px; color: #6ee3a1; font-size: 34px; }

.scan-frame { position: absolute; z-index: 2; width: min(78%, 320px); height: 112px; border: 2px solid #6ee3a1; border-radius: 12px; box-shadow: 0 0 0 999px rgba(0,0,0,.2); }
.scan-frame span { position: absolute; top: 50%; right: 12px; left: 12px; height: 2px; background: #6ee3a1; box-shadow: 0 0 10px #6ee3a1; animation: scan-line 1.8s ease-in-out infinite; }
.scan-hint { position: absolute; z-index: 3; bottom: 22px; margin: 0; padding: 8px 12px; border-radius: 22px; background: rgba(0,0,0,.55); font-size: 11px; }

@keyframes scan-line { 0%, 100% { transform: translateY(-34px); } 50% { transform: translateY(34px); } }

.manual-entry { margin: 14px; padding: 13px; border: 1px solid var(--line); border-radius: 13px; background: #fff; }
.manual-entry label { display: block; margin-bottom: 8px; color: var(--muted); font-size: 11px; }
.manual-entry > div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
.manual-entry input, .setup-dialog input, .setup-dialog select { min-width: 0; padding: 11px; border: 1px solid var(--line); border-radius: 9px; background: #fafbfa; color: var(--ink); }

.primary-button, .secondary-button { min-height: 42px; border-radius: 9px; padding: 10px 14px; font-weight: 800; }
.primary-button { border: 0; background: var(--green); color: #fff; }
.secondary-button { border: 1px solid var(--line); background: #fff; color: var(--ink); }
.primary-button:disabled { opacity: .55; }
.wide { width: 100%; }

.result-view { padding: 18px 15px 24px; }
.result-heading { padding: 8px 0 15px; text-align: center; }
.result-heading h1 { margin: 0 0 6px; font-size: 20px; }
.result-heading p { margin: 0 auto; max-width: 320px; color: var(--muted); font-size: 12px; line-height: 1.65; }
.result-icon { display: grid; width: 58px; height: 58px; margin: 0 auto 11px; place-items: center; border-radius: 50%; background: var(--green-soft); color: var(--green); font-size: 29px; font-weight: 900; }
.tone-warning .result-icon { background: var(--amber-soft); color: var(--amber); }
.tone-danger .result-icon { background: var(--red-soft); color: var(--red); }

.collector-card { overflow: hidden; border: 1px solid #b8dcc7; border-radius: 14px; background: var(--green-soft); }
.tone-warning .collector-card { border-color: #ead099; background: var(--amber-soft); }
.tone-danger .collector-card { border-color: #ecc1bd; background: var(--red-soft); }
.collector-preview { display: grid; min-height: 245px; place-items: center; overflow: hidden; border-bottom: 1px solid rgba(0,0,0,.08); background: #dce2dd; }
.collector-preview img { width: 100%; height: 245px; object-fit: contain; background: #151d18; }
.device-placeholder { position: relative; display: grid; width: 165px; height: 190px; place-items: end center; padding: 22px 12px; border: 6px solid #b8c0ba; border-radius: 12px; background: #edf0ed; box-shadow: 0 11px 20px rgba(20,30,22,.12); }
.device-placeholder::before { position: absolute; top: 42px; color: #758078; content: "采集器照片待补拍"; font-size: 11px; }
.device-placeholder span { width: 100%; padding: 14px 5px; background: #fff; color: var(--ink); font-size: 10px; font-weight: 800; text-align: center; overflow-wrap: anywhere; }
.collector-card dl { margin: 0; padding: 12px; }
.collector-card dl div { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 8px; padding: 5px 0; font-size: 12px; }
.collector-card dt { color: var(--muted); }
.collector-card dd { margin: 0; font-weight: 800; text-align: right; overflow-wrap: anywhere; }

.boundary-note { margin: 12px 0; padding: 11px 12px; border: 1px solid rgba(0,0,0,.07); border-radius: 9px; background: #fff; color: var(--muted); font-size: 11px; line-height: 1.6; }
.upload-status { margin: 0 0 12px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 9px; background: #fff; color: var(--muted); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.upload-status.status-success { border-color: #b8dcc7; background: var(--green-soft); color: var(--green); }
.upload-status.status-error { border-color: #e1b8b4; background: var(--red-soft); color: var(--red); }
.result-actions { display: grid; gap: 9px; }

.records-view, .import-view { padding: 18px 14px 24px; }
.records-view header h1, .import-view header h1 { margin: 0 0 5px; font-size: 20px; }
.records-view header p, .import-view header p { margin: 0 0 16px; color: var(--muted); font-size: 12px; line-height: 1.6; }
.record-list { display: grid; gap: 8px; }
.record-list article { display: grid; grid-template-columns: 36px minmax(0, 1fr) 10px; align-items: center; gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 11px; background: #fff; }
.record-index { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 9px; background: #edf1ed; font-size: 11px; font-weight: 800; }
.record-list strong, .record-list small { display: block; }
.record-list strong { font-size: 13px; overflow-wrap: anywhere; }
.record-list small { margin-top: 3px; color: var(--muted); font-size: 10px; }
.record-list i { width: 9px; height: 9px; border-radius: 50%; background: var(--green); }
.record-list i.photo { background: #d48817; }
.record-list i.pool { background: #c14d44; }
.empty-state { display: grid; min-height: 280px; place-items: center; color: var(--muted); }

.import-view { display: grid; gap: 12px; }
.upload-field { display: grid; gap: 7px; padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: #fff; }
.upload-field span { font-size: 13px; font-weight: 800; }
.upload-field small { color: var(--muted); font-size: 11px; }
.upload-field input { max-width: 100%; }
.import-summary { display: grid; gap: 10px; padding: 14px; border: 1px solid #b8dcc7; border-radius: 12px; background: var(--green-soft); }
.import-summary > div { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; color: var(--muted); font-size: 11px; }

.bottom-nav { position: absolute; right: 0; bottom: 0; left: 0; z-index: 8; display: grid; height: 70px; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--line); background: rgba(255,255,255,.97); backdrop-filter: blur(16px); }
.bottom-nav button { display: grid; place-items: center; align-content: center; gap: 3px; border: 0; background: transparent; color: var(--muted); font-size: 10px; }
.bottom-nav button span { font-size: 19px; }
.bottom-nav button.active { color: var(--green); font-weight: 800; }

.setup-backdrop { position: fixed; inset: 0; z-index: 90; display: grid; place-items: end center; padding: 12px; background: rgba(16,25,20,.52); }
.setup-dialog { display: grid; width: min(100%, 460px); gap: 13px; padding: 18px; border-radius: 20px 20px 12px 12px; background: #fff; box-shadow: 0 22px 60px rgba(15,30,20,.28); }
.setup-dialog header { display: flex; align-items: center; justify-content: space-between; }
.setup-dialog h2 { margin: 0; font-size: 19px; }
.setup-dialog header button { width: 36px; height: 36px; border: 1px solid var(--line); border-radius: 50%; background: #fff; font-size: 21px; }
.setup-dialog label { display: grid; gap: 6px; }
.setup-dialog label span { color: var(--muted); font-size: 12px; }
.setup-divider { display: flex; align-items: center; gap: 9px; color: var(--muted); font-size: 11px; }
.setup-divider::before, .setup-divider::after { height: 1px; flex: 1; background: var(--line); content: ""; }
.visually-hidden { position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none; }

@media (max-width: 640px) {
  .inventory-page { width: 100%; min-width: 0; max-width: 100vw; min-height: 100dvh; overflow-x: clip; padding: 0; }
  .phone-surface { width: 100%; min-height: 100dvh; border: 0; border-radius: 0; box-shadow: none; }
  .inventory-appbar { padding-top: calc(10px + env(safe-area-inset-top)); }
  .inventory-body { padding-bottom: calc(72px + env(safe-area-inset-bottom)); }
  .bottom-nav { height: calc(70px + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom); }
  .setup-backdrop { padding: 0; }
  .setup-dialog { border-radius: 20px 20px 0 0; padding-bottom: calc(18px + env(safe-area-inset-bottom)); }
}

@media (max-width: 390px) {
  .inventory-page, .phone-surface, .inventory-body, .scan-view, .manual-entry, .result-view, .collector-card { min-width: 0; max-width: 100%; }
  .inventory-appbar, .batch-row, .manual-entry, .result-view, .records-view, .import-view { overflow-wrap: anywhere; }
  .manual-entry > div { grid-template-columns: minmax(0, 1fr) auto; }
}

@media (prefers-reduced-motion: reduce) { .scan-frame span { animation: none; } }
</style>
