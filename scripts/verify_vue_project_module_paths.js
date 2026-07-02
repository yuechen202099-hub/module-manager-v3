const fs = require("fs");
const path = require("path");

const servicesPath = path.join(process.cwd(), "v2-web", "src", "api", "services.ts");
const staticAssetsPath = path.join(process.cwd(), "v2-api", "app", "static", "vue", "assets");
const source = fs.readFileSync(servicesPath, "utf8");
const staticSource = fs
  .readdirSync(staticAssetsPath)
  .filter((fileName) => fileName.endsWith(".js"))
  .map((fileName) => fs.readFileSync(path.join(staticAssetsPath, fileName), "utf8"))
  .join("\n");

const modules = ["progress", "delivery", "field", "review", "risks", "tasks"];
const registryDrivenChecks = [
  {
    ok: source.includes("registeredModules: Project['modules']"),
    message: "fetchProjectModuleSections must accept backend project module metadata.",
  },
  {
    ok: source.includes("fetchProjectModuleSections(project.id, project.modules)"),
    message: "Project list loading must pass backend module metadata into section loading.",
  },
  {
    ok:
      source.includes("modules.map(async (module)") &&
      source.includes("`/projects/${id}/modules/${encodeURIComponent(module.id)}`"),
    message: "Project module requests must be driven by the module registry list.",
  },
];
const hardcodedModuleCalls = modules
  .map((moduleId) => `/projects/\${id}/modules/${moduleId}`)
  .filter((expectedPath) => source.includes("api<BackendProject") && source.includes(expectedPath));
const legacy = modules
  .map((moduleId) => `/projects/\${id}/${moduleId}`)
  .filter((legacyPath) => source.includes(legacyPath));
const staticUnifiedMissing = staticSource.includes("/modules/") ? [] : ["/modules/"];
const registryFailures = registryDrivenChecks.filter((check) => !check.ok);

if (registryFailures.length || hardcodedModuleCalls.length || legacy.length || staticUnifiedMissing.length) {
  for (const failure of registryFailures) {
    console.error(failure.message);
  }
  if (hardcodedModuleCalls.length) {
    console.error(`Project module requests are still hardcoded: ${hardcodedModuleCalls.join(", ")}`);
  }
  if (legacy.length) {
    console.error(`Legacy project module paths still present: ${legacy.join(", ")}`);
  }
  if (staticUnifiedMissing.length) {
    console.error("Built Vue assets do not include the expected unified module requests.");
    if (staticUnifiedMissing.length) {
      console.error(`Missing built module fragments: ${staticUnifiedMissing.join(", ")}`);
    }
  }
  process.exit(1);
}

console.log("[OK] Vue project module requests use unified module paths.");
