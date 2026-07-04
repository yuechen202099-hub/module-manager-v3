const fs = require("fs");
const path = require("path");

const root = process.cwd();
const typesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "types.ts"), "utf8");
const servicesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "services.ts"), "utf8");
const workspaceSource = fs.readFileSync(path.join(root, "v2-web", "src", "stores", "workspace.ts"), "utf8");
const projectsViewSource = fs.readFileSync(path.join(root, "v2-web", "src", "views", "ProjectsView.vue"), "utf8");
const constructionViewSource = fs.readFileSync(path.join(root, "v2-web", "src", "views", "ConstructionView.vue"), "utf8");

const checks = [
  {
    ok:
      typesSource.includes("export type ProjectFieldDefinition") &&
      typesSource.includes("export type ProjectWorkItemSchema") &&
      typesSource.includes("platformRequiredFields: ProjectFieldDefinition[]") &&
      typesSource.includes("workItemSchema?: ProjectWorkItemSchema"),
    message: "Project types must expose configurable work item schema and platform required fields.",
  },
  {
    ok:
      servicesSource.includes("type BackendProjectFieldDefinition") &&
      servicesSource.includes("type BackendProjectWorkItemSchema") &&
      servicesSource.includes("function mapWorkItemSchema") &&
      servicesSource.includes("workItemSchema: mapWorkItemSchema(raw.work_item_schema") &&
      servicesSource.includes("work_item_schema: mapWorkItemSchemaForCreate(payload.workItemSchema)") &&
      servicesSource.includes("export async function updateProjectWorkItemSchema") &&
      servicesSource.includes("`/projects/${projectId}/work-item-schema`") &&
      servicesSource.includes("method: 'PATCH'"),
    message: "Project API service must map backend work item schema in both directions.",
  },
  {
    ok:
      projectsViewSource.includes("primaryField") &&
      projectsViewSource.includes("aggregateField") &&
      projectsViewSource.includes("customFields") &&
      projectsViewSource.includes("platformRequiredFields") &&
      projectsViewSource.includes("buildWorkItemSchemaPayload"),
    message: "Project creation dialog must collect primary, aggregate, custom, and platform-required fields.",
  },
  {
    ok:
      projectsViewSource.includes("安装人员") &&
      projectsViewSource.includes("安装时间") &&
      projectsViewSource.includes("在线时长") &&
      projectsViewSource.includes("照片数量") &&
      projectsViewSource.includes("扫码次数"),
    message: "Project creation dialog must show KPI and efficiency fields that the platform always keeps.",
  },
  {
    ok:
      projectsViewSource.includes("captureMethodOptions") &&
      projectsViewSource.includes("dataTypeOptions") &&
      projectsViewSource.includes("sourceOptions") &&
      projectsViewSource.includes("required") &&
      projectsViewSource.includes("parentKey"),
    message: "Project creation dialog must configure source, format, capture method, requirement, and parent field.",
  },
  {
    ok:
      projectsViewSource.includes("schemaDialogVisible") &&
      projectsViewSource.includes("openSchemaDialog") &&
      projectsViewSource.includes("submitSchemaUpdate") &&
      projectsViewSource.includes("字段配置") &&
      projectsViewSource.includes("保存配置") &&
      projectsViewSource.includes("workspace.updateProjectWorkItemSchema"),
    message: "Projects view must allow draft project work item schema to be reviewed and updated after creation.",
  },
  {
    ok:
      workspaceSource.includes("async updateProjectWorkItemSchema") &&
      workspaceSource.includes("services.updateProjectWorkItemSchema(projectId, workItemSchema)") &&
      workspaceSource.includes("this.projects.splice"),
    message: "Workspace store must update the local project list after schema changes.",
  },
  {
    ok:
      typesSource.includes("fieldValues?: Record<string, string>") &&
      servicesSource.includes("field_values") &&
      constructionViewSource.includes("constructionFields") &&
      constructionViewSource.includes("dynamicFields") &&
      constructionViewSource.includes("startDynamicScanner") &&
      constructionViewSource.includes("requiredConstructionFieldLabels") &&
      constructionViewSource.includes("field_values"),
    message: "Construction collection form must render, cache, scan, validate, and upload configured field values.",
  },
  {
    ok:
      servicesSource.includes("export async function downloadProjectTemplate") &&
      servicesSource.includes("`/projects/${projectId}/templates/${templateType}`") &&
      projectsViewSource.includes("downloadProjectTemplate") &&
      projectsViewSource.includes("templateDownloadOptions") &&
      projectsViewSource.includes("initial_work_orders") &&
      projectsViewSource.includes("external_completed") &&
      !projectsViewSource.includes("downloadTemplate(row, 'field_collection')") &&
      !typesSource.includes("'field_collection' | 'external_completed'"),
    message: "Projects view must expose only onboarding template downloads and hide field collection templates.",
  },
  {
    ok:
      projectsViewSource.includes("commonFieldPresets") &&
      projectsViewSource.includes("aggregateFieldPresetOptions") &&
      projectsViewSource.includes("terminalAggregateFieldPresetOptions") &&
      projectsViewSource.includes("setExclusiveAggregateField") &&
      projectsViewSource.includes("requiredFieldCollectionLabels") &&
      projectsViewSource.includes("createRequiredFieldCollectionLabels") &&
      projectsViewSource.includes("schemaRequiredFieldCollectionLabels") &&
      projectsViewSource.includes("siteRequiredFields: [...createRequiredFieldCollectionLabels.value, ...createRequiredPhotoLabels.value]") &&
      projectsViewSource.includes("applyFieldPreset(createForm.primaryField") &&
      projectsViewSource.includes("applyFieldPreset(schemaForm.primaryField") &&
      projectsViewSource.includes("setExclusiveAggregateField(createForm") &&
      projectsViewSource.includes("setExclusiveAggregateField(schemaForm") &&
      projectsViewSource.includes("showInConstructionPanel"),
    message: "Project primary fields must use common presets, aggregate fields must be exclusive, and fields must expose construction display control.",
  },
  {
    ok:
      projectsViewSource.includes("handleTemplateCommand") &&
      projectsViewSource.includes("handleModuleCommand") &&
      projectsViewSource.includes("<ElDropdown") &&
      projectsViewSource.includes("<ElDropdownItem"),
    message: "Projects view must consolidate row operations into dropdown actions.",
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

const defaultModuleBlocks = [
  /const createForm = reactive<CreateProjectForm>\([\s\S]*?defaultCustomField\('module_asset_no', '模块（需更换）', 'scan'\)[\s\S]*?required: true[\s\S]*?relationRole: 'accessory_new_device'/,
  /const schemaForm = reactive<WorkItemSchemaForm>\([\s\S]*?defaultCustomField\('module_asset_no', '模块（需更换）', 'scan'\)[\s\S]*?required: true[\s\S]*?relationRole: 'accessory_new_device'/,
  /function resetCreateForm\(\)[\s\S]*?defaultCustomField\('module_asset_no', '模块（需更换）', 'scan'\)[\s\S]*?required: true[\s\S]*?relationRole: 'accessory_new_device'/,
];

for (const pattern of defaultModuleBlocks) {
  if (!pattern.test(projectsViewSource)) {
    console.error("Default module replacement field must be required in create/schema draft forms.");
    process.exit(1);
  }
}

console.log("[OK] Vue project creation configures work item schema fields.");
