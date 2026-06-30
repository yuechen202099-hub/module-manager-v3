const fs = require("fs");
const path = require("path");

const root = process.cwd();
const layoutSource = fs.readFileSync(path.join(root, "v2-web", "src", "layouts", "AppLayout.vue"), "utf8");

const checks = [
  {
    ok:
      layoutSource.includes("sidebarCollapsed") &&
      layoutSource.includes("module_manager_sidebar_collapsed") &&
      layoutSource.includes("toggleSidebar"),
    message: "App layout must persist and toggle a collapsible sidebar state.",
  },
  {
    ok:
      layoutSource.includes("side-shell") &&
      layoutSource.includes("class=\"side-rail\"") &&
      layoutSource.includes("class=\"side-nav\"") &&
      layoutSource.includes("class=\"side-toggle\""),
    message: "App layout must render a left side shell, rail, nav, and collapse control.",
  },
  {
    ok:
      layoutSource.includes("collapsed: sidebarCollapsed") &&
      layoutSource.includes(":aria-expanded=\"!sidebarCollapsed\"") &&
      layoutSource.includes(":title=\"sidebarCollapsed ? item.title : undefined\""),
    message: "Sidebar must expose collapsed state to CSS, accessibility, and tooltips.",
  },
  {
    ok:
      layoutSource.includes("class=\"shell-header\"") &&
      layoutSource.includes("class=\"shell-page-title\"") &&
      layoutSource.includes("class=\"side-actions\""),
    message: "Top navigation responsibilities must move into a lightweight content header and side actions.",
  },
  {
    ok:
      layoutSource.includes("@media (max-width: 900px)") &&
      layoutSource.includes("grid-template-columns: 1fr") &&
      layoutSource.includes(".side-shell:not(.embedded) .side-rail"),
    message: "Sidebar layout must include a mobile-friendly responsive mode.",
  },
  {
    ok: !layoutSource.includes("class=\"topbar\"") && !layoutSource.includes("class=\"top-nav\""),
    message: "Legacy topbar/top-nav markup must be removed from the app shell.",
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

console.log("[OK] Vue app layout uses a collapsible left sidebar navigation.");
