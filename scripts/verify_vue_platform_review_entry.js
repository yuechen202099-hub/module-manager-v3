const fs = require("fs");
const path = require("path");

const root = process.cwd();
const typesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "types.ts"), "utf8");
const servicesSource = fs.readFileSync(path.join(root, "v2-web", "src", "api", "services.ts"), "utf8");
const taskHallSource = fs.readFileSync(path.join(root, "v2-web", "src", "views", "TaskHallView.vue"), "utf8");

const checks = [
  {
    ok:
      typesSource.includes("export type PlatformReviewWorkOrder") &&
      typesSource.includes("fieldReviews") &&
      typesSource.includes("photoSlotReviews"),
    message: "Frontend types must expose platform review work orders, field reviews, and photo slot reviews.",
  },
  {
    ok:
      servicesSource.includes("type BackendPlatformReviewWorkOrder") &&
      servicesSource.includes("function mapPlatformReviewWorkOrder") &&
      servicesSource.includes("export async function fetchProjectReviewWorkOrders") &&
      servicesSource.includes("/review/work-orders"),
    message: "Frontend services must fetch and map platform review work orders from the project review endpoint.",
  },
  {
    ok:
      taskHallSource.includes("fetchProjectReviewWorkOrders") &&
      taskHallSource.includes("platformReviewWorkOrders") &&
      taskHallSource.includes("selectPlatformReviewWorkOrder") &&
      taskHallSource.includes("平台接入审阅") &&
      taskHallSource.includes("平台工单字段") &&
      taskHallSource.includes("照片槽位"),
    message: "Task hall review workbench must render a platform review entry and selected work order details.",
  },
];

const failures = checks.filter((check) => !check.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(failure.message);
  }
  process.exit(1);
}

console.log("[OK] Vue task hall exposes platform review work orders.");
