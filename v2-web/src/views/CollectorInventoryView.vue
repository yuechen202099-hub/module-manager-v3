<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import {
  fetchProjectCollectorInventory,
  registerProjectCollector,
  scanProjectCollector,
} from '@/api/services'
import type {
  CollectorInventoryDecision,
  CollectorInventoryPage,
  CollectorPhotoRegistration,
} from '@/api/types'
import { inventoryResultPresentation } from '@/features/collectorTransfer/state'
import { useWorkspaceStore } from '@/stores/workspace'

type MobileView = 'scan' | 'records'
type CameraStatus = 'idle' | 'starting' | 'scanning' | 'unsupported' | 'denied'
type UploadStatus = 'idle' | 'uploading' | 'success' | 'error'
type DetectedBarcode = { rawValue?: string }
type NativeBarcodeDetector = { detect: (source: HTMLVideoElement) => Promise<DetectedBarcode[]> }
type NativeBarcodeDetectorConstructor = new (options?: { formats?: string[] }) => NativeBarcodeDetector
type QuaggaScanner = {
  init?: (options: unknown, callback: (error?: unknown) => void) => void
  onDetected?: (handler: (result: unknown) => void) => void
  offDetected?: (handler: (result: unknown) => void) => void
  start?: () => void
  stop?: () => void
}

const CAMERA_START_TIMEOUT_MS = 7_000
const VIDEO_PLAY_TIMEOUT_MS = 3_000
const QUAGGA_READERS = ['code_128_reader', 'code_39_reader', 'ean_reader', 'ean_8_reader']

const EMPTY_INVENTORY: CollectorInventoryPage = {
  items: [],
  total: 0,
  stats: { direct: 0, available: 0, reserved: 0, used: 0, awaiting_photo: 0 },
}

const workspace = useWorkspaceStore()
const mobileView = ref<MobileView>('scan')
const collectorNo = ref('')
const result = ref<CollectorInventoryDecision | null>(null)
const inventory = ref<CollectorInventoryPage>(structuredClone(EMPTY_INVENTORY))
const loading = ref(false)
const inventoryLoading = ref(false)
const cameraActive = ref(false)
const cameraStatus = ref<CameraStatus>('idle')
const scanFeedback = ref('')
const completedDuplicateFeedback = ref('')
const uploadStatus = ref<UploadStatus>('idle')
const uploadMessage = ref('')
const localPhotoUrl = ref('')
const video = ref<HTMLVideoElement | null>(null)
const photoInput = ref<HTMLInputElement | null>(null)
const pendingPhoto = ref<File | null>(null)
const completedCollectorNos = new Set<string>()

let mediaStream: MediaStream | null = null
let barcodeDetector: NativeBarcodeDetector | null = null
let animationFrameId = 0
let cameraSession = 0
let quaggaActive = false
let quaggaDetectedHandler: ((result: unknown) => void) | null = null
const cameraTimeoutRejectors = new Map<number, (reason?: unknown) => void>()
let scanInFlight = false
let lastDecodedValue = ''
let lastDecodedAt = 0
let inventoryGeneration = 0
let projectContextGeneration = 0
let componentUnmounted = false

const activeProject = computed(() => workspace.activeProject || null)
const activeProjectId = computed(() => String(activeProject.value?.id || ''))
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
  const current = result.value
  if (!current) return ''
  if (current.decision === 'existing_available') return '已在替换池'
  if (current.decision === 'existing_reserved' || current.decision === 'existing_used') {
    return '禁止重复使用'
  }
  if (current.add_to_pool) return current.requires_photo ? '拍照后加入替换池' : '已加入替换池'
  if (current.decision === 'direct_needs_photo') return '直接匹配，不入池'
  return '同号直接匹配，不进入随机池'
})
const registrationDetail = computed(() => {
  const current = result.value
  if (!current) return ''
  if (current.decision === 'existing_available') return '已登记库存'
  if (current.decision === 'existing_reserved') return '已被任务预留'
  if (current.decision === 'existing_used') return '已完成使用'
  return current.add_to_pool ? '替换池候选' : '同号直接匹配'
})
const primaryActionLabel = computed(() => (
  uploadStatus.value === 'error' && pendingPhoto.value
    ? '重新上传'
    : presentation.value?.primaryAction || ''
))
const cameraStatusMessage = computed(() => {
  if (cameraStatus.value === 'starting') return '正在请求摄像头权限…'
  if (cameraStatus.value === 'scanning') return scanFeedback.value || '连续扫码已开启'
  if (cameraStatus.value === 'unsupported') return '浏览器不支持摄像头扫码，请手工输入或使用扫码枪'
  if (cameraStatus.value === 'denied') return '摄像头不可用，请手工输入或使用扫码枪'
  return '手工输入与外接扫码枪始终可用'
})

