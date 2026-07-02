<script setup lang="ts">
import { computed, ref } from 'vue'

type FieldSource = 'import' | 'field_collection' | 'review' | 'system'
type CaptureMethod = 'manual' | 'scan' | 'photo' | 'select' | 'datetime' | 'location' | 'system' | 'none'
type DataType = 'text' | 'number' | 'datetime' | 'image' | 'enum' | 'duration' | 'location' | 'boolean'

type FieldForm = {
  key: string
  label: string
  dataType: DataType
  source: FieldSource
  captureMethod: CaptureMethod
  required: boolean
  parentKey?: string
  kpiEnabled: boolean
}

type FieldGraphItem = {
  field: FieldForm
  index: number
  role: string
}

type FieldRoleBucket = {
  id: string
  label: string
  helper: string
  items: FieldGraphItem[]
}

type FieldSelectionType = 'aggregate' | 'primary' | 'custom' | 'platform'

type FieldUpdatePayload = {
  type: Exclude<FieldSelectionType, 'platform'>
  fieldIndex?: number
  updates: Partial<FieldForm>
}

type TemplateBindingPreview = {
  initialWorkOrders: string[]
  externalCompleted: string[]
  siteRequiredFields: string[]
}

type TemplateActionPayload = {
  action: 'download' | 'validate'
  templateType: 'initial_work_orders' | 'external_completed'
}

const props = defineProps<{
  primaryField: FieldForm
  aggregateField: FieldForm
  customFields: FieldForm[]
  platformRequiredFields?: FieldForm[]
  templatePreview?: TemplateBindingPreview | null
  editable: boolean
}>()

const emit = defineEmits<{
  (event: 'update-parent', payload: { fieldIndex: number; parentKey: string }): void
  (event: 'update-field', payload: FieldUpdatePayload): void
  (event: 'template-action', payload: TemplateActionPayload): void
}>()

const selectedField = ref<{ type: FieldSelectionType; index: number } | null>(null)
const draggingFieldIndex = ref<number | null>(null)

const sourceOptions: Array<{ value: FieldSource; label: string }> = [
  { value: 'import', label: '初始导入' },
  { value: 'field_collection', label: '现场采集' },
  { value: 'review', label: '审阅补录' },
  { value: 'system', label: '系统生成' },
]

const captureMethodOptions: Array<{ value: CaptureMethod; label: string }> = [
  { value: 'manual', label: '录入' },
  { value: 'scan', label: '扫码' },
  { value: 'photo', label: '拍照' },
  { value: 'select', label: '选择' },
  { value: 'datetime', label: '时间' },
  { value: 'location', label: '定位' },
  { value: 'system', label: '系统' },
  { value: 'none', label: '无采集' },
]

const dataTypeOptions: Array<{ value: DataType; label: string }> = [
  { value: 'text', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'datetime', label: '时间' },
  { value: 'image', label: '图片' },
  { value: 'enum', label: '选项' },
  { value: 'duration', label: '时长' },
  { value: 'location', label: '位置' },
  { value: 'boolean', label: '是/否' },
]

const aggregateKey = computed(() => props.aggregateField.key || 'aggregate')
const primaryKey = computed(() => props.primaryField.key || 'primary')

const customItems = computed<FieldGraphItem[]>(() =>
  props.customFields.map((field, index) => ({
    field,
    index,
    role: fieldRole(field),
  })),
)

const aggregateChildren = computed(() =>
  customItems.value.filter((item) => (item.field.parentKey || primaryKey.value) === aggregateKey.value),
)

const primaryChildren = computed(() =>
  customItems.value.filter((item) => (item.field.parentKey || primaryKey.value) !== aggregateKey.value),
)

