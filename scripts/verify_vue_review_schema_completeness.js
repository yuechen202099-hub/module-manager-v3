const fs = require("fs");
const path = require("path");

const root = process.cwd();
const typesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "types.ts"), "utf8");
const servicesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "services.ts"), "utf8");
const reviewViewSource = fs.readFileSync(path.join(root, "v2-web", "src", "views", "ReviewView.vue"), "utf8");

const checks = [
  {
    ok:
      typesSource.includes("fieldValues?: Record<string, string>") &&
      typesSource.includes("constructionSlot?: string") &&
      typesSource.includes("constructionSlotLabel?: string") &&
      servicesSource.includes("construction_field_values?: Record<string, unknown>") &&
      servicesSource.includes("field_values?: Record<string, unknown>") &&
      servicesSource.includes("construction_slot?: string") &&
      servicesSource.includes("construction_slot_label?: string") &&
      servicesSource.includes("fieldValues: mapStringRecord(") &&
      servicesSource.includes("raw.construction_field_values") &&
      servicesSource.includes("raw.field_values") &&
      servicesSource.includes("constructionSlot: raw.construction_slot") &&
      servicesSource.includes("constructionSlotLabel: raw.construction_slot_label"),
    message: "Review group API mapping must expose uploaded construction field values and photo slots to the frontend.",
  },
  {
    ok:
      reviewViewSource.includes("workspace.selectRouteProject(route.query.project_id)") &&
      reviewViewSource.includes("activeProjectSchema") &&
      reviewViewSource.includes("requiredReviewFields") &&
      reviewViewSource.includes("schemaPhotoRequirements") &&
      reviewViewSource.includes("reviewChecklist") &&
      reviewViewSource.includes("missingReviewItems") &&
      reviewViewSource.includes("canCompleteReview") &&
      reviewViewSource.includes("photo.constructionSlot") &&
      reviewViewSource.includes("photo.constructionSlotLabel") &&
      reviewViewSource.includes("reviewActions") &&
      reviewViewSource.includes("@click=\"save(status)\""),
    message: "Review view must build a project-schema-driven completeness checklist before completion.",
  },
  {
    ok:
      reviewViewSource.includes("通讯模块（需更换）") &&
      reviewViewSource.includes("新SIM卡") &&
      reviewViewSource.includes("改造前照片") &&
      reviewViewSource.includes("新旧模块照片") &&
      reviewViewSource.includes("改造后照片"),
    message: "Review view must provide visible schema checklist labels for terminal replacement review.",
  },
  {
    ok:
      reviewViewSource.includes(":disabled=\"status === 'complete' && !canCompleteReview\"") &&
      reviewViewSource.includes("missingReviewItems.value.join") &&
      reviewViewSource.includes("ElMessage.warning"),
    message: "Review completion must be blocked with a clear missing-item warning when required schema items are absent.",
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

console.log("[OK] Vue review view checks project schema completeness.");