onMounted(() => {
  if (activeProjectId.value) void loadInventory(activeProjectId.value)
})

watch(activeProjectId, (nextProjectId, previousProjectId) => {
  if (nextProjectId === previousProjectId) return
  resetProjectContext()
  if (nextProjectId) void loadInventory(nextProjectId)
})

onUnmounted(() => {
  componentUnmounted = true
  inventoryGeneration += 1
  projectContextGeneration += 1
  stopCamera()
  releaseLocalPhotoUrl()
  pendingPhoto.value = null
})

async function loadInventory(projectId: string) {
  if (!projectId || componentUnmounted) return
  const requestGeneration = ++inventoryGeneration
  inventoryLoading.value = true
  try {
    const nextInventory = await fetchProjectCollectorInventory(projectId)
    if (
      componentUnmounted
      || requestGeneration !== inventoryGeneration
      || projectId !== activeProjectId.value
    ) return
    inventory.value = nextInventory
  } catch (error) {
    if (
      componentUnmounted
      || requestGeneration !== inventoryGeneration
      || projectId !== activeProjectId.value
    ) return
    ElMessage.error(error instanceof Error ? error.message : '采集器库存加载失败')
  } finally {
    if (requestGeneration === inventoryGeneration) inventoryLoading.value = false
  }
}

function resetProjectContext() {
  projectContextGeneration += 1
  inventoryGeneration += 1
  scanInFlight = false
  lastDecodedValue = ''
  lastDecodedAt = 0
  loading.value = false
  inventoryLoading.value = false
  stopCamera()
  releaseLocalPhotoUrl()
  pendingPhoto.value = null
  collectorNo.value = ''
  result.value = null
  inventory.value = structuredClone(EMPTY_INVENTORY)
  uploadStatus.value = 'idle'
  uploadMessage.value = ''
  scanFeedback.value = ''
  completedDuplicateFeedback.value = ''
  completedCollectorNos.clear()
  mobileView.value = 'scan'
  if (photoInput.value) photoInput.value.value = ''
}

