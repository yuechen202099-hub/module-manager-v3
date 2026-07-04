const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const typesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'types.ts'), 'utf8')
const servicesSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'api', 'services.ts'), 'utf8')
const reviewSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'ReviewView.vue'), 'utf8')
const taskHallSource = fs.readFileSync(path.join(root, 'v2-web', 'src', 'views', 'TaskHallView.vue'), 'utf8')
const templatesSource = fs.readFileSync(path.join(root, 'v2-api', 'app', 'services', 'platform', 'templates.py'), 'utf8')

function fail(message) {
  console.error(`[FAIL] ${message}`)
  process.exit(1)
}

const requiredTokens = [
  [typesSource, 'relationRole?: ProjectFieldDefinition[\'relationRole\']', 'review types must carry relationRole'],
  [servicesSource, 'relation_role?: ProjectFieldDefinition[\'relationRole\']', 'backend review type must accept relation_role'],
  [servicesSource, 'required_when?: BackendProjectFieldRequiredWhen', 'backend review type must accept required_when'],
  [servicesSource, 'relationRole: mapRelationRole(field.relation_role)', 'field review mapper must keep relationRole'],
  [servicesSource, 'requiredWhen: mapRequiredWhen(field.required_when)', 'field review mapper must keep requiredWhen'],
  [servicesSource, 'relationRole: mapRelationRole(slot.relation_role)', 'photo review mapper must keep relationRole'],
  [servicesSource, 'requiredWhen: mapRequiredWhen(slot.required_when)', 'photo review mapper must keep requiredWhen'],
  [typesSource, 'requiredWhen?: ProjectFieldRequiredWhen', 'platform review field/photo types must carry requiredWhen'],
  [templatesSource, '"required_when": field.get("required_when") or None', 'backend field review payload must preserve required_when'],
  [templatesSource, '"required_when": slot.get("required_when") or None', 'backend photo review payload must preserve required_when'],
  [reviewSource, 'type ReviewHierarchySection', 'review view must define hierarchy sections'],
  [reviewSource, 'const reviewFieldSections', 'review fields must be grouped into hierarchy sections'],
  [reviewSource, 'const reviewPhotoSections', 'review photos must be grouped into evidence sections'],
  [reviewSource, 'function reviewFieldSectionId', 'review fields need relation-role section routing'],
  [reviewSource, 'function reviewFieldSectionsBase', 'review field sections must share one base definition'],
  [reviewSource, 'function isConditionalReviewField', 'conditional review fields must be detected by requiredWhen'],
  [reviewSource, 'function reviewWorkOrderFieldValues', 'review view must read per-work-order values before conditional filtering'],
  [reviewSource, 'function reviewConditionMatches', 'review view must evaluate requiredWhen against the selected work order'],
  [reviewSource, 'function isReviewConditionActiveForValues', 'review view must expose active/inactive conditional field logic'],
  [reviewSource, 'const activeReviewFieldReviews', 'review view must filter field reviews by the selected work order conditions'],
  [reviewSource, 'const activeReviewPhotoSlotReviews', 'review view must filter photo slots by the selected work order conditions'],
  [reviewSource, 'fieldReviews.filter((field) => isReviewConditionActiveForValues(field, values))', 'review view must hide inactive conditional accessory fields'],
  [reviewSource, 'photoSlotReviews.filter((slot) => isReviewConditionActiveForValues(slot, values))', 'review view must hide inactive conditional accessory photos'],
  [reviewSource, 'function reviewConditionLabel', 'review field rows must show conditional review hints'],
  [reviewSource, 'function reviewRelationRoleLabel', 'review fields need role labels'],
  [reviewSource, "id: 'task-core'", 'review sections must include task core section'],
  [reviewSource, "id: 'main-device-replacement'", 'review sections must include main device replacement section'],
  [reviewSource, "id: 'device-replacement'", 'review sections must include device replacement section'],
  [reviewSource, "id: 'accessory-confirmation'", 'review sections must include accessory confirmation section'],
  [reviewSource, "id: 'conditional-accessory-fields'", 'review sections must include conditional accessory section'],
  [reviewSource, "id: 'supporting-fields'", 'review sections must include supporting fields section'],
  [reviewSource, "field.relationRole === 'replacement_device'", 'main replacement devices must route by relation role'],
  [reviewSource, "field.relationRole === 'accessory_replace_confirm'", 'accessory confirmation fields must route by relation role'],
  [reviewSource, "field.requiredWhen?.fieldKey", 'conditional accessory review fields must keep trigger-field relation'],
  [reviewSource, "replacement_device: '主设备 · 更换后'", 'review relation labels must distinguish main replacement devices'],
  [reviewSource, "accessory_replace_confirm: '附属设备 · 是否更换'", 'review relation labels must distinguish accessory confirmations'],
  [reviewSource, "accessory_new_device: '附属设备 · 新设备'", 'review relation labels must distinguish accessory new devices'],
  [reviewSource, 'v-for="section in reviewFieldSections"', 'review detail must render field sections'],
  [reviewSource, 'v-for="photoSection in reviewPhotoSections"', 'review detail must render photo sections'],
  [reviewSource, 'reviewConditionLabel(field)', 'review detail must render conditional field hints'],
  [reviewSource, 'class="platform-review-section"', 'review section styling must be present'],
  [reviewSource, 'class="platform-review-role-tag"', 'review role tag must be visible'],
  [reviewSource, 'class="platform-review-condition-hint"', 'review conditional hint styling must be visible'],
  [reviewSource, 'platform-review-section-main-device-replacement', 'main replacement review section styling must be present'],
  [reviewSource, 'platform-review-section-accessory-confirmation', 'accessory confirmation review section styling must be present'],
  [reviewSource, 'platform-review-section-conditional-accessory-fields', 'conditional accessory review section styling must be present'],
  [taskHallSource, 'type PlatformReviewHierarchySection', 'task hall platform review must define hierarchy sections'],
  [taskHallSource, 'const platformReviewFieldSections', 'task hall platform review fields must be grouped into hierarchy sections'],
  [taskHallSource, 'const platformReviewPhotoSections', 'task hall platform review photos must be grouped into evidence sections'],
  [taskHallSource, 'function platformReviewFieldSectionsBase', 'task hall review sections must share one base definition'],
  [taskHallSource, 'function isConditionalPlatformReviewField', 'task hall conditional review fields must be detected by requiredWhen'],
  [taskHallSource, 'function platformReviewWorkOrderFieldValues', 'task hall must read per-work-order values before conditional filtering'],
  [taskHallSource, 'function platformReviewConditionMatches', 'task hall must evaluate requiredWhen against the selected work order'],
  [taskHallSource, 'function isPlatformReviewConditionActiveForValues', 'task hall must expose active/inactive conditional field logic'],
  [taskHallSource, 'const activePlatformReviewFieldReviews', 'task hall must filter field reviews by the selected work order conditions'],
  [taskHallSource, 'const activePlatformReviewPhotoSlotReviews', 'task hall must filter photo slots by the selected work order conditions'],
  [taskHallSource, 'fieldReviews.filter((field) => isPlatformReviewConditionActiveForValues(field, values))', 'task hall must hide inactive conditional accessory fields'],
  [taskHallSource, 'photoSlotReviews.filter((slot) => isPlatformReviewConditionActiveForValues(slot, values))', 'task hall must hide inactive conditional accessory photos'],
  [taskHallSource, 'function platformReviewConditionLabel', 'task hall review rows must show conditional review hints'],
  [taskHallSource, "field.relationRole === 'replacement_device'", 'task hall must route main replacement devices by relation role'],
  [taskHallSource, "field.relationRole === 'accessory_replace_confirm'", 'task hall must route accessory confirmations by relation role'],
  [taskHallSource, "field.requiredWhen?.fieldKey", 'task hall conditional accessory fields must keep trigger-field relation'],
  [taskHallSource, 'v-for="section in platformReviewFieldSections"', 'task hall must render field hierarchy sections'],
  [taskHallSource, 'v-for="photoSection in platformReviewPhotoSections"', 'task hall must render photo hierarchy sections'],
  [taskHallSource, 'platformReviewConditionLabel(field)', 'task hall must render conditional field hints'],
  [taskHallSource, 'platform-review-section', 'task hall hierarchy section styling must be present'],
  [taskHallSource, 'class="platform-review-role-tag"', 'task hall role tag must be visible'],
  [taskHallSource, 'class="platform-review-condition-hint"', 'task hall conditional hint styling must be visible'],
  [taskHallSource, 'platform-review-section-main-device-replacement', 'task hall main replacement section styling must be present'],
  [taskHallSource, 'platform-review-section-accessory-confirmation', 'task hall accessory confirmation section styling must be present'],
  [taskHallSource, 'platform-review-section-conditional-accessory-fields', 'task hall conditional accessory section styling must be present'],
]

for (const [source, token, message] of requiredTokens) {
  if (!source.includes(token)) fail(message)
}

console.log('[OK] Vue review hierarchy sections are wired.')
