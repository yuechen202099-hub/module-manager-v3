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
const missing = modules
  .map((moduleId) => `/projects/\${id}/modules/${moduleId}`)
  .filter((expectedPath) => !source.includes(expectedPath));
const legacy = modules
  .map((moduleId) => `/projects/\${id}/${moduleId}`)
  .filter((legacyPath) => source.includes(legacyPath));
const staticUnifiedMissing = modules
  .map((moduleId) => `/modules/${moduleId}`)
  .filter((compiledModulePath) => !staticSource.includes(compiledModulePath));

if (missing.length || legacy.length || staticUnifiedMissing.length) {
  if (missing.length) {
    console.error(`Missing unified module paths: ${missing.join(", ")}`);
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