async function submitScan(rawValue = collectorNo.value) {
  const projectId = activeProjectId.value
  const value = rawValue.trim()
  if (!projectId) {
    ElMessage.warning('请先选择项目')
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

  const requestGeneration = projectContextGeneration
  completedDuplicateFeedback.value = completedCollectorNos.has(value)
    ? `重复扫码：${value} 已处理，本次重新确认。`
    : ''
  scanInFlight = true
  loading.value = true
  try {
    const decision = await scanProjectCollector(projectId, value)
    if (
      componentUnmounted
      || requestGeneration !== projectContextGeneration
      || projectId !== activeProjectId.value
    ) return
    releaseLocalPhotoUrl()
    pendingPhoto.value = null
    uploadStatus.value = 'idle'
    uploadMessage.value = ''
    result.value = decision
    collectorNo.value = decision.collector_no
    completedCollectorNos.add(decision.collector_no)
    stopCamera()
  } catch (error) {
    if (
      componentUnmounted
      || requestGeneration !== projectContextGeneration
      || projectId !== activeProjectId.value
    ) return
    ElMessage.error(error instanceof Error ? error.message : '采集器扫码判断失败')
  } finally {
    if (
      requestGeneration === projectContextGeneration
      && projectId === activeProjectId.value
    ) {
      scanInFlight = false
      loading.value = false
    }
  }
}

async function startCamera() {
  if (cameraActive.value || !activeProjectId.value) return
  result.value = null
  releaseLocalPhotoUrl()
  pendingPhoto.value = null
  uploadStatus.value = 'idle'
  uploadMessage.value = ''
  scanFeedback.value = ''
  if (globalThis.isSecureContext === false || typeof navigator.mediaDevices?.getUserMedia !== 'function') {
    cameraStatus.value = 'unsupported'
    return
  }
  const session = ++cameraSession
  cameraStatus.value = 'starting'
  try {
    const stream = await requestCameraStream(session)
    if (session !== cameraSession) {
      stopMediaStream(stream)
      return
    }
    mediaStream = stream
    await nextTick()
    if (!video.value) throw new Error('摄像头画面尚未就绪')
    const preview = video.value
    preview.setAttribute('playsinline', 'true')
    preview.setAttribute('webkit-playsinline', 'true')
    preview.autoplay = true
    preview.muted = true
    preview.srcObject = stream
    await withCameraTimeout(preview.play(), VIDEO_PLAY_TIMEOUT_MS, '摄像头预览启动超时')
    if (session !== cameraSession) return
    cameraActive.value = true
    cameraStatus.value = 'scanning'
    const Detector = (globalThis as typeof globalThis & {
      BarcodeDetector?: NativeBarcodeDetectorConstructor
    }).BarcodeDetector
    if (Detector) {
      barcodeDetector = new Detector({ formats: ['code_128', 'code_39', 'ean_13'] })
      scanFeedback.value = '相机已打开，正在使用浏览器原生识别。'
      void detectNextFrame(session)
      return
    }
    scanFeedback.value = '相机已打开，正在加载实时识别。'
    void startQuaggaScanner(session)
  } catch (error) {
    if (session !== cameraSession) return
    stopCamera()
    cameraStatus.value = 'denied'
    ElMessage.warning(error instanceof Error ? error.message : '无法打开摄像头')
  }
}

function stopCamera() {
  cameraSession += 1
  for (const reject of [...cameraTimeoutRejectors.values()]) reject(new Error('摄像头启动已取消'))
  cameraTimeoutRejectors.clear()
  if (animationFrameId) cancelAnimationFrame(animationFrameId)
  animationFrameId = 0
  barcodeDetector = null
  const quagga = getQuagga()
  if (quaggaDetectedHandler) quagga?.offDetected?.(quaggaDetectedHandler)
  if (quaggaActive) {
    try {
      quagga?.stop?.()
    } catch {
      // Mobile scanners can race while their stream is shutting down.
    }
  }
  quaggaActive = false
  quaggaDetectedHandler = null
  cameraActive.value = false
  if (mediaStream) stopMediaStream(mediaStream)
  mediaStream = null
  if (video.value) video.value.srcObject = null
  video.value?.parentElement?.querySelectorAll('canvas, video:not(.collector-camera-preview)').forEach((node) => node.remove())
}

async function detectNextFrame(session: number) {
  if (!cameraActive.value || session !== cameraSession || !barcodeDetector || !video.value) return
  try {
    const detected = await barcodeDetector.detect(video.value)
    handleDetectedValue(detected[0]?.rawValue || '')
  } catch {
    scanFeedback.value = '本帧未识别，请继续对准条形码'
  } finally {
    if (cameraActive.value && session === cameraSession) {
      animationFrameId = requestAnimationFrame(() => void detectNextFrame(session))
    }
  }
}

function getQuagga(): QuaggaScanner | null {
  const source = window as typeof window & {
    Quagga?: QuaggaScanner
    Quagga2?: QuaggaScanner
    exports?: { Quagga?: QuaggaScanner }
    module?: { exports?: QuaggaScanner }
  }
  return source.Quagga || source.Quagga2 || source.exports?.Quagga || source.module?.exports || null
}

function withCameraTimeout<T>(
  promise: Promise<T>,
  milliseconds: number,
  message: string,
  onLateResolution?: (value: T) => void,
) {
  let timer = 0
  let settled = false
  return new Promise<T>((resolve, reject) => {
    const finish = (callback: () => void) => {
      if (settled) return false
      settled = true
      window.clearTimeout(timer)
      cameraTimeoutRejectors.delete(timer)
      callback()
      return true
    }
    timer = window.setTimeout(() => finish(() => reject(new Error(message))), milliseconds)
    cameraTimeoutRejectors.set(timer, (reason) => finish(() => reject(reason)))
    promise.then(
      (value) => {
        if (!finish(() => resolve(value))) onLateResolution?.(value)
      },
      (error) => finish(() => reject(error)),
    )
  })
}

function stopMediaStream(stream: MediaStream) {
  for (const track of stream.getTracks()) track.stop()
}

async function requestCameraStream(session: number) {
  try {
    return await withCameraTimeout(
      navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      }),
      CAMERA_START_TIMEOUT_MS,
      '后置摄像头启动超时',
      stopMediaStream,
    )
  } catch {
    if (session !== cameraSession) throw new Error('摄像头启动已取消')
    return withCameraTimeout(
      navigator.mediaDevices.getUserMedia({ audio: false, video: true }),
      CAMERA_START_TIMEOUT_MS,
      '摄像头启动超时',
      stopMediaStream,
    )
  }
}

