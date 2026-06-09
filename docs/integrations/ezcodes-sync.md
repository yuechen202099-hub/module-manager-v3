# Ezcodes Backend Sync Historical Reference

This document is historical/debug reference only. Per the current project decision, V2.0 main workflow is spreadsheet import and must not depend on the Ezcodes backend API.

Do not use this integration as the primary product flow, release blocker, or acceptance baseline. If retained, it is compatibility support for investigation only.

## Source

- Site: `https://app.ezcodes.cn/web#/home/batch-scan-files`
- CloudBase env: `cloud1-8g4k4khc04701207`
- CloudBase Web API endpoint: `https://cloud1-8g4k4khc04701207.ap-shanghai.tcb-api.tencentcloudapi.com/web`
- File tree collection: `BGFiles`
- Barcode data collection: `BGBarcodes`
- Query action: `database.queryDocument`
- Photo URL action: `storage.batchGetDownloadUrl` for resolving URL references only.
- Root folder: `批量扫码 / 模块改造`
- Installer folders:
  - `罗爱民`
  - `龙翔`
  - `张海军`
  - `邓卓`

## Traversal

1. Query `BGFiles` with `parentId = "0"` and `name = "模块改造"`.
2. Query `BGFiles` under that folder for the four installer folders.
3. Recursively traverse each installer folder.
4. Treat `type == 0` as folder and non-zero rows as scan files.
5. Query `BGBarcodes` by `fileId` for each scan file.
6. Resolve `images` through CloudBase temporary file URLs for reference only. Do not download photos to local disk.

## Baseline Fields

These fields are project-critical and must stay stable:

- `terminal`: terminal identifier.
- `collector`: collector device.
- `meter_no`: submitted meter number when present in Ezcodes.
- `module_asset_no`: module asset number.
- `address`: address from Ezcodes scan data; V2.0 still treats the total catalog as the final installation-address source for review matching.
- `barcode`: original scanned long barcode.
- `meter_match_key`: derived from the barcode by removing the first 11 characters and the last character.
- `image_file_ids`: CloudBase photo object IDs.

## API

- `POST /projects/{project_id}/scan/ezcodes/preview`

This endpoint, if retained, builds a debug sync plan from backend data access. It does not click or scrape frontend UI and must not replace the spreadsheet-import workflow.

Any active implementation must treat backend CloudBase requests as optional compatibility/debug behavior. Credentials are accepted at request time and are not embedded in source code, tests, or documentation.
