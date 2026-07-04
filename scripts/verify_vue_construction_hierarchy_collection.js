const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const constructionSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ConstructionView.vue'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  [typesSource, 'relationRole?: ProjectFieldRelationRole', 'ConstructionPhotoSlot must carry relationRole for evidence grouping'],
  [constructionSource, 'type ConstructionFieldSection', 'construction view must define field sections'],
  [constructionSource, 'const constructionFieldSections', 'construction fields must be grouped into hierarchy sections'],
  [constructionSource, 'const constructionPhotoSections', 'photo slots must be grouped into evidence sections'],
  [constructionSource, "id: 'task-core'", 'construction sections must include task core section'],
  [constructionSource, "id: 'device-replacement'", 'construction sections must include device replacement section'],
  [constructionSource, "id: 'main-device-replacement'", 'construction sections must include main device replacement section'],
  [constructionSource, "id: 'accessory-confirmation'", 'construction sections must include accessory confirmation section'],
  [constructionSource, "id: 'conditional-accessory-fields'", 'construction sections must include conditional accessory collection section'],
  [constructionSource, "id: 'supporting-fields'", 'construction sections must include supporting fields section'],
  [constructionSource, 'function constructionFieldSectionId', 'construction fields need relation-role based section routing'],
  [constructionSource, 'function constructionFieldSectionsBase', 'construction field sections must share one base definition'],
  [constructionSource, 'const platformConstructionFieldSections', 'platform construction entry must preview grouped construction fields'],
  [constructionSource, 'function isConditionalAccessoryField', 'conditional accessory fields must be detected by requiredWhen'],
  [constructionSource, '主设备更换', 'construction UI must show main replacement device section'],
  [constructionSource, '附属设备确认', 'construction UI must show accessory confirmation section'],
  [constructionSource, '条件补采', 'construction UI must show conditional accessory section'],
  [constructionSource, "field.relationRole === 'replacement_device'", 'main replacement devices must route by relation role'],
  [constructionSource, "field.relationRole === 'accessory_replace_confirm'", 'accessory confirmation fields must route by relation role'],
  [constructionSource, "field.requiredWhen?.fieldKey", 'conditional accessory fields must keep trigger-field relation'],
  [constructionSource, 'function fieldRelationRoleLabel', 'construction fields need relation role labels'],
  [constructionSource, "replacement_device: '主设备 · 更换后'", 'construction relation labels must distinguish main replacement devices'],
  [constructionSource, "accessory_replace_confirm: '附属设备 · 是否更换'", 'construction relation labels must distinguish accessory confirmations'],
  [constructionSource, "accessory_new_device: '附属设备 · 新设备'", 'construction relation labels must distinguish accessory new devices'],
  [constructionSource, 'relationRole: field.relationRole', 'photo slots must preserve relationRole from field schema'],
  [constructionSource, 'v-for="section in activeConstructionFieldSections"', 'desktop form must render active hierarchical field sections'],
  [constructionSource, 'v-for="section in platformConstructionFieldSections"', 'platform entry must render grouped construction field preview'],
  [constructionSource, 'v-for="photoSection in activeConstructionPhotoSections"', 'desktop form must render active hierarchical photo sections'],
  [constructionSource, 'constructionConditionLabel(field)', 'field rows must show conditional collection hint'],
  [constructionSource, 'class="construction-section"', 'construction section styling must be present'],
  [constructionSource, 'class="construction-section-head"', 'construction section header must be present'],
  [constructionSource, 'class="construction-role-tag"', 'field relation role tag must be visible'],
  [constructionSource, 'class="construction-condition-hint"', 'conditional collection hint styling must be present'],
  [constructionSource, 'class="platform-schema-sections"', 'platform grouped schema preview styling must be present'],
  [constructionSource, 'class="platform-schema-section"', 'platform grouped schema section styling must be present'],
  [constructionSource, 'construction-section-main-device-replacement', 'main device replacement section styling must be present'],
  [constructionSource, 'construction-section-accessory-confirmation', 'accessory confirmation section styling must be present'],
  [constructionSource, 'construction-section-conditional-accessory-fields', 'conditional accessory section styling must be present'],
  [constructionSource, 'class="construction-photo-section"', 'photo evidence section styling must be present'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue construction hierarchy collection is wired.')