async function ensureQuaggaLoaded() {
  if (getQuagga()?.init) return getQuagga()
  await withCameraTimeout(
    new Promise<void>((resolve, reject) => {
      const existing = document.querySelector<HTMLScriptElement>('script[data-collector-quagga-loader="1"]')
      if (existing) {
        if (existing.dataset.loaded === '1' || getQuagga()?.init) {
          resolve()
          return
        }
        existing.addEventListener('load', () => {
          existing.dataset.loaded = '1'
          resolve()
        }, { once: true })
        existing.addEventListener('error', () => reject(new Error('QuaggaJS 加载失败')), { once: true })
        return
      }
      const script = document.createElement('script')
      script.src = '/static/vendor/quagga.min.js?v=20260615-quagga2'
      script.async = true
      script.dataset.collectorQuaggaLoader = '1'
      script.onload = () => {
        script.dataset.loaded = '1'
        resolve()
      }
      script.onerror = () => reject(new Error('QuaggaJS 加载失败'))
      document.head.appendChild(script)
    }),
    CAMERA_START_TIMEOUT_MS,
    'QuaggaJS 加载超时',
  )
  return getQuagga()
}

async function startQuaggaScanner(session: number) {
  try {
    const quagga = await ensureQuaggaLoaded()
    if (session !== cameraSession) return
    if (!quagga?.init || !video.value?.parentElement) throw new Error('QuaggaJS 不可用')
    await withCameraTimeout(
      new Promise<void>((resolve, reject) => {
        quagga.init?.(
          {
            inputStream: {
              name: 'Live',
              type: 'LiveStream',
              target: video.value?.parentElement,
              constraints: {
                facingMode: { ideal: 'environment' },
                width: { ideal: 1280 },
                height: { ideal: 720 },
                audio: false,
              },
            },
            locator: { patchSize: 'medium', halfSample: true },
            locate: true,
            numOfWorkers: Math.min(2, Math.max(0, navigator.hardwareConcurrency || 0)),
            frequency: 8,
            decoder: { readers: QUAGGA_READERS },
          },
          (error) => (error ? reject(error) : resolve()),
        )
      }),
      CAMERA_START_TIMEOUT_MS,
      'QuaggaJS 初始化超时',
    )
    if (session !== cameraSession) {
      try {
        quagga.stop?.()
      } catch {
        // The late scanner must not outlive its project or component.
      }
      return
    }
    quaggaActive = true
    quaggaDetectedHandler = (result) => handleDetectedValue(
      (result as { codeResult?: { code?: string } })?.codeResult?.code || '',
    )
    quagga.onDetected?.(quaggaDetectedHandler)
    quagga.start?.()
    scanFeedback.value = 'QuaggaJS 正在识别条形码。'
  } catch {
    if (session !== cameraSession || !cameraActive.value) return
    scanFeedback.value = '相机已打开，当前浏览器不支持实时识别，可手工输入或使用扫码枪。'
  }
}

function handleDetectedValue(rawValue: string) {
  const value = rawValue.trim()
  const now = Date.now()
  if (!value) return
  if (scanInFlight && value === lastDecodedValue) {
    scanFeedback.value = '已识别该采集器，正在查询，请勿重复扫码'
  } else if (
    completedCollectorNos.has(value)
    || value !== lastDecodedValue
    || now - lastDecodedAt >= 1800
  ) {
    lastDecodedValue = value
    lastDecodedAt = now
    collectorNo.value = value
    void submitScan(value)
  }
}

function requestPhoto() {
  photoInput.value?.click()
}

function handlePrimaryAction() {
  if (!result.value?.requires_photo) {
    resetForNextScan()
    return
  }
  if (uploadStatus.value === 'error' && pendingPhoto.value) {
    void submitPhoto(pendingPhoto.value)
    return
  }
  requestPhoto()
}

function handlePhotoChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !result.value?.requires_photo) return
  releaseLocalPhotoUrl()
  pendingPhoto.value = file
  localPhotoUrl.value = URL.createObjectURL(file)
  void submitPhoto(file)
}

