const fs = require("fs");
const path = require("path");

const projectsViewPath = path.join(process.cwd(), "v2-web", "src", "views", "ProjectsView.vue");
const source = fs.readFileSync(projectsViewPath, "utf8");

const openRouteMatch = source.match(/function openRoute\(path: string, project: Project\) \{(?<body>[\s\S]*?)\n\}/);
const openRouteBody = openRouteMatch?.groups?.body || "";

const guardIndex = openRouteBody.indexOf("project.status === 'draft'");
const messageIndex = openRouteBody.indexOf("草稿项目模块待接入");
const returnIndex = openRouteBody.indexOf("return", messageIndex);
const routeIndex = openRouteBody.indexOf("router.push");
const selectIndex = openRouteBody.indexOf("workspace.selectProject");

const checks = [
  {
    ok: Boolean(openRouteMatch),
    message: "ProjectsView must keep module navigation centralized in openRoute().",
  },
  {
    ok: guardIndex >= 0,
    message: "openRoute() must guard draft projects before module navigation.",
  },
  {
    ok: messageIndex >= 0,
    message: "Draft project guard must show the 草稿项目模块待接入 message.",
  },
  {
    ok: messageIndex >= 0 && returnIndex > messageIndex,
    message: "Draft project guard must return before routing.",
  },
  {
    ok: guardIndex >= 0 && routeIndex > guardIndex,
    message: "Draft project guard must run before router.push().",
  },
  {
    ok: guardIndex >= 0 && selectIndex > guardIndex,
    message: "Draft project guard must run before selecting the draft as a module page project.",
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

console.log("[OK] Vue projects page guards draft project module entry.");