const importFields = computed(() => customItems.value.filter((item) => item.field.source === 'import'))
const collectionFields = computed(() =>
  customItems.value.filter((item) => item.field.source === 'field_collection' && item.field.dataType !== 'image'),
)
const photoFields = computed(() =>
  customItems.value.filter((item) => item.field.captureMethod === 'photo' || item.field.dataType === 'image'),
)
const platformKpiChecklistFields = ['安装人员', '安装时间', '在线时间', '照片数量', '旧设备回收']
const platformChecklistFields = computed(() =>
  Array.from(
    new Set([
      ...(props.platformRequiredFields || []).map((field) => fieldTitle(field, '平台必备字段')),
      ...platformKpiChecklistFields,
    ]),
  ).filter(Boolean),
)
const fieldRoleBuckets = computed<FieldRoleBucket[]>(() => [
  {
    id: 'import',
    label: '导入字段',
    helper: '初始建单可以从清单带入',
    items: importFields.value,
  },
  {
    id: 'collection',
    label: '现场采集',
    helper: '施工端扫码、拍照或录入',
    items: collectionFields.value,
  },
  {
    id: 'photo',
    label: '照片证据',
    helper: '审阅需要看到的影像资料',
    items: photoFields.value,
  },
  {
    id: 'platform',
    label: '平台必备',
    helper: '用于 KPI、效率和追溯',
    items: (props.platformRequiredFields || []).map((field, index) => ({
      field,
      index,
      role: '平台必备',
    })),
  },
])
const initialTemplateFields = computed(() =>
  props.templatePreview?.initialWorkOrders?.length
    ? props.templatePreview.initialWorkOrders
    : uniqueFieldLabels([
        props.primaryField,
        props.aggregateField,
        ...importFields.value.map((item) => item.field),
      ]),
)
const externalCompletedTemplateFields = computed(() =>
  props.templatePreview?.externalCompleted?.length
    ? props.templatePreview.externalCompleted
    : uniqueFieldLabels([
        props.primaryField,
        props.aggregateField,
        ...importFields.value.map((item) => item.field),
        ...collectionFields.value.map((item) => item.field),
        ...photoFields.value.map((item) => item.field),
      ]),
)
const siteRequiredFields = computed(() =>
  props.templatePreview?.siteRequiredFields?.length
    ? props.templatePreview.siteRequiredFields
    : uniqueFieldLabels(
        customItems.value
          .filter((item) => item.field.required && item.field.source === 'field_collection')
          .map((item) => item.field),
      ),
)
const siteChecklistFields = computed(() =>
  Array.from(new Set([...siteRequiredFields.value, ...platformChecklistFields.value])),
)

const selectedFieldDetail = computed(() => {
  if (!selectedField.value) return null
  if (selectedField.value.type === 'aggregate') return props.aggregateField
  if (selectedField.value.type === 'primary') return props.primaryField
  if (selectedField.value.type === 'platform') return props.platformRequiredFields?.[selectedField.value.index]
  return props.customFields[selectedField.value.index]
})

const selectedFieldEditable = computed(() => Boolean(props.editable && selectedField.value && selectedField.value.type !== 'platform'))

function fieldTitle(field: FieldForm, fallback: string) {
  return field.label?.trim() || field.key?.trim() || fallback
}

function uniqueFieldLabels(fields: FieldForm[]) {
  return Array.from(new Set(fields.map((field) => fieldTitle(field, '未命名字段')).filter(Boolean)))
}

function fieldRole(field: FieldForm) {
  if (field.captureMethod === 'photo' || field.dataType === 'image') return '照片证据'
  if (field.source === 'import') return '导入字段'
  if (field.source === 'field_collection') return '现场采集'
  if (field.source === 'review') return '审阅补录'
  return '系统字段'
}

function fieldMeta(field: FieldForm) {
  const required = field.required ? '必填' : '选填'
  const capture = captureLabel(field.captureMethod)
  const type = dataTypeLabel(field.dataType)
  return `${capture} · ${type} · ${required}`
}