async function submitPhoto(file: File) {
  const projectId = activeProjectId.value
  const currentDecision = result.value
  if (!projectId || !currentDecision?.requires_photo) return
  const requestGeneration = projectContextGeneration
  uploadStatus.value = 'uploading'
  uploadMessage.value = '照片上传中…'
  loading.value = true
  try {
    const uploaded = await registerProjectCollector(
      projectId,
      currentDecision.collector_no,
      file,
    )
    if (
      componentUnmounted
      || requestGeneration !== projectContextGeneration
      || projectId !== activeProjectId.value
    ) return
    applyUploadedPhoto(currentDecision, uploaded)
    pendingPhoto.value = null
    uploadStatus.value = 'success'
    uploadMessage.value = uploaded.pool_status === 'available'
      ? '照片上传成功，已加入替换池'
      : '上传成功，照片已完成同号确认'
    ElMessage.success(uploadMessage.value)
    await loadInventory(projectId)
  } catch (error) {
    if (
      componentUnmounted
      || requestGeneration !== projectContextGeneration
      || projectId !== activeProjectId.value
    ) return
    uploadStatus.value = 'error'
    uploadMessage.value = `上传失败：${error instanceof Error ? error.message : '请重试'}`
    ElMessage.error(error instanceof Error ? error.message : '采集器照片上传失败')
  } finally {
    if (
      requestGeneration === projectContextGeneration
      && projectId === activeProjectId.value
    ) loading.value = false
  }
}

function applyUploadedPhoto(
  currentDecision: CollectorInventoryDecision,
  uploaded: CollectorPhotoRegistration,
) {
  result.value = {
    ...currentDecision,
    collector_id: uploaded.collector_id,
    collector_no: uploaded.collector_no,
    requires_photo: false,
    pool_status: uploaded.pool_status,
    photo: uploaded.photo,
  }
}

function cancelCapture() {
  releaseLocalPhotoUrl()
  pendingPhoto.value = null
  uploadStatus.value = 'idle'
  uploadMessage.value = ''
  if (photoInput.value) photoInput.value.value = ''
}

function cancelAndContinue() {
  cancelCapture()
  resetForNextScan(false)
}

function resetForNextScan(reopenCamera = true) {
  result.value = null
  collectorNo.value = ''
  completedDuplicateFeedback.value = ''
  uploadStatus.value = 'idle'
  uploadMessage.value = ''
  releaseLocalPhotoUrl()
  pendingPhoto.value = null
  mobileView.value = 'scan'
  if (reopenCamera) void startCamera()
}

function setMobileView(view: MobileView) {
  if (view !== 'scan') stopCamera()
  mobileView.value = view
}

function releaseLocalPhotoUrl() {
  if (!localPhotoUrl.value) return
  URL.revokeObjectURL(localPhotoUrl.value)
  localPhotoUrl.value = ''
}
</script>

