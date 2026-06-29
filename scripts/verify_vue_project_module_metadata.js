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
      typesSource.includes("export type ProjectModule") &&
      typesSource.includes("modules: ProjectModule[]") &&
      typesSource.includes("routePath: string"),
    message: "Project type must expose backend module metadata.",
  },
  {
    ok:
      servicesSource.includes("type BackendProjectModule") &&
      servicesSource.includes("function mapProjectModules") &&
      servicesSource.includes("routePath: String(module.route_path") &&
      servicesSource.includes("modules: mapProjectModules(raw.modules"),
    message: "Project mapper must preserve backend module metadata.",
  },
  {
    ok:
      projectsViewSource.includes("project.modules") &&
      projectsViewSource.includes("projectActionModules(row)") &&
      !projectsViewSource.includes("function projectModuleRoute") &&
      projectsViewSource.includes("module.routePath") &&
      projectsViewSource.includes("module.name"),
    message: "Projects view must render module actions from project.modules route metadata.",
  },
  {
    ok:
      typesSource.includes("export type ProjectCreatePayload") &&
      typesSource.includes("status: 'active' | 'archived' | 'draft'") &&
      servicesSource.includes("export async function createProject") &&
      servicesSource.includes("api<BackendPlatformProject>('/projects'") &&
      servicesSource.includes("method: 'POST'") &&
      workspaceSource.includes("async createProjectDraft") &&
      workspaceSource.includes("services.createProject(payload)") &&
      workspaceSource.includes("this.selectProject(project.id)"),
    message: "Frontend must expose project draft creation through API services and workspace store.",
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

console.log("[OK] Vue projects page consumes project module metadata.");