function captureLabel(method: CaptureMethod) {
  const labels: Record<CaptureMethod, string> = {
    manual: '录入',
    scan: '扫码',
    photo: '拍照',
    select: '选择',
    datetime: '时间',
    location: '定位',
    system: '系统',
    none: '无采集',
  }
  return labels[method] || method
}

function dataTypeLabel(type: DataType) {
  const labels: Record<DataType, string> = {
    text: '文本',
    number: '数字',
    datetime: '时间',
    image: '图片',
    enum: '选项',
    duration: '时长',
    location: '位置',
    boolean: '是/否',
  }
  return labels[type] || type
}

function selectField(type: FieldSelectionType, index = -1) {
  selectedField.value = { type, index }
}

function isSelected(type: FieldSelectionType, index = -1) {
  return selectedField.value?.type === type && selectedField.value.index === index
}

function selectedParentLabel(field: FieldForm) {
  const parentKey = field.parentKey || primaryKey.value
  if (parentKey === aggregateKey.value) return fieldTitle(props.aggregateField, '聚合字段')
  if (parentKey === primaryKey.value) return fieldTitle(props.primaryField, '主字段')
  return parentKey || '项目对象'
}

function selectBucketItem(bucket: FieldRoleBucket) {
  const item = bucket.items[0]
  if (!item) return
  selectField(bucket.id === 'platform' ? 'platform' : 'custom', item.index)
}

function emitTemplateAction(action: TemplateActionPayload['action'], templateType: TemplateActionPayload['templateType']) {
  emit('template-action', { action, templateType })
}

function updateSelectedField(updates: Partial<FieldForm>) {
  if (!selectedField.value || selectedField.value.type === 'platform') return
  emit('update-field', {
    type: selectedField.value.type,
    fieldIndex: selectedField.value.type === 'custom' ? selectedField.value.index : undefined,
    updates,
  })
}