<template>
  <div class="inventory-page">
    <section class="phone-surface" :aria-busy="loading || inventoryLoading">
      <header class="inventory-appbar">
        <div>
          <strong>采集器实物登记</strong>
          <small>打开即可扫码拍照</small>
        </div>
        <span class="live-dot">项目库存</span>
      </header>

      <div class="stage-banner">只做扫码、拍照和入池判断 · 不连接甲方平台</div>
      <div v-if="activeProject" class="project-row">
        <p class="project-identity" data-testid="project-identity">
          <span>当前项目</span>
          <strong>{{ activeProject.name }}</strong>
          <small>{{ activeProject.id }}</small>
        </p>
        <div class="inventory-count">
          <strong>{{ inventory.total }}</strong>
          <span>已登记</span>
        </div>
      </div>

      <main class="inventory-body">
        <section v-if="!activeProject" class="project-empty" data-testid="project-empty-state">
          <span aria-hidden="true">⌁</span>
          <h1>请先选择项目</h1>
          <p>采集器库存严格按项目隔离。选择当前项目后才能扫码和拍照。</p>
        </section>

        <section v-else-if="mobileView === 'scan'" class="scan-view">
          <template v-if="!result">
            <div class="camera-stage">
              <video v-show="cameraActive" ref="video" class="collector-camera-preview" autoplay muted playsinline />
              <div v-if="!cameraActive" class="camera-empty">
                <span class="camera-glyph" aria-hidden="true">⌗</span>
                <strong>扫描采集器条形码</strong>
                <small>识别后立即判断是否需要拍照</small>
                <button
                  class="primary-button"
                  data-testid="start-camera"
                  type="button"
                  @click="startCamera"
                >
                  打开摄像头扫码
                </button>
                <span class="camera-status" data-testid="camera-status" aria-live="polite">
                  {{ cameraStatusMessage }}
                </span>
              </div>
              <div v-if="cameraActive" class="scan-frame"><span /></div>
              <p
                v-if="cameraActive"
                class="scan-hint"
                data-testid="scan-feedback"
                aria-live="polite"
              >
                {{ scanFeedback || '对准条形码，识别后自动判断' }}
              </p>
            </div>

            <form class="manual-entry" @submit.prevent="submitScan()">
              <label for="collector-number">无法识别时，可手工输入或使用外接扫码枪</label>
              <div>
                <input
                  id="collector-number"
                  v-model="collectorNo"
                  inputmode="text"
                  autocomplete="off"
                  placeholder="扫描或输入采集器号"
                >
                <button class="primary-button" type="submit" :disabled="loading">判断</button>
              </div>
            </form>
          </template>

          <section v-else class="result-view" :class="`tone-${presentation?.tone}`">
            <div class="result-heading">
              <span class="result-icon">{{ presentation?.tone === 'success' ? '✓' : '!' }}</span>
              <h1 data-testid="decision-title">{{ presentation?.title }}</h1>
              <p>{{ presentation?.description }}</p>
            </div>
            <p
              v-if="completedDuplicateFeedback"
              class="duplicate-feedback"
              data-testid="completed-duplicate-feedback"
              aria-live="polite"
            >
              {{ completedDuplicateFeedback }}
            </p>

            <div class="collector-card">
              <div class="collector-preview">
                <img
                  v-if="photoUrl"
                  :src="photoUrl"
                  data-testid="photo-preview"
                  alt="采集器照片预览"
                >
                <div v-else class="device-placeholder"><span>{{ result.collector_no }}</span></div>
              </div>
              <dl>
                <div><dt>采集器号</dt><dd>{{ result.collector_no }}</dd></div>
                <div><dt>登记结果</dt><dd>{{ registrationDetail }}</dd></div>
                <div><dt>替换池</dt><dd data-testid="pool-semantics">{{ poolSemantics }}</dd></div>
              </dl>
            </div>

            <p class="boundary-note">扫码页面不会创建批次，也不会录入或上传甲方平台。</p>
            <p
              v-if="uploadStatus !== 'idle'"
              class="upload-status"
              :class="`status-${uploadStatus}`"
              data-testid="upload-status"
              aria-live="polite"
            >
              {{ uploadMessage }}
            </p>
            <div class="result-actions">
              <button
                class="primary-button wide"
                data-testid="decision-primary-action"
                type="button"
                :disabled="uploadStatus === 'uploading'"
                @click="handlePrimaryAction"
              >
                {{ primaryActionLabel }}
              </button>
              <button
                v-if="result.requires_photo"
                class="secondary-button wide"
                data-testid="capture-cancel"
                type="button"
                :disabled="uploadStatus === 'uploading'"
                @click="cancelAndContinue"
              >
                取消，继续扫码
              </button>
              <button class="text-button" type="button" @click="setMobileView('records')">
                查看项目库存记录
              </button>
            </div>
          </section>
        </section>

        <section v-else class="records-view" data-testid="inventory-records">
          <header>
            <div>
              <h1>项目采集器库存</h1>
              <p>只显示当前项目，禁止跨项目复用。</p>
            </div>
            <button type="button" :disabled="inventoryLoading" @click="loadInventory(activeProjectId)">刷新</button>
          </header>
          <div class="stat-strip">
            <span><strong>{{ inventory.stats.direct }}</strong>同号</span>
            <span><strong>{{ inventory.stats.available }}</strong>可用</span>
            <span><strong>{{ inventory.stats.reserved }}</strong>已占用</span>
            <span><strong>{{ inventory.stats.used }}</strong>已使用</span>
          </div>
          <div v-if="inventory.items.length" class="record-list">
            <article v-for="item in inventory.items" :key="item.collector_id">
              <img
                v-if="item.photo?.thumbnail_url || item.photo?.preview_url || item.photo?.image_url"
                :src="item.photo.thumbnail_url || item.photo.preview_url || item.photo.image_url"
                alt="采集器缩略图"
              >
              <span v-else class="record-placeholder">⌗</span>
              <div>
                <strong>{{ item.collector_no }}</strong>
                <small>{{ item.last_scanned_at || item.created_at || '暂无时间' }}</small>
              </div>
              <em :class="`status-${item.pool_status}`">{{ item.pool_status }}</em>
            </article>
          </div>
          <div v-else class="empty-state">当前项目还没有采集器库存</div>
        </section>
      </main>

      <nav v-if="activeProject" class="bottom-nav" aria-label="采集器盘点功能">
        <button
          :class="{ active: mobileView === 'scan' }"
          type="button"
          aria-label="扫码"
          @click="setMobileView('scan')"
        >
          <span>⌗</span>扫码
        </button>
        <button
          :class="{ active: mobileView === 'records' }"
          type="button"
          aria-label="盘点记录"
          @click="setMobileView('records')"
        >
          <span>▤</span>盘点记录
        </button>
      </nav>
    </section>

    <input
      ref="photoInput"
      class="visually-hidden"
      data-testid="photo-input"
      type="file"
      accept="image/*"
      capture="environment"
      :disabled="!result?.requires_photo || uploadStatus === 'uploading'"
      @change="handlePhotoChange"
      @cancel="cancelCapture"
    >
  </div>
