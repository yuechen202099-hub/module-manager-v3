# Spreadsheet Import Design

The primary V2 workflow imports scan and photo metadata from spreadsheets. Backend Ezcodes sync is compatibility/debug code only and must not be the normal production path.

## Scope

The import service accepts spreadsheet rows after the file reader has converted them to dictionaries. The first implementation is intentionally template-tolerant because the final supplier template is not available yet.

Supported business fields:

| Canonical field | Required for matching | Example headers |
| --- | --- | --- |
| `terminal` | No | `终端`, `终端号`, `terminal` |
| `collector` | No | `采集器`, `采集器号`, `collector` |
| `meter_no` | Yes, unless `barcode` or `meter_match_key` exists | `表号`, `电表号`, `meter_no` |
| `module_asset_no` | No | `模块`, `模块号`, `module_asset_no` |
| `address` | No for scan import; never authoritative | `地址`, `安装地址`, `address` |
| `photo_urls` | No, but expected for photo review | `照片URL`, `图片URL`, `photo_urls`, numbered URL columns |
| `category_name` | No, but required for classified archive naming | `分类命名`, `分类`, `category_name` |
| `barcode` | Yes, unless `meter_no` or `meter_match_key` exists | `条形码`, `长条码`, `barcode` |
| `meter_match_key` | Yes, unless derived | `匹配键`, `meter_match_key` |

## Parsing Rules

- Header names are normalized by trimming whitespace, lowercasing, and removing internal whitespace.
- Chinese and English aliases map to canonical backend fields.
- A row is accepted only when the backend can produce `meter_match_key` from one of:
  - explicit `meter_match_key`;
  - long scanned `barcode`, using the rule "remove first 11 chars and last 1 char";
  - `meter_no`, using the total/stage catalog short-meter rule "remove first 2 chars".
- Photo URLs may be in one multi-value column or numbered columns such as `photo_url_1`, `photo_url_2`, `照片URL1`, `图片URL2`.
- Multi-value photo cells split on newline, comma, semicolon, Chinese comma, and Chinese semicolon.
- Duplicate URLs inside the same source row are suppressed while preserving order.
- Only `http://` and `https://` photo values are accepted as photo references. Other values are reported as warnings.
- The importer preserves URL strings only. It must not download photos, create local image files, or rewrite signed URL query strings.

## Address Rule

Imported scan rows may carry an `address` value for traceability, but it is not the installation-address source of truth.

Production group address must still come from `total_catalog_rows.installation_address`, copied into `material_groups.installation_address` after matching. Stage catalog rows, scan rows, spreadsheet rows, frontend edits, and review notes must not overwrite that snapshot.

## Classification Naming

`category_name` stores the operator or template-provided classification label. The review/export layer may use this value as the classified archive filename stem, with a suitable extension resolved from the final photo URL or stored photo metadata.

When the row has multiple photo URLs, each parsed `SpreadsheetPhotoRef` inherits the row's `category_name`. Future templates may add per-photo category columns; those should extend the parser without changing the canonical `SpreadsheetPhotoRef` shape.

## Backend Skeleton

Current code:

- `v2-api/app/services/spreadsheet_import.py`
- `v2-api/tests/test_spreadsheet_import.py`

The service currently provides pure parsing functions:

- `parse_csv_text(text) -> list[dict[str, str]]`
- `parse_spreadsheet_rows(rows) -> SpreadsheetImportResult`
- `normalize_spreadsheet_row(row, row_number) -> (SpreadsheetImportRecord, errors)`
- `infer_meter_match_key(meter_no=..., barcode=...) -> str`

The pure parser is intentionally separated from database writes so it can be reused by CSV, XLSX, and API-upload adapters once the final template and file-reading package are chosen.

## Future Persistence Flow

The route/service integration should use one import transaction per uploaded file:

1. Create an `import_jobs` row with source filename, uploader, status, and raw template metadata.
2. Parse spreadsheet rows into `SpreadsheetImportRecord` values.
3. Reject rows without a matchable meter identity and store row-level errors in import job details.
4. Match accepted rows by `meter_match_key` against total and stage catalog rows.
5. Create or update `material_groups` using the total catalog display meter number and address snapshot.
6. Insert one `photos` row per accepted URL, preserving the URL as a remote reference and assigning category metadata.
7. Recalculate group `photo_count`; keep groups with fewer than 4 valid photos as `incomplete`.
8. Record unmatched rows and warning details as import exceptions or import-job diagnostics.
9. Commit the job summary atomically with accepted row count, rejected row count, photo count, and warning count.

## Acceptance Tests

The parser tests cover:

- Chinese required-field aliases: terminal, collector, meter number, module, address, photo URL, category naming.
- Multiple URLs in one cell.
- Numbered URL columns.
- URL deduplication within one row.
- Rejection of rows without a matchable meter identity.
- Preservation of URL strings and warning-only handling for non-URL photo values.