function onFieldDragStart(index: number, event: DragEvent) {
  if (!props.editable) return
  draggingFieldIndex.value = index
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function onDropParent(parentKey: string, event: DragEvent) {
  if (!props.editable) return
  const rawIndex = event.dataTransfer?.getData('text/plain')
  const fieldIndex = rawIndex ? Number(rawIndex) : draggingFieldIndex.value
  draggingFieldIndex.value = null
  if (fieldIndex === null || Number.isNaN(fieldIndex)) return
  emit('update-parent', { fieldIndex, parentKey })
}

function onDragEnd() {
  draggingFieldIndex.value = null
}
</script>

<template>
  <section class="field-graph-designer">
    <div class="field-graph-header">
      <div>
        <strong>字段关系图</strong>
        <span>用层级关系确认项目对象、导入字段、现场采集和照片证据。</span>
      </div>
      <span class="field-graph-mode">{{ editable ? '草稿可编辑' : '只读查看' }}</span>
    </div>

    <div class="field-graph-layout">
      <div class="field-tree">
        <div
          class="field-node field-node-root"
          :class="{ 'drop-enabled': editable, selected: isSelected('aggregate') }"
          @dragover.prevent
          @drop="onDropParent(aggregateKey, $event)"
          @click="selectField('aggregate')"
        >
          <span>聚合字段</span>
          <strong>{{ fieldTitle(aggregateField, '聚合字段') }}</strong>
          <small>{{ fieldMeta(aggregateField) }}</small>
        </div>

        <div class="field-branch">
          <div
            class="field-drop-zone"
            :class="{ 'drop-enabled': editable }"
            @dragover.prevent
            @drop="onDropParent(aggregateKey, $event)"
          >
            <span>拖到聚合字段下</span>
            <small>适合台区、线路、区域等汇总对象的子字段。</small>
          </div>
          <div
            v-for="item in aggregateChildren"
            :key="`aggregate-${item.index}`"
            class="field-chip"
            :class="{ selected: isSelected('custom', item.index) }"
            :draggable="editable"
            @dragstart="onFieldDragStart(item.index, $event)"
            @dragend="onDragEnd"
            @click="selectField('custom', item.index)"
          >
            <span>{{ item.role }}</span>
            <strong>{{ fieldTitle(item.field, `字段${item.index + 1}`) }}</strong>
          </div>
        </div>

        <div
          class="field-node field-node-primary"
          :class="{ 'drop-enabled': editable, selected: isSelected('primary') }"
          @dragover.prevent
          @drop="onDropParent(primaryKey, $event)"
          @click="selectField('primary')"
        >
          <span>主字段</span>
          <strong>{{ fieldTitle(primaryField, '主字段') }}</strong>
          <small>{{ fieldMeta(primaryField) }}</small>
        </div>

        <div class="field-branch primary-branch">
          <div
            class="field-drop-zone"
            :class="{ 'drop-enabled': editable }"
            @dragover.prevent
            @drop="onDropParent(primaryKey, $event)"
          >
            <span>拖到主字段下</span>
            <small>适合终端、电能表、用户等施工对象的子字段。</small>
          </div>
          <div
            v-for="item in primaryChildren"
            :key="`primary-${item.index}`"
            class="field-chip"
            :class="{ required: item.field.required, selected: isSelected('custom', item.index) }"
            :draggable="editable"
            @dragstart="onFieldDragStart(item.index, $event)"
            @dragend="onDragEnd"
            @click="selectField('custom', item.index)"
          >
            <span>{{ item.role }}</span>
            <strong>{{ fieldTitle(item.field, `字段${item.index + 1}`) }}</strong>
            <small>{{ fieldMeta(item.field) }}</small>
          </div>
        </div>
      </div>

      <aside class="field-graph-side">
        <div class="field-group-list">
          <section>
            <span>导入字段</span>
            <strong>{{ importFields.length }}</strong>
          </section>
          <section>
            <span>现场采集</span>
            <strong>{{ collectionFields.length }}</strong>
          </section>
          <section>
            <span>照片证据</span>
            <strong>{{ photoFields.length }}</strong>
          </section>
          <section>
            <span>平台必备</span>
            <strong>{{ platformRequiredFields?.length || 0 }}</strong>
          </section>
        </div>

        <div class="field-role-buckets">
          <div class="field-role-heading">
            <strong>字段角色分组</strong>
            <span>可拖拽子字段先看角色，再决定挂到哪一层。</span>
          </div>
          <button
            v-for="bucket in fieldRoleBuckets"
            :key="bucket.id"
            type="button"
            class="field-role-row"
            @click="selectBucketItem(bucket)"
          >
            <span>{{ bucket.label }}</span>
            <strong>{{ bucket.items.length }}</strong>
            <small>{{ bucket.helper }}</small>
          </button>
        </div>

        <div class="selected-field-panel">
          <span>字段详情</span>
          <template v-if="selectedFieldDetail">
            <strong>{{ fieldTitle(selectedFieldDetail, '字段') }}</strong>
            <p>{{ fieldMeta(selectedFieldDetail) }}</p>
            <p>
              层级归属：
              {{ selectedField?.type === 'custom' ? selectedParentLabel(selectedFieldDetail) : '项目根对象' }}
            </p>
            <div v-if="selectedFieldEditable" class="field-detail-form">
              <label>
                <span>字段名称</span>
                <ElInput
                  :model-value="selectedFieldDetail.label"
                  size="small"
                  @update:model-value="updateSelectedField({ label: String($event) })"
                />
              </label>
              <label>
                <span>字段编码</span>
                <ElInput
                  :model-value="selectedFieldDetail.key"
                  size="small"
                  @update:model-value="updateSelectedField({ key: String($event) })"
                />
              </label>
              <label>
                <span>字段来源</span>
                <ElSelect
                  :model-value="selectedFieldDetail.source"
                  size="small"
                  @change="updateSelectedField({ source: $event as FieldSource })"
                >
                  <ElOption
                    v-for="option in sourceOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label>
                <span>采集方式</span>
                <ElSelect
                  :model-value="selectedFieldDetail.captureMethod"
                  size="small"
                  @change="updateSelectedField({ captureMethod: $event as CaptureMethod })"
                >
                  <ElOption
                    v-for="option in captureMethodOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label>
                <span>字段格式</span>
                <ElSelect
                  :model-value="selectedFieldDetail.dataType"
                  size="small"
                  @change="updateSelectedField({ dataType: $event as DataType })"
                >
                  <ElOption
                    v-for="option in dataTypeOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </ElSelect>
              </label>
              <label class="field-detail-switch">
                <span>是否必填</span>
                <ElSwitch
                  :model-value="selectedFieldDetail.required"
                  @change="updateSelectedField({ required: Boolean($event) })"
                />
              </label>
            </div>
          </template>
          <template v-else>
            <strong>未选择字段</strong>
            <p>点击字段节点可查看来源、格式和采集要求。</p>
          </template>
        </div>
      </aside>
    </div>

    <div class="template-binding-preview">
      <div class="template-binding-heading">
        <strong>模板绑定预览</strong>
        <span>字段结构会决定下载模板和中途接入项目时需要补哪些数据。</span>
      </div>
      <div class="template-binding-grid">
        <section>
          <span>初始接入模板</span>
          <div>
            <ElTag v-for="field in initialTemplateFields" :key="field" size="small" effect="plain">
              {{ field }}
            </ElTag>
          </div>
          <small>用于项目开始前建单，只放能从清单导入的字段。</small>
          <div class="template-action-row">
            <ElButton size="small" type="primary" plain @click="emitTemplateAction('download', 'initial_work_orders')">
              下载初始接入模板
            </ElButton>
            <ElButton size="small" plain @click="emitTemplateAction('validate', 'initial_work_orders')">
              校验初始接入模板
            </ElButton>
          </div>
        </section>
        <section>
          <span>系统外已完成模板</span>
          <div>
            <ElTag v-for="field in externalCompletedTemplateFields" :key="field" size="small" type="warning" effect="plain">
              {{ field }}
            </ElTag>
          </div>
          <small>用于把运行到一半的项目接入平台，系统字段按上传时生成。</small>
          <div class="template-action-row">
            <ElButton size="small" type="warning" plain @click="emitTemplateAction('download', 'external_completed')">
              下载系统外已完成模板
            </ElButton>
            <ElButton size="small" plain @click="emitTemplateAction('validate', 'external_completed')">
              校验系统外已完成模板
            </ElButton>
          </div>
        </section>
        <section>
          <span>现场必采清单</span>
          <div>
            <ElTag v-for="field in siteRequiredFields" :key="field" size="small" type="success" effect="plain">
              {{ field }}
            </ElTag>
            <ElTag v-if="!siteRequiredFields.length" size="small" type="info" effect="plain">
              暂无必采字段
            </ElTag>
          </div>
          <small>现场端需要扫码、拍照或录入的关键数据。</small>
        </section>
      </div>
      <div class="site-checklist-panel">
        <div>
          <strong>施工端必采</strong>
          <span>现场采集入口会按这些字段提醒施工人员补齐证据。</span>
        </div>
        <div>
          <ElTag v-for="field in siteChecklistFields" :key="field" size="small" type="success" effect="plain">
            {{ field }}
          </ElTag>
        </div>
        <small>平台仍会保留安装人员、安装时间、在线时间、照片数量、旧设备回收等 KPI 字段。</small>
      </div>
      <span class="template-binding-hint">模板下载和校验使用当前字段结构；保存配置后会成为项目正式模板规则。</span>
    </div>
  </section>
</template>

<style scoped>
.field-graph-designer {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.field-graph-header,
.field-graph-layout,
.field-graph-side,
.field-group-list,
.selected-field-panel,
.template-binding-preview,
.template-binding-grid,
.field-tree,
.field-branch {
  min-width: 0;
}

.field-graph-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.field-graph-header > div,
.selected-field-panel,
.field-detail-form,
.field-detail-form label,
.template-binding-preview,
.template-binding-grid section,
.field-tree {
  display: grid;
  gap: 8px;
}

.field-graph-header strong,
.field-node strong,
.field-chip strong,
.selected-field-panel strong,
.template-binding-heading strong {
  color: var(--el-text-color-primary);
}

.field-graph-header span,
.field-node span,
.field-node small,
.field-chip span,
.field-chip small,
.selected-field-panel span,
.selected-field-panel p,
.field-group-list span,
.template-binding-heading span,
.template-binding-grid span,
.template-binding-grid small,
.template-binding-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-graph-mode {
  flex: 0 0 auto;
  padding: 4px 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 999px;
  background: #fff;
}

.field-graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(220px, 0.7fr);
  gap: 14px;
}

.field-tree {
  position: relative;
}

.field-node,
.field-chip,
.selected-field-panel,
.field-group-list section {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.field-node {
  display: grid;
  gap: 4px;
  padding: 12px;
}

.field-node-root {
  border-color: var(--el-color-primary-light-5);
}

.field-node-primary {
  margin-top: 12px;
  border-color: var(--el-color-success-light-5);
}

.drop-enabled {
  outline: 1px dashed transparent;
}

.drop-enabled:hover {
  outline-color: var(--el-color-primary);
}

.field-branch {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 0 0 18px;
}

.primary-branch {
  padding-bottom: 2px;
}

.field-chip {
  display: grid;
  gap: 3px;
  width: min(210px, 100%);
  padding: 10px;
  cursor: pointer;
}

.field-chip[draggable='true'] {
  cursor: grab;
}

.field-chip.required {
  border-color: var(--el-color-warning-light-5);
}

.field-graph-side {
  display: grid;
  align-content: start;
  gap: 12px;
}

.field-group-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.field-group-list section {
  display: grid;
  gap: 4px;
  padding: 10px;
}

.field-group-list strong {
  color: var(--el-text-color-primary);
  font-size: 18px;
}

.selected-field-panel {
  padding: 12px;
}

.field-node.selected,
.field-chip.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 2px var(--el-color-primary-light-8);
}

.selected-field-panel p {
  margin: 0;
}

.field-detail-form {
  padding-top: 4px;
}

.field-detail-form label > span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.field-detail-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-drop-zone {
  display: grid;
  align-content: center;
  gap: 3px;
  width: min(210px, 100%);
  min-height: 68px;
  padding: 10px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color);
}

.field-drop-zone span {
  color: var(--el-text-color-primary);
  font-size: 13px;
  font-weight: 700;
}

.field-drop-zone small,
.field-role-row small,
.field-role-heading span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.field-role-buckets {
  display: grid;
  gap: 8px;
}

.field-role-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.field-role-heading strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-role-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}

.field-role-row span,
.field-role-row strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.field-role-row small {
  grid-column: 1 / -1;
}

.template-binding-preview {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: #fff;
}

.template-binding-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.template-binding-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.template-binding-grid section {
  align-content: start;
  min-height: 116px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}

.template-binding-grid section > div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.template-action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.site-checklist-panel {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--el-color-success-light-5);
  border-radius: 8px;
  background: var(--el-color-success-light-9);
}

.site-checklist-panel > div:first-child {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.site-checklist-panel strong {
  color: var(--el-text-color-primary);
  font-size: 13px;
}

.site-checklist-panel span,
.site-checklist-panel small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.45;
}

.site-checklist-panel > div:last-of-type {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 760px) {
  .field-graph-layout,
  .field-group-list,
  .template-binding-grid {
    grid-template-columns: 1fr;
  }

  .field-chip {
    width: 100%;
  }
}
</style>