</template>

<style scoped>
.inventory-page {
  min-height: 100%;
  padding: 20px;
  background:
    radial-gradient(circle at 15% 0%, rgb(27 83 146 / 14%), transparent 34%),
    #eef2f7;
  color: #132238;
}

.phone-surface {
  width: min(100%, 480px);
  min-height: calc(100vh - 40px);
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid #d9e1ea;
  border-radius: 28px;
  background: #f8fafc;
  box-shadow: 0 22px 54px rgb(15 35 59 / 16%);
}

.inventory-appbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px 14px;
  background: #102d4f;
  color: white;
}

.inventory-appbar div,
.project-identity {
  display: grid;
  gap: 3px;
}

.inventory-appbar strong { font-size: 18px; }
.inventory-appbar small { color: #bcd0e7; }

.live-dot {
  padding: 6px 10px;
  border: 1px solid rgb(255 255 255 / 28%);
  border-radius: 999px;
  background: rgb(255 255 255 / 8%);
  font-size: 12px;
}

.stage-banner {
  padding: 9px 16px;
  background: #e9f5ee;
  color: #17643b;
  font-size: 12px;
  text-align: center;
}

.project-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid #e5ebf1;
  background: white;
}

.project-identity { margin: 0; min-width: 0; }
.project-identity span,
.project-identity small { color: #718096; font-size: 12px; }
.project-identity strong { overflow-wrap: anywhere; }

.inventory-count {
  display: grid;
  flex: 0 0 auto;
  justify-items: end;
  color: #718096;
  font-size: 11px;
}

.inventory-count strong { color: #17643b; font-size: 24px; line-height: 1; }

.inventory-body { padding: 18px; }

.project-empty,
.empty-state {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 300px;
  padding: 30px;
  color: #6a788a;
  text-align: center;
}

.project-empty > span { font-size: 52px; color: #7d91aa; }
.project-empty h1,
.project-empty p { margin: 0; }

.camera-stage {
  position: relative;
  min-height: 310px;
  overflow: hidden;
  border-radius: 22px;
  background: linear-gradient(155deg, #173554, #0c2037);
  color: white;
}

.camera-stage video {
  width: 100%;
  min-height: 310px;
  object-fit: cover;
}

.camera-empty {
  display: grid;
  place-items: center;
  gap: 10px;
  min-height: 310px;
  padding: 28px;
  text-align: center;
}

.camera-empty small,
.camera-status { color: #b9c9da; }
.camera-glyph { font-size: 68px; line-height: 1; color: #71d29b; }
.camera-status { min-height: 18px; font-size: 12px; }

.scan-frame {
  position: absolute;
  inset: 24% 12%;
  border: 2px solid #71d29b;
  border-radius: 16px;
  box-shadow: 0 0 0 999px rgb(0 0 0 / 25%);
}

.scan-frame span {
  position: absolute;
  top: 50%;
  right: 8px;
  left: 8px;
  height: 2px;
  background: #71d29b;
  box-shadow: 0 0 10px #71d29b;
}

.scan-hint {
  position: absolute;
  right: 20px;
  bottom: 14px;
  left: 20px;
  margin: 0;
  font-size: 12px;
  text-align: center;
}

.manual-entry {
  display: grid;
  gap: 8px;
  margin-top: 16px;
}

.manual-entry label { color: #5f6f82; font-size: 12px; }
.manual-entry > div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; }

input,
button { font: inherit; }

input {
  min-width: 0;
  padding: 12px 13px;
  border: 1px solid #ccd7e3;
  border-radius: 12px;
  background: white;
  color: #132238;
}

button { cursor: pointer; }
button:disabled { cursor: not-allowed; opacity: .58; }

.primary-button,
.secondary-button,
.text-button,
.records-view header button {
  min-height: 44px;
  border-radius: 12px;
  font-weight: 700;
}

.primary-button {
  padding: 0 18px;
  border: 0;
  background: #147a4c;
  color: white;
}

.secondary-button {
  border: 1px solid #c8d3df;
  background: white;
  color: #243c58;
}

.text-button {
  border: 0;
  background: transparent;
  color: #315f8c;
}

.wide { width: 100%; }

.result-heading {
  display: grid;
  justify-items: center;
  gap: 8px;
  padding: 8px 0 18px;
  text-align: center;
}

.result-heading h1,
.result-heading p { margin: 0; }
.result-heading p { color: #65758a; }

.result-icon {
  display: grid;
  width: 56px;
  height: 56px;
  place-items: center;
  border-radius: 50%;
  background: #dff4e7;
  color: #147a4c;
  font-size: 28px;
  font-weight: 800;
}

.tone-warning .result-icon { background: #fff2d7; color: #a86000; }
.tone-danger .result-icon { background: #ffe2e2; color: #a32929; }

.duplicate-feedback,
.boundary-note,
.upload-status {
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 12px;
}

.duplicate-feedback { background: #eef3f8; color: #415a75; }
.boundary-note { background: #eef6f1; color: #35634a; }
.upload-status { background: #edf3fa; color: #315f8c; }
.upload-status.status-error { background: #fff0f0; color: #a32929; }
.upload-status.status-success { background: #e8f6ee; color: #17643b; }

.collector-card {
  overflow: hidden;
  border: 1px solid #dce4ec;
  border-radius: 18px;
  background: white;
}

.collector-preview {
  display: grid;
  min-height: 190px;
  place-items: center;
  background: #e9eff5;
}

.collector-preview img { width: 100%; height: 230px; object-fit: cover; }
.device-placeholder { display: grid; padding: 25px; place-items: center; color: #415a75; }
.device-placeholder span { overflow-wrap: anywhere; font-weight: 800; }

.collector-card dl { display: grid; gap: 0; margin: 0; padding: 4px 16px; }
.collector-card dl div { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 10px; padding: 11px 0; border-bottom: 1px solid #edf1f5; }
.collector-card dl div:last-child { border-bottom: 0; }
.collector-card dt { color: #718096; }
.collector-card dd { margin: 0; overflow-wrap: anywhere; font-weight: 700; }

.result-actions { display: grid; gap: 9px; margin-top: 14px; }

.records-view header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 12px;
}

.records-view h1,
.records-view p { margin: 0; }
.records-view p { color: #718096; font-size: 12px; }
.records-view header button { min-height: 36px; padding: 0 13px; border: 1px solid #c8d3df; background: white; }

.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 16px 0;
}

.stat-strip span {
  display: grid;
  justify-items: center;
  padding: 10px 3px;
  border-radius: 12px;
  background: white;
  color: #718096;
  font-size: 10px;
}

.stat-strip strong { color: #173554; font-size: 18px; }
.record-list { display: grid; gap: 10px; }

.record-list article {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  align-items: center;
  gap: 11px;
  padding: 10px;
  border: 1px solid #e0e7ef;
  border-radius: 14px;
  background: white;
}

.record-list img,
.record-placeholder { width: 52px; height: 52px; border-radius: 10px; }
.record-list img { object-fit: cover; }
.record-placeholder { display: grid; place-items: center; background: #e9eff5; color: #52677e; }
.record-list article > div { display: grid; min-width: 0; gap: 4px; }
.record-list article strong { overflow-wrap: anywhere; }
.record-list article small { color: #8190a1; font-size: 10px; }
.record-list em { padding: 4px 7px; border-radius: 999px; background: #edf3f8; color: #52677e; font-size: 10px; font-style: normal; }
.record-list em.status-available { background: #e6f6ec; color: #17643b; }
.record-list em.status-used { background: #f2e9e9; color: #923a3a; }

.bottom-nav {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 1px solid #dfe7ef;
  background: white;
}

.bottom-nav button {
  display: grid;
  justify-items: center;
  gap: 2px;
  min-height: 64px;
  border: 0;
  background: transparent;
  color: #718096;
  font-size: 11px;
}

.bottom-nav button span { font-size: 22px; }
.bottom-nav button.active { color: #147a4c; }

.visually-hidden {
  position: fixed;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@media (max-width: 520px) {
  .inventory-page { padding: 0; background: #f8fafc; }
  .phone-surface { min-height: 100vh; border: 0; border-radius: 0; box-shadow: none; }
  .inventory-body { padding: 14px; }
}
</style>
