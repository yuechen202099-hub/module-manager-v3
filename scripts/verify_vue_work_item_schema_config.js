const fs = require("fs");
const path = require("path");

const root = process.cwd();
const typesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "types.ts"), "utf8");
const servicesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "services.ts"), "utf8");
const workspaceSource = fs.readFileSync(path.join(root, "v2-web", "src", "stores", "workspace.ts"), "utf8");
const projectsViewSource = fs.readFileSync(path.join(root, "v2-web", "src", "views", "ProjectsView.vue"), "utf8");

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
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

console.log("[OK] Vue project creation configures work item schema fields.");
