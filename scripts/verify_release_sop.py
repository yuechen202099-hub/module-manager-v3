from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

RELEASE_INPUTS = (
    "scripts/verify_v3_2_0_role_routes.py",
    "scripts/verify_v3_2_0_data_center_ui.py",
    "scripts/verify_v3_2_0_dashboard_drilldown.py",
    "scripts/verify_v3_2_0_export_center_ui.py",
    "scripts/verify_v3_2_0_single_export_entry.py",
    "scripts/verify_v3_2_0_release.py",
    "scripts/verify_v3_2_1_installer_kpi_restore.py",
    "scripts/verify_v3_2_2_release.py",
    "scripts/verify_v3_2_3_release.py",
    "scripts/test_verify_v3_2_3_release.py",
    "scripts/verify_v3_2_4_release.py",
    "scripts/test_verify_v3_2_4_release.py",
    "scripts/verify_v3_2_5_release.py",
    "scripts/test_verify_v3_2_5_release.py",
    "scripts/verify_v3_2_6_release.py",
    "scripts/test_verify_v3_2_6_release.py",
    "scripts/verify_v3_2_7_release.py",
    "scripts/test_verify_v3_2_7_release.py",
    "scripts/verify_v3_2_8_release.py",
    "scripts/test_verify_v3_2_8_release.py",
    "scripts/verify_v3_2_10_release.py",
    "scripts/test_verify_v3_2_10_release.py",
    "scripts/verify_v3_2_11_release.py",
    "scripts/test_verify_v3_2_11_release.py",
    "scripts/verify_v3_2_12_release.py",
    "scripts/test_verify_v3_2_12_release.py",
    "scripts/verify_v3_2_13_release.py",
    "scripts/test_verify_v3_2_13_release.py",
    "scripts/verify_v3_2_14_release.py",
    "scripts/test_verify_v3_2_14_release.py",
    "scripts/verify_v3_2_15_release.py",
    "scripts/test_verify_v3_2_15_release.py",
    "scripts/verify_v3_2_16_release.py",
    "scripts/test_verify_v3_2_16_release.py",
    "scripts/verify_v3_2_17_release.py",
    "scripts/test_verify_v3_2_17_release.py",
    "scripts/verify_v3_2_18_release.py",
    "scripts/test_verify_v3_2_18_release.py",
    "scripts/verify_v3_2_19_release.py",
    "scripts/test_verify_v3_2_19_release.py",
    "scripts/patch_export_retirement_nginx.py",
    "scripts/test_patch_export_retirement_nginx.py",
    "scripts/oss_local_export.py",
    "scripts/test_oss_local_export.py",
    "v2-api/alembic/versions/0013_data_center_query_indexes.py",
    "v2-api/alembic/versions/0014_export_center_jobs.py",
    "v2-api/alembic/versions/0015_collector_transfer_workbench.py",
    "v2-api/alembic/versions/0016_project_scoped_collector_inventory.py",
    "v2-api/app/api/routes/collector_transfer.py",
    "v2-api/app/domain/collector_transfer.py",
    "v2-api/app/domain/terminal_review.py",
    "v2-api/app/services/collector_transfer.py",
    "v2-api/tests/test_collector_transfer_api.py",
    "v2-api/tests/test_collector_transfer_domain.py",
    "v2-api/tests/test_collector_transfer_postgres_integration.py",
    "v2-api/tests/test_collector_transfer_service.py",
    "v2-api/tests/test_collector_transfer_scale.py",
    "v2-api/tests/test_data_center_review.py",
    "v2-api/tests/test_data_center.py",
    "v2-api/tests/test_local_simulation.py",
    "v2-api/tests/test_terminal_review_domain.py",
    "v2-api/app/api/routes/groups.py",
    "v2-api/app/api/routes/exports.py",
    "v2-api/app/schemas/data_center.py",
    "v2-api/app/schemas/export_center.py",
    "v2-api/app/services/data_center.py",
    "v2-api/app/services/export_center.py",
    "v2-api/app/services/photo_storage.py",
    "v2-api/tests/test_photo_storage.py",
    "v2-api/app/services/export_retirement.py",
    "v2-api/app/services/external_photo_oss_migration.py",
    "v2-api/scripts/build_oss_export_manifest.py",
    "v2-api/scripts/migrate_external_photos_to_oss.py",
    "v2-api/tests/test_migrate_external_photos_to_oss.py",
    "v2-web/src/components/data-center/DataCenterFilters.vue",
    "v2-web/src/components/data-center/DataCenterReviewDialog.vue",
    "v2-web/src/components/data-center/DataCenterGroupReviewPanel.vue",
    "v2-web/src/components/PhotoLightbox.vue",
    "v2-web/src/composables/useDataCenterQuery.ts",
    "v2-web/src/utils/dataCenterDrilldown.ts",
    "v2-web/src/components/InstallerKpiDialog.vue",
    "v2-web/src/utils/installerKpi.ts",
    "v2-web/src/api/services.ts",
    "v2-web/src/api/types.ts",
    "v2-web/src/features/collectorTransfer/state.ts",
    "v2-web/src/layouts/AppLayout.vue",
    "v2-web/src/router/index.ts",
    "v2-web/src/router/staticPages.ts",
    "v2-web/src/views/CollectorInventoryView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryView.spec.ts",
    "v2-web/src/views/ReviewRephotoWorkbenchView.vue",
    "v2-web/src/views/ProjectBoardView.vue",
    "v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts",
    "v2-web/src/views/__tests__/ReviewRephotoWorkbenchView.spec.ts",
    "v2-web/src/components/__tests__/ProjectBoardView.spec.ts",
    "v2-web/src/views/__tests__/AppLayout.spec.ts",
    "v2-web/src/views/__tests__/LoginView.spec.ts",
    "v2-web/tests/collector-transfer-state.test.ts",
    "ops/releases/V3.2.0.md",
    "ops/releases/V3.2.1.md",
    "ops/releases/V3.2.2.md",
    "ops/releases/V3.2.3.md",
    "ops/releases/V3.2.4.md",
    "ops/releases/V3.2.5.md",
    "ops/releases/V3.2.6.md",
    "ops/releases/V3.2.7.md",
    "ops/releases/V3.2.8.md",
    "ops/releases/V3.2.9.md",
    "ops/releases/V3.2.10.md",
    "ops/releases/V3.2.11.md",
    "ops/releases/V3.2.12.md",
    "ops/releases/V3.2.13.md",
    "ops/releases/V3.2.14.md",
    "ops/releases/V3.2.15.md",
    "ops/releases/V3.2.16.md",
    "ops/releases/V3.2.17.md",
    "ops/releases/V3.2.18.md",
    "ops/releases/V3.2.19.md",
)

REQUIRED_FILES = [
    "docs/sop/README.md",
    "docs/sop/01-demand-intake-and-priority.md",
    "docs/sop/02-production-branch-versioning.md",
    "docs/sop/03-change-analysis-and-tdd.md",
    "docs/sop/04-subagent-review-template.md",
    "docs/sop/05-release-package-and-hash.md",
    "docs/sop/06-production-deploy-runbook.md",
    "docs/sop/07-rollback-and-incident-review.md",
    "docs/sop/08-business-acceptance-templates.md",
    "docs/sop/09-export-retirement-and-oss-local-export.md",
    "ops/releases/README.md",
    "ops/releases/V3.0.84.md",
    "ops/releases/V3.1.1.md",
    "ops/releases/V3.1.0.md",
    "ops/releases/V3.0.83.md",
    "ops/releases/V3.0.82.md",
    "ops/releases/V3.0.81.md",
    "ops/releases/V3.0.79.md",
    "ops/releases/V3.0.80.md",
    "ops/releases/V3.0.78.md",
    "ops/releases/V3.0.77.md",
    "ops/releases/V3.0.76.md",
    "ops/releases/V3.0.75.md",
    "ops/releases/V3.0.74.md",
    "ops/releases/V3.0.73.md",
    "ops/releases/V3.0.72.md",
    "ops/releases/V3.0.71.md",
    "ops/releases/V3.0.70.md",
    "ops/releases/V3.0.69.md",
    "ops/releases/V3.0.68.md",
    "ops/releases/V3.0.67.md",
    "ops/releases/V3.0.66.md",
    "ops/releases/V3.0.65.md",
    "ops/releases/V3.0.64.md",
    "ops/releases/V3.0.63.md",
    "ops/releases/V3.0.62.md",
    "ops/releases/V3.0.61.md",
    "ops/releases/V3.0.60.md",
    "ops/releases/V3.0.59.md",
    "ops/releases/V3.0.58.md",
    "ops/releases/V3.0.56.md",
    "ops/releases/V3.0.55.md",
    "ops/releases/V3.0.54.md",
    "ops/releases/V3.0.53.md",
    "ops/releases/V3.0.52.md",
    "ops/releases/V3.0.51.md",
    "ops/releases/V3.0.50.md",
    "ops/releases/V3.0.49.md",
    "ops/releases/V3.0.48.md",
    "ops/releases/V3.0.47.md",
    "ops/releases/V3.0.46.md",
    "ops/releases/V3.0.45.md",
    "ops/releases/V3.0.44.md",
    "ops/releases/V3.0.42.md",
    "ops/releases/V3.0.41.md",
    "ops/releases/V3.0.40.md",
    "ops/releases/V3.0.39.md",
    "ops/releases/V3.0.38.md",
    "ops/releases/V3.0.37.md",
    "ops/incidents/P0-template.md",
    "scripts/production_backup.sh",
    "scripts/cleanup_old_releases.sh",
    "scripts/production_health_check.py",
    "scripts/verify_release_retention_policy.py",
    "scripts/verify_project_board_data_center_photos.js",
    "scripts/verify_project_board_unmatched_review.js",
    "scripts/verify_dialog_information_integration.js",
    "v2-web/src/version.json",
    *RELEASE_INPUTS,
]

RELEASE_TABLE_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<evidence>[^|]+?)\s*\|\s*(?P<value>[^|]*)\s*\|\s*$", re.MULTILINE
)
DEPLOYED_BASELINE_MARKER = "当前已部署生产版本"
RELEASE_CANDIDATE_MARKER = "当前发布候选版本"
ENGLISH_DEPLOYED_BASELINE_MARKER = "Deployed production baseline"
ENGLISH_RELEASE_CANDIDATE_MARKER = "Release candidate"
ENGLISH_RELEASE_CANDIDATE_BRANCH_MARKER = "Release-candidate maintenance branch"
RELEASE_CANDIDATE_BRANCH_MARKER = "\u5f53\u524d\u5019\u9009\u7ef4\u62a4\u5206\u652f"
STATUS_FIELD_LABELS = {
    "Status": "Status",
    "Deployment state": "Deployment state",
    "Deployment status": "Deployment status",
    "Release status": "Release status",
    "Release": "Release",
    "Deployment": "Deployment",
    "状态": "状态",
    "部署状态": "部署状态",
    "发布状态": "发布状态",
    "上线状态": "上线状态",
    "部署": "部署",
    "发布": "发布",
    "上线": "上线",
}
EVIDENCE_FIELD_LABELS = {
    "SHA256": "SHA256",
    "Backup directory": "Backup directory",
    "Release directory": "Release directory",
    "Public health check": "Public health check",
}
VERSION_TOKEN_PATTERN = re.compile(r"\bV\d+\.\d+\.\d+\b", re.IGNORECASE)
SEMANTIC_VERSION_PATTERN = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
MANIFEST_VERSION_LINE_PATTERN = re.compile(r"^- Version:\s*(?P<version>.*?)\s*$", re.MULTILINE)
AFFIRMATIVE_STATE_ADVERB_PATTERN = (
    r"(?!(?:not|never|possibly|probably|potentially|allegedly|reportedly|supposedly)\b)"
    r"(?:[a-z]+ly|already|now|long)"
)
MODAL_PREFIX_ADVERB_PATTERN = r"(?:[a-z]+ly|well|long|already|now|yet|ever|even)"
DEPLOYMENT_CLAIM_PATTERN = re.compile(
    r"\b(?:deployed|shipped|released)\b"
    r"|\b(?:go|gone|went|be|been|is|are|was|were)\s+"
    r"(?:(?:already|currently|now|presently|successfully|fully)\s+)*live\b"
    r"(?:\s+(?:in|on)\s+production\b)?"
    r"|\b(?:(?:is|are|was|were)|(?:has|have|had)\s+"
    rf"(?:(?:{AFFIRMATIVE_STATE_ADVERB_PATTERN})\s+)*been)\s+"
    rf"(?:(?:{AFFIRMATIVE_STATE_ADVERB_PATTERN})\s+)*"
    r"(?!not\b)(?:running"
    rf"(?:\s+(?:{AFFIRMATIVE_STATE_ADVERB_PATTERN}))*\s+)?in\s+production\b"
    r"|(?:已|已经|现已)(?:成功|正式)?(?:部署|发布|上线)(?:到|至|在)?生产(?:环境)?"
    r"|已部署|已发布|已上线|(?:生产(?:环境)?\s*)?(?:部署|发布|上线)已完成"
    r"|已(?:在)?生产(?:环境)?(?:正式)?(?:部署|发布|上线|生效)"
    r"|已完成(?:生产(?:环境)?)?(?:部署|发布|上线)"
    r"|现已(?:在)?生产(?:环境)?(?:正式)?生效",
    re.IGNORECASE,
)
NEGATED_ENGLISH_CLAIM_PATTERN = re.compile(
    r"\b(?:not|never)\s+(?:(?:yet|currently|ever|actually|successfully|fully)\s+)*"
    r"(?:(?:been|be|get)\s+)?(?:deployed|shipped|released)\b"
    r"|\b(?:not|never)\s+(?:(?:yet|currently|ever|actually|successfully|fully)\s+)*"
    r"(?:go|gone|be)?\s*live(?:\s+(?:in|on))?\s+production\b",
    re.IGNORECASE,
)
NEGATED_CHINESE_CLAIM_PATTERN = re.compile(
    r"(?:未|尚未)(?:在)?(?:生产(?:环境)?)?(?:正式)?(?:部署|发布|上线|生效)"
    r"|(?:未|尚未)完成(?:生产(?:环境)?)?(?:部署|发布|上线)"
)
CONDITIONAL_ENGLISH_CLAIM_PATTERN = re.compile(
    r"\b(?:can|could|may|might|should|must|ought\s+to|if|unless)\b",
    re.IGNORECASE,
)
CONDITIONAL_CHINESE_CLAIM_PATTERN = re.compile(
    r"(?:可以|可能|或许|也许|应当|应该|必须|须|需要|若|如果|假如|倘若|除非|否则|仅当|只要|待)"
    r"|可(?=[^,，;；。.!?！？\n]{0,24}(?:部署|发布|上线|生效))"
)
CONDITIONAL_SCOPE_ENGLISH_CLAIM_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:if|unless)\b",
    re.IGNORECASE,
)
CONDITIONAL_SCOPE_CHINESE_CLAIM_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:若|如果|假如|倘若|除非|否则|仅当|只要|待)"
)
PENDING_STATUS_PATTERN = re.compile(r"\bpending\b|待(?:部署|发布|上线|验证)|未(?:部署|发布|上线)", re.IGNORECASE)
FUTURE_DEPLOYMENT_PATTERN = re.compile(
    r"\b(?:will|would|shall|should|must|ought\s+to|going\s+to|to\s+be|scheduled\s+to|planned\s+to)\s+"
    r"(?:(?:be\s+)?(?:deployed|shipped|released)|go\s+live(?:\s+(?:in|on))?\s+production)\b"
    r"|\b(?:before|after|until|once)\b[^,;.!?\n]{0,120}\b(?:deployed|shipped|released)\b"
    r"|(?:将|计划|拟|应当|应该|应|必须|须|需要|需)(?:于[^,，;；。.!?！？\n]{0,20})?"
    r"(?:在生产(?:环境)?)?(?:部署|发布|上线|生效)",
    re.IGNORECASE,
)
CLAUSE_BOUNDARY_PATTERN = re.compile(
    r"([,，;；。.!?！？\n]+|\b(?:and|but|however|then|while|yet)\b|(?:并且|并于|并|但是|然而|但|却|然后)|于(?=(?:今日|现已|生产)))",
    re.IGNORECASE,
)
CLAUSE_SCOPE_RESET_PATTERN = re.compile(r"[。.!?！？\n]|\b(?:but|however|yet)\b|(?:但是|然而|但|却)", re.IGNORECASE)
NEGATED_DEPLOYMENT_PREFIX_PATTERN = re.compile(
    r"\b(?:not|never)\s+"
    r"(?:(?:yet|currently|ever|actually|successfully|fully|even|eventually|possibly|already|now)\s+)*"
    r"(?:(?:have|has|had|been|be|being|get|got|go)\s+)*$",
    re.IGNORECASE,
)
MODAL_DEPLOYMENT_PREFIX_PATTERN = re.compile(
    r"(?:\b(?:can|could|may|might|should|must|would|will|shall)\s+"
    r"(?:not\s+)?"
    rf"(?:(?:{MODAL_PREFIX_ADVERB_PATTERN})\s+)*"
    r"(?:(?:have|has|had|been|be|being|get|got|go|gone)\s+)*"
    r"|\b(?:going|scheduled|planned)\s+to\s+(?:be\s+)?"
    r"|\bto\s+be\s+)$",
    re.IGNORECASE,
)
CHINESE_MODAL_DEPLOYMENT_PREFIX_PATTERN = re.compile(
    r"(?:可以|可能|或许|也许|应当|应该|必须|须|需要|需|将|计划|拟|可)"
    r"(?:于[^,，;；。.!?！？\n]{0,20})?(?:在生产(?:环境)?)?$"
)
CONDITIONAL_DEPLOYMENT_PREFIX_PATTERN = re.compile(
    r"\b(?:only\s+after|before|until|once)\b[^,;.!?\n]{0,80}$"
    r"|(?:若|如果|假如|倘若|除非|仅当|只要)[^,，;；。.!?！？\n]{0,40}$",
    re.IGNORECASE,
)
POST_DEPLOYMENT_CONDITION_PATTERN = re.compile(
    r"^\s*(?:(?:to|in|on)\s+production\b\s*)?(?:if|unless)\b"
    r"|^\s*(?:(?:到|至|在)?生产(?:环境)?\s*)?(?:若|如果|假如|倘若|除非|仅当|只要)",
    re.IGNORECASE,
)
NONASSERTIVE_DEPLOYMENT_PREFIX_PATTERN = re.compile(
    r"\b(?:there\s+(?:is|was)\s+)?no\s+(?:credible\s+)?evidence\s+(?:that|to\s+show)\b.*$"
    r"|\b(?:we|i|they)\s+(?:can\s+not|could\s+not|must\s+not|should\s+not|do\s+not)\s+"
    r"(?:claim|say|conclude|state)\s+(?:that\s+)?\b.*$"
    r"|\bit\s+is\s+not\s+true\s+that\b.*$"
    r"|(?:目前|当前)?没有(?:任何)?证据(?:表明|证明|显示).*$"
    r"|(?:我们|本记录)?(?:不能|无法|不可|不应)(?:声称|断言|认定|说明).*$",
    re.IGNORECASE,
)
MARKDOWN_FENCE_PATTERN = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
EXAMPLE_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:example|for\s+example|sample|e\.g\.|示例|例如|举例)\s*[:：,，]",
    re.IGNORECASE,
)
RELEASE_RECORD_VERSION_PATTERN = re.compile(r"^#\s*(?P<version>V\d+\.\d+\.\d+)\b", re.MULTILINE)
PLACEHOLDER_PATTERN = re.compile(r"\b(?:tbd|todo|pending|n/?a|unknown)\b|待补充|待验证|(?:^|\s)-(?:$|\s)", re.IGNORECASE)
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
BACKUP_DIRECTORY_PATTERN = re.compile(r"/opt/module-manager-v2/backups/[A-Za-z0-9._-]+")
RELEASE_DIRECTORY_PATTERN = re.compile(r"/opt/module-manager-v2/releases/[A-Za-z0-9._-]+")
PUBLIC_HEALTH_URL_PATTERN = re.compile(r"https://(?:www\.)?sgcc\.online/health(?:[/?#\s]|$)", re.IGNORECASE)
SUCCESS_STATUS_PATTERN = re.compile(r"\b(?:passed|pass|success|successful|healthy|ok)\b|通过|成功", re.IGNORECASE)
DEPLOYED_LIFECYCLE_STATUS = "reviewed, packaged, deployed, and verified in production"
ACCEPTANCE_OR_ATTESTATION_TOPIC_PATTERN = re.compile(
    r"\b(?:acceptance|accepted|attestation|attested)\b|(?:验收|认证|签署)",
    re.IGNORECASE,
)
EXPLICITLY_UNACCEPTED_OR_UNATTESTED_PATTERN = re.compile(
    r"\b(?:no|not|never|without|pending|must\s+not|has\s+not|was\s+not|is\s+not)\b"
    r"[^,;.!?\n]{0,48}\b(?:v\d+\.\d+\.\d+\s+)?"
    r"(?:production\s+)?(?:acceptance|attestation|accepted|attested)\b"
    r"|\b(?:production\s+)?(?:acceptance|attestation)\b[^,;.!?\n]{0,24}"
    r"\b(?:not|never|incomplete|pending)\b"
    r"|(?:未|无|不|尚未|不得|不能|待)[^,，;；。.!?！？\n]{0,24}(?:验收|认证|签署|证明)"
    r"|(?:验收|认证|签署|证明)[^,，;；。.!?！？\n]{0,16}(?:未|不|尚未|待)",
    re.IGNORECASE,
)
ACCEPTANCE_INCOMPLETE_BEFORE_COMPLETION_PATTERN = re.compile(
    r"\bbefore\b[^,;.!?\n]{0,64}\bacceptance\b\s+completed\b",
    re.IGNORECASE,
)


def fail(message: str) -> None:
    raise AssertionError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def normalize_claim_text(value: str) -> str:
    text = normalize_text(value)
    text = text.replace("can't", "can not")
    text = re.sub(
        r"\b(is|are|was|were|has|have|had|do|does|did|can|could|would|should|must)n't\b",
        r"\1 not",
        text,
    )
    return text.replace("won't", "will not").replace("cannot", "can not")


def is_label_character(char: str) -> bool:
    return char.isalnum() or "\u3400" <= char <= "\u9fff"


def strip_optional_markdown_bullet(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lstrip()
    if normalized[:1] in {"-", "*", "+"}:
        return normalized[1:].lstrip()
    return normalized


def strip_decorative_prefix(value: str) -> str:
    while value and not is_label_character(value[0]) and value[0] not in {"/", "-"}:
        value = value[1:]
    return value


def compact_label(value: str) -> str:
    return "".join(char.casefold() for char in unicodedata.normalize("NFKC", value) if is_label_character(char))


def label_suffix(value: str, label: str) -> str | None:
    text = strip_decorative_prefix(strip_optional_markdown_bullet(value))
    expected = compact_label(label)
    index = 0
    for char in expected:
        while index < len(text) and not is_label_character(text[index]):
            index += 1
        if index >= len(text) or text[index].casefold() != char:
            return None
        index += 1
    return text[index:]


def parse_known_label_value(value: str, labels: dict[str, str]) -> tuple[str, str] | None:
    for label in sorted(labels, key=lambda item: len(compact_label(item)), reverse=True):
        suffix = label_suffix(value, label)
        if suffix is None or not suffix or is_label_character(suffix[0]):
            continue
        parsed_value = strip_decorative_prefix(suffix).strip()
        if parsed_value:
            return labels[label], parsed_value
    return None


def parse_known_label(value: str, labels: dict[str, str]) -> str | None:
    for label in sorted(labels, key=lambda item: len(compact_label(item)), reverse=True):
        suffix = label_suffix(value, label)
        if suffix is not None and not strip_decorative_prefix(suffix).strip():
            return labels[label]
    return None


def parse_marker_version(value: str) -> str | None:
    match = re.match(r"(?P<version>V\d+\.\d+\.\d+)(?P<trailing>.*)$", unicodedata.normalize("NFKC", value))
    if match is None or strip_decorative_prefix(match.group("trailing")).strip():
        return None
    return match.group("version")


def parse_maintenance_branch(value: str) -> str | None:
    normalized = strip_decorative_prefix(unicodedata.normalize("NFKC", value))
    match = re.match(
        r"(?P<branch>production/V3/(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)))(?P<trailing>.*)$",
        normalized,
    )
    if match is None or strip_decorative_prefix(match.group("trailing")).strip():
        return None
    return match.group("branch")


def parse_agents_marker(agents: str, marker: str, marker_name: str) -> str:
    matches = []
    for line in agents.splitlines():
        parsed = parse_known_label_value(line, {marker: marker})
        if parsed is None:
            continue
        _, value = parsed
        version = parse_marker_version(value)
        if version is not None:
            matches.append(version)
    if len(matches) != 1:
        fail(f"AGENTS.md must define exactly one {marker_name} marker")
    return matches[0]


def parse_agents_maintenance_branch(agents: str, marker: str, marker_name: str) -> str:
    matches = []
    for line in agents.splitlines():
        parsed = parse_known_label_value(line, {marker: marker})
        if parsed is None:
            continue
        _, value = parsed
        branch = parse_maintenance_branch(value)
        if branch is not None:
            matches.append(branch)
    if len(matches) != 1:
        fail(f"AGENTS.md must define exactly one {marker_name} marker")
    return matches[0]


def deployed_production_baseline(agents: str) -> str:
    english = parse_agents_marker(
        agents,
        ENGLISH_DEPLOYED_BASELINE_MARKER,
        "English deployed production baseline",
    )
    chinese = parse_agents_marker(agents, DEPLOYED_BASELINE_MARKER, "deployed production baseline")
    if english != chinese:
        fail("AGENTS.md English and Chinese deployed production baseline markers must agree")
    return chinese


def release_candidate_maintenance_branch(agents: str) -> str:
    english = parse_agents_maintenance_branch(
        agents,
        ENGLISH_RELEASE_CANDIDATE_BRANCH_MARKER,
        "English release-candidate maintenance branch",
    )
    chinese = parse_agents_maintenance_branch(
        agents,
        RELEASE_CANDIDATE_BRANCH_MARKER,
        "release-candidate maintenance branch",
    )
    if english != chinese:
        fail("AGENTS.md English and Chinese release-candidate maintenance branch markers must agree")
    return chinese


def release_candidate(agents: str) -> str:
    english = parse_agents_marker(
        agents,
        ENGLISH_RELEASE_CANDIDATE_MARKER,
        "English release candidate",
    )
    chinese = parse_agents_marker(agents, RELEASE_CANDIDATE_MARKER, "release candidate")
    if english != chinese:
        fail("AGENTS.md English and Chinese release candidate markers must agree")
    maintenance_branch = release_candidate_maintenance_branch(agents)
    expected_branch = f"production/V3/{chinese.removeprefix('V')}"
    if maintenance_branch != expected_branch:
        fail("AGENTS.md release-candidate maintenance branch must match the release candidate")
    return chinese


def release_record_status(record: str) -> str:
    claims = []
    all_labels = {**STATUS_FIELD_LABELS, **EVIDENCE_FIELD_LABELS}
    for line in record.splitlines():
        if line.lstrip().startswith("|"):
            continue
        parsed = parse_known_label_value(line, all_labels)
        if parsed is not None and parsed[0] in STATUS_FIELD_LABELS.values():
            claims.append(parsed[1])
    for match in RELEASE_TABLE_ROW_PATTERN.finditer(record):
        field = parse_known_label(match.group("evidence"), STATUS_FIELD_LABELS)
        if field is not None:
            claims.append(match.group("value").strip())
    if not claims:
        fail("release record must include a status-like field")
    if len(claims) != 1:
        fail("release record must not contain multiple status-like claims")
    return claims[0]


def release_record_evidence(record: str) -> dict[str, list[str]]:
    evidence = {field: [] for field in EVIDENCE_FIELD_LABELS.values()}
    for match in RELEASE_TABLE_ROW_PATTERN.finditer(record):
        field = parse_known_label(match.group("evidence"), EVIDENCE_FIELD_LABELS)
        if field is not None:
            evidence[field].append(match.group("value").strip())
    all_labels = {**STATUS_FIELD_LABELS, **EVIDENCE_FIELD_LABELS}
    for line in record.splitlines():
        if line.lstrip().startswith("|"):
            continue
        parsed = parse_known_label_value(line, all_labels)
        if parsed is not None and parsed[0] in evidence:
            evidence[parsed[0]].append(parsed[1])
    return evidence


def is_placeholder(value: str) -> bool:
    return PLACEHOLDER_PATTERN.search(value) is not None


def clause_has_conditional_language(clause: str) -> bool:
    normalized = normalize_claim_text(clause)
    return bool(
        CONDITIONAL_ENGLISH_CLAIM_PATTERN.search(normalized)
        or CONDITIONAL_CHINESE_CLAIM_PATTERN.search(normalized)
    )


def clause_opens_conditional_scope(clause: str) -> bool:
    normalized = normalize_claim_text(clause)
    return bool(
        CONDITIONAL_SCOPE_ENGLISH_CLAIM_PATTERN.search(normalized)
        or CONDITIONAL_SCOPE_CHINESE_CLAIM_PATTERN.search(normalized)
    )


def semantic_claim_clauses(value: str) -> list[tuple[str, bool]]:
    protected = VERSION_TOKEN_PATTERN.sub(lambda match: match.group(0).replace(".", "\ue000"), normalize_claim_text(value))
    parts = CLAUSE_BOUNDARY_PATTERN.split(protected)
    clauses: list[tuple[str, bool]] = []
    conditional_scope = False
    for index in range(0, len(parts), 2):
        clause = parts[index].replace("\ue000", ".").strip()
        clause_is_conditional = clause_opens_conditional_scope(clause)
        if clause:
            clauses.append((clause, conditional_scope or clause_is_conditional))
        if clause_opens_conditional_scope(clause):
            conditional_scope = True
        boundary = parts[index + 1] if index + 1 < len(parts) else ""
        if CLAUSE_SCOPE_RESET_PATTERN.search(boundary):
            conditional_scope = False
    return clauses


def claim_clauses(value: str) -> list[str]:
    return [clause for clause, _ in semantic_claim_clauses(value)]


def deployment_claim_prose(record: str) -> str:
    lines: list[str] = []
    fence_character = ""
    fence_length = 0
    quote_pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
    for line in record.splitlines():
        if line.startswith("    ") or line.startswith("\t"):
            continue
        fence_match = MARKDOWN_FENCE_PATTERN.match(line)
        if fence_match is not None:
            marker = fence_match.group("fence")
            if not fence_character:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = ""
                fence_length = 0
            continue
        if fence_character:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        baseline_metadata = parse_known_label_value(
            stripped,
            {
                ENGLISH_DEPLOYED_BASELINE_MARKER: ENGLISH_DEPLOYED_BASELINE_MARKER,
                DEPLOYED_BASELINE_MARKER: DEPLOYED_BASELINE_MARKER,
            },
        )
        if baseline_metadata is not None and parse_marker_version(baseline_metadata[1]) is not None:
            continue
        if EXAMPLE_LINE_PATTERN.search(normalize_claim_text(stripped)):
            continue
        quoted_candidate = strip_optional_markdown_bullet(stripped)
        quoted_candidate = re.sub(r"^\d+[.)]\s+", "", quoted_candidate, count=1).lstrip()
        if quoted_candidate.startswith(">"):
            continue
        if len(quoted_candidate) >= 2 and quote_pairs.get(quoted_candidate[0]) == quoted_candidate[-1]:
            continue
        table_row = RELEASE_TABLE_ROW_PATTERN.match(stripped) if stripped.startswith("|") else None
        prose_line = table_row.group("value") if table_row is not None else line
        lines.append(re.sub(r"`+[^`\n]*`+", "", prose_line))
    return "\n".join(lines)


def clause_has_affirmative_deployment_claim(clause: str) -> bool:
    normalized = normalize_claim_text(clause)
    for match in DEPLOYMENT_CLAIM_PATTERN.finditer(normalized):
        prefix = normalized[max(0, match.start() - 96) : match.start()]
        suffix = normalized[match.end() : min(len(normalized), match.end() + 96)]
        if NEGATED_DEPLOYMENT_PREFIX_PATTERN.search(prefix):
            continue
        if MODAL_DEPLOYMENT_PREFIX_PATTERN.search(prefix):
            continue
        if CHINESE_MODAL_DEPLOYMENT_PREFIX_PATTERN.search(prefix):
            continue
        if CONDITIONAL_DEPLOYMENT_PREFIX_PATTERN.search(prefix):
            continue
        if NONASSERTIVE_DEPLOYMENT_PREFIX_PATTERN.search(prefix):
            continue
        if POST_DEPLOYMENT_CONDITION_PATTERN.search(suffix):
            continue
        return True
    return False


def has_deployment_claim(status: str) -> bool:
    return any(
        not conditional and clause_has_affirmative_deployment_claim(clause)
        for clause, conditional in semantic_claim_clauses(status)
    )


def status_is_pending(status: str) -> bool:
    normalized = normalize_claim_text(status)
    return bool(PENDING_STATUS_PATTERN.search(normalized)) or bool(
        NEGATED_ENGLISH_CLAIM_PATTERN.search(normalized) or NEGATED_CHINESE_CLAIM_PATTERN.search(normalized)
    )


def release_record_has_affirmative_deployment_prose(record: str) -> bool:
    return any(
        not conditional and clause_has_affirmative_deployment_claim(clause)
        for clause, conditional in semantic_claim_clauses(deployment_claim_prose(record))
    )


def runtime_version_from_artifact(value: str) -> str:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                fail("Version artifact must contain one unambiguous machine-readable runtime version")
            result[key] = item
        return result

    try:
        payload = json.loads(value, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError("Version artifact must contain one unambiguous machine-readable runtime version") from exc
    if not isinstance(payload, dict) or set(payload) != {"version"}:
        fail("Version artifact must contain one unambiguous machine-readable runtime version")
    version = payload.get("version")
    if not isinstance(version, str) or SEMANTIC_VERSION_PATTERN.fullmatch(version) is None:
        fail("Version artifact must contain one unambiguous machine-readable runtime version")
    return version


def valid_sha256(value: str) -> bool:
    return not is_placeholder(value) and SHA256_PATTERN.fullmatch(value.strip()) is not None


def valid_backup_directory(value: str) -> bool:
    path = value.strip()
    return (
        not is_placeholder(path)
        and BACKUP_DIRECTORY_PATTERN.fullmatch(path) is not None
        and path.rsplit("/", 1)[-1] not in {".", ".."}
    )


def valid_release_directory(value: str) -> bool:
    path = value.strip()
    return (
        not is_placeholder(path)
        and RELEASE_DIRECTORY_PATTERN.fullmatch(path) is not None
        and path.rsplit("/", 1)[-1] not in {".", ".."}
    )


def valid_public_health_evidence(value: str) -> bool:
    return (
        not is_placeholder(value)
        and PUBLIC_HEALTH_URL_PATTERN.search(value) is not None
        and SUCCESS_STATUS_PATTERN.search(value) is not None
        and not PENDING_STATUS_PATTERN.search(value)
    )


def has_single_valid_evidence(
    evidence: dict[str, list[str]], field: str, validator: Callable[[str], bool]
) -> bool:
    values = evidence[field]
    return len(values) == 1 and validator(values[0])


def release_record_lifecycle_values(
    record: str, fields: tuple[str, ...]
) -> dict[str, list[str]]:
    values = {field: [] for field in fields}
    labels = {field: field for field in fields}
    for line in record.splitlines():
        parsed = parse_known_label_value(line, labels)
        if parsed is not None:
            field, value = parsed
            values[field].append(value)
    return values


def release_record_has_affirmative_acceptance_or_attestation(record: str) -> bool:
    prose = re.sub(r"(?:并且|且)", "\n", deployment_claim_prose(record))
    for clause, conditional in semantic_claim_clauses(prose):
        topic_matches = list(ACCEPTANCE_OR_ATTESTATION_TOPIC_PATTERN.finditer(clause))
        if not topic_matches:
            continue
        if conditional:
            continue
        for index in range(len(topic_matches)):
            previous_end = topic_matches[index - 1].end() if index else 0
            next_start = (
                topic_matches[index + 1].start()
                if index + 1 < len(topic_matches)
                else len(clause)
            )
            local_context = clause[previous_end:next_start]
            if EXPLICITLY_UNACCEPTED_OR_UNATTESTED_PATTERN.search(local_context):
                continue
            if ACCEPTANCE_INCOMPLETE_BEFORE_COMPLETION_PATTERN.search(local_context):
                continue
            return True
    return False


def release_record_claims_deployed_without_live_evidence(record: str) -> bool:
    status = release_record_status(record)
    deployment_claimed = has_deployment_claim(status)
    prose_claimed = release_record_has_affirmative_deployment_prose(record)
    if (deployment_claimed or prose_claimed) and status_is_pending(status):
        fail("release record contains contradictory pending and deployment claims")
    if not deployment_claimed and not prose_claimed:
        return False
    evidence = release_record_evidence(record)
    return not (
        has_single_valid_evidence(evidence, "SHA256", valid_sha256)
        and has_single_valid_evidence(evidence, "Backup directory", valid_backup_directory)
        and has_single_valid_evidence(evidence, "Release directory", valid_release_directory)
        and has_single_valid_evidence(evidence, "Public health check", valid_public_health_evidence)
    )


def candidate_release_record_is_pending(record: str, version: str, deployed_baseline: str = "V3.0.80") -> None:
    version_match = RELEASE_RECORD_VERSION_PATTERN.search(record)
    if version_match is None or version_match.group("version") != version:
        fail(f"{version} release record must have a matching title")
    required_fields = {
        "Status": "pending",
        "Local Verification": "not run",
        "Package": "pending",
        "Production Deployment": "pending",
        "Production Reconciliation": "pending",
        "Rollback target": deployed_baseline,
    }
    lifecycle_values = release_record_lifecycle_values(record, tuple(required_fields))
    for field, value in required_fields.items():
        values = lifecycle_values[field]
        if field == "Local Verification":
            allowed = {
                normalize_text("not run"),
                normalize_text("pending"),
                normalize_text("passed"),
            }
            if len(values) != 1 or normalize_text(values[0]).strip() not in allowed:
                fail(
                    f"{version} release record must define Local Verification: "
                    "not run, pending, or passed exactly once"
                )
            continue
        if len(values) != 1 or normalize_text(values[0]).strip() != normalize_text(value):
            fail(f"{version} release record must define {field}: {value} exactly once")
    if release_record_claims_deployed_without_live_evidence(record):
        fail(f"{version} pending release record must not claim production deployment")


def structured_deployed_release_record_has_verified_evidence(record: str, version: str) -> bool:
    semantic_version = version.removeprefix("V")
    required_summary = (
        f"# {version} Production Release Record",
        "- Status: deployed",
        "- Local Verification: passed",
        "- Package: passed",
        "- Production Deployment: passed",
        "- Production Reconciliation: passed",
    )
    if any(marker not in record for marker in required_summary):
        return False
    source_commit = re.findall(r"(?m)^- 源码提交：`([0-9a-f]{40})`$", record)
    current_release = re.findall(
        rf"(?m)^- 当前 release：`(/opt/module-manager-v2/releases/v{re.escape(semantic_version)}-[^`]+)`$",
        record,
    )
    backup_directory = re.findall(
        rf"(?m)^- 上线前备份：`(/opt/module-manager-v2/backups/{re.escape(version)}-[^`]+)`$",
        record,
    )
    local_hash = re.findall(r"(?m)^- 本地 SHA256：`([0-9A-Fa-f]{64})`$", record)
    server_hash = re.findall(r"(?m)^- 服务器 SHA256：`([0-9A-Fa-f]{64})`$", record)
    return (
        len(source_commit) == 1
        and len(current_release) == 1
        and len(backup_directory) == 1
        and len(local_hash) == 1
        and server_hash == local_hash
        and '- 本机 `/health`：`200`' in record
        and '- 公网 `/health`：`200`' in record
        and f"`production_health_check.py --expected-version {semantic_version}`：通过" in record
    )


def validate_structured_deployed_lifecycle_fields(record: str, version: str) -> bool:
    required_fields = {
        "Status": "deployed",
        "Local Verification": "passed",
        "Package": "passed",
        "Production Deployment": "passed",
        "Production Reconciliation": "passed",
        "Rollback target": None,
    }
    lifecycle_values = release_record_lifecycle_values(record, tuple(required_fields))
    if not any(lifecycle_values[field] for field in tuple(required_fields)[1:]):
        return False
    for field, expected in required_fields.items():
        values = lifecycle_values[field]
        if len(values) != 1:
            expected_suffix = f": {expected}" if expected is not None else ""
            fail(
                f"{version} release record must define {field}{expected_suffix} exactly once"
            )
    return all(
        expected is None
        or normalize_text(lifecycle_values[field][0]).strip() == normalize_text(expected)
        for field, expected in required_fields.items()
    )


def deployed_release_record_is_verified(record: str, version: str) -> None:
    version_match = RELEASE_RECORD_VERSION_PATTERN.search(record)
    if version_match is None or version_match.group("version") != version:
        fail(f"{version} release record must have a matching title")
    uses_structured_lifecycle = validate_structured_deployed_lifecycle_fields(record, version)
    if uses_structured_lifecycle and structured_deployed_release_record_has_verified_evidence(
        record, version
    ):
        return
    status = release_record_status(record)
    if normalize_claim_text(status).strip() != DEPLOYED_LIFECYCLE_STATUS:
        fail(
            f"{version} deployed baseline record status must confirm "
            f"{DEPLOYED_LIFECYCLE_STATUS}"
        )
    if release_record_claims_deployed_without_live_evidence(record):
        fail(f"{version} deployed baseline record claims deployment without complete live evidence")


def recovered_unattested_v327_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.7":
        return False
    expected_lifecycle = {
        "Status": "deployed, recovered, production acceptance incomplete",
        "Local Verification": "passed before deployment",
        "Package": "passed",
        "Production Deployment": "incomplete after guarded smoke incident",
        "Production Reconciliation": "recovered with zero business-row additions",
        "Rollback target": "V3.2.6",
    }
    lifecycle_values = release_record_lifecycle_values(record, tuple(expected_lifecycle))
    expected_status = expected_lifecycle["Status"]
    status_values = lifecycle_values["Status"]
    if len(status_values) != 1 or normalize_text(status_values[0]).strip() != normalize_text(
        expected_status
    ):
        recovery_markers = ("recovered with zero business-row additions", "global OOM kill")
        if not any(marker in record for marker in recovery_markers):
            return False
        fail(f"{version} recovered baseline must define Status: {expected_status} exactly once")
    for field, expected in expected_lifecycle.items():
        if field == "Status":
            continue
        values = lifecycle_values[field]
        if len(values) != 1 or normalize_text(values[0]).strip() != normalize_text(expected):
            fail(f"{version} recovered baseline must define {field}: {expected} exactly once")
    required = (
        "# V3.2.7 Production Release Record",
        "- Status: deployed, recovered, production acceptance incomplete",
        "- Production Deployment: incomplete after guarded smoke incident",
        "- Production Reconciliation: recovered with zero business-row additions",
        "8db0c64e82e98cdffa8e95ca83f6230236368b6a",
        "32D2365D1F3470D2A2476E8547DAE3B12AA0B43E903C8E387548028545DB5CAC",
        "/opt/module-manager-v2/releases/v3.2.7-20260824_173544",
        r"C:\Users\Administrator\Documents\module-manager-production-backups\20260824T161047Z",
        "HTTP `499`",
        "global OOM kill",
        "zero business-row additions",
        "no V3.2.7 attestation",
        "worker and timer remain stopped",
    )
    if not all(marker in record for marker in required):
        return False
    if release_record_has_affirmative_acceptance_or_attestation(record):
        fail(f"{version} recovered baseline must not claim affirmative production acceptance or attestation")
    return True


def verified_v329_hotfix_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.9":
        return False
    expected_sha256 = "ba333764f85ed83908b2d5a4ed2cf0b4118a623f37328b514474c5d04c253243"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.9 deployed hotfix record must remain byte-identical to production proof commit 8a4bcd6")
    return True


def verified_v3210_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.10":
        return False
    expected_sha256 = "46c65deb2edf1500ac1315ab7e3e4bfdba4bcf70a5f3385c3c97b1ce9cc5e2f3"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.10 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3211_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.11":
        return False
    expected_sha256 = "75276c03c18ba4b66cfca62b25b85afa2022ab4aa7a975a46d46b7ad975bda15"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.11 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3212_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.12":
        return False
    expected_sha256 = "7354aa5be62423111f4e4136cc56d88da76dd426965b7c1c10705eca83d598aa"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.12 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3213_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.13":
        return False
    expected_sha256 = "2db0b2c7a895d57dfef268ff3f12063c6104a06cbe9031eabcb86b70ea98bfb8"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.13 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3214_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.14":
        return False
    expected_sha256 = "5a6fe4a2daa700e1340fb218dc202e3c8e21d52c500b077f86adfe1ad431be7d"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.14 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3215_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.15":
        return False
    expected_sha256 = "2417960478d1598b8f836104d4a5d22eb30f95f163e914dbc105327e2f2e16b7"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.15 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3216_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.16":
        return False
    expected_sha256 = "d12d9c19e75dd25bc0d8cfc35abadb4f890d0c6f8ece77eb14856a07fd4bc116"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.16 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3217_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.17":
        return False
    expected_sha256 = "eb3007e5ec2b63d4a56ee80b76864d451faed55c511638be86007ca61bd6807d"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.17 attested baseline record must remain byte-identical to its production proof")
    return True


def verified_v3218_attested_baseline_is_documented(record: str, version: str) -> bool:
    if version != "V3.2.18":
        return False
    expected_sha256 = "740a63cd4c2dc70b296d2aed106c8cc7097255020bbcc9448d000f64c36c38ad"
    if hashlib.sha256(record.encode("utf-8")).hexdigest() != expected_sha256:
        fail("V3.2.18 attested baseline record must remain byte-identical to its production proof")
    return True


def release_record_matches_lifecycle_state(
    record: str,
    version: str,
    deployed_baseline: str,
    release_candidate_version: str,
    candidate_phase: str = "source",
) -> None:
    if version == deployed_baseline:
        if verified_v3218_attested_baseline_is_documented(record, version):
            return
        if verified_v3217_attested_baseline_is_documented(record, version):
            return
        if verified_v3216_attested_baseline_is_documented(record, version):
            return
        if verified_v3215_attested_baseline_is_documented(record, version):
            return
        if verified_v3214_attested_baseline_is_documented(record, version):
            return
        if verified_v3213_attested_baseline_is_documented(record, version):
            return
        if verified_v3212_attested_baseline_is_documented(record, version):
            return
        if verified_v3211_attested_baseline_is_documented(record, version):
            return
        if verified_v3210_attested_baseline_is_documented(record, version):
            return
        if verified_v329_hotfix_baseline_is_documented(record, version):
            return
        if recovered_unattested_v327_baseline_is_documented(record, version):
            return
        deployed_release_record_is_verified(record, version)
        return
    if version == release_candidate_version:
        if candidate_phase == "source":
            candidate_release_record_is_pending(record, version, deployed_baseline)
            return
        if candidate_phase != "attestation":
            fail("candidate release phase must be source or attestation")
        required_fields = {
            "Status": "attested",
            "Local Verification": "passed",
            "Package": "passed",
            "Production Deployment": "passed",
            "Production Reconciliation": "passed",
            "Rollback target": deployed_baseline,
        }
        lifecycle_values = release_record_lifecycle_values(record, tuple(required_fields))
        for field, expected in required_fields.items():
            values = lifecycle_values[field]
            if len(values) != 1 or normalize_text(values[0]).strip() != normalize_text(expected):
                fail(
                    f"{version} attestation release record must define "
                    f"{field}: {expected} exactly once"
                )
        return
    fail(f"{version} release record does not match the deployed baseline or release candidate")


def validate_release_lifecycle_records(
    read_record: Callable[[str], str],
    deployed_baseline: str,
    release_candidate_version: str,
) -> None:
    for version in dict.fromkeys((deployed_baseline, release_candidate_version)):
        release_record_matches_lifecycle_state(
            read_record(version),
            version,
            deployed_baseline,
            release_candidate_version,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify release SOP files for one explicit candidate version.")
    parser.add_argument("--version", required=True, help="Expected candidate version, including the V prefix.")
    parser.add_argument("--phase", required=True, choices=("source", "attestation"))
    parser.add_argument("--package", type=Path)
    parser.add_argument("--expected-source-commit")
    return parser.parse_args(argv)


def verify_current_release_phase(
    phase: str,
    version: str | None = None,
    *,
    package_path: Path | None = None,
    expected_source_commit: str | None = None,
) -> None:
    candidate = version or release_candidate(read("AGENTS.md"))
    if candidate == "V3.2.19":
        path = Path(__file__).with_name("verify_v3_2_19_release.py")
        module_name = "verify_v3_2_19_release"
    elif candidate == "V3.2.18":
        path = Path(__file__).with_name("verify_v3_2_18_release.py")
        module_name = "verify_v3_2_18_release"
    elif candidate == "V3.2.17":
        path = Path(__file__).with_name("verify_v3_2_17_release.py")
        module_name = "verify_v3_2_17_release"
    elif candidate == "V3.2.16":
        path = Path(__file__).with_name("verify_v3_2_16_release.py")
        module_name = "verify_v3_2_16_release"
    elif candidate == "V3.2.15":
        path = Path(__file__).with_name("verify_v3_2_15_release.py")
        module_name = "verify_v3_2_15_release"
    elif candidate == "V3.2.14":
        path = Path(__file__).with_name("verify_v3_2_14_release.py")
        module_name = "verify_v3_2_14_release"
    elif candidate == "V3.2.13":
        path = Path(__file__).with_name("verify_v3_2_13_release.py")
        module_name = "verify_v3_2_13_release"
    elif candidate == "V3.2.12":
        path = Path(__file__).with_name("verify_v3_2_12_release.py")
        module_name = "verify_v3_2_12_release"
    elif candidate == "V3.2.11":
        path = Path(__file__).with_name("verify_v3_2_11_release.py")
        module_name = "verify_v3_2_11_release"
    elif candidate == "V3.2.10":
        path = Path(__file__).with_name("verify_v3_2_10_release.py")
        module_name = "verify_v3_2_10_release"
    else:
        path = Path(__file__).with_name("verify_v3_2_8_release.py")
        module_name = "verify_v3_2_8_release"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        fail(f"Unable to load {candidate} release verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verifier_args = ["--phase", phase]
    if candidate in {"V3.2.14", "V3.2.15", "V3.2.16", "V3.2.17", "V3.2.18", "V3.2.19"}:
        if package_path is not None:
            verifier_args.extend(("--package", str(package_path)))
        if expected_source_commit is not None:
            verifier_args.extend(("--expected-source-commit", expected_source_commit))
    if module.main(verifier_args) != 0:
        fail(f"{candidate} {phase} release contract failed")


def validate_requested_candidate_version(version: str, agents: str) -> str:
    requested = str(version or "").strip()
    if VERSION_TOKEN_PATTERN.fullmatch(requested) is None:
        fail("--version must be an exact candidate such as V3.1.0")
    candidate = release_candidate(agents)
    if requested != candidate:
        fail(f"Requested version {requested} does not match release candidate {candidate}")
    return candidate


def release_input_is_copied_by_build_script(path: str, build_script: str) -> bool:
    windows_path = path.replace("/", "\\")
    directory_copy_markers = {
        "v2-api/alembic/": 'Copy-ReleaseItem "v2-api\\alembic" "v2-api\\alembic"',
        "v2-api/app/": 'Copy-ReleaseItem "v2-api\\app" "v2-api\\app"',
        "v2-api/tests/": 'Copy-ReleaseItem "v2-api\\tests" "v2-api\\tests"',
        "v2-api/scripts/": 'Copy-ReleaseItem "v2-api\\scripts" "v2-api\\scripts"',
    }
    return windows_path in build_script or any(
        path.startswith(prefix) and marker in build_script
        for prefix, marker in directory_copy_markers.items()
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        fail("Missing SOP files: " + ", ".join(missing))
    verify_current_release_phase(
        args.phase,
        args.version,
        package_path=args.package,
        expected_source_commit=args.expected_source_commit,
    )

    readme = read("README.md")
    if "build/server-release/" not in readme:
        fail("README must document build/server-release as the production package path")
    if "docs/sop/README.md" not in readme:
        fail("README must link the SOP index")

    gate = read("scripts/run-client-acceptance-gate.ps1")
    if "build\\client-release" in gate or "module-manager-v2-client-demo" in gate:
        fail("run-client-acceptance-gate.ps1 still references the legacy client-release package path")
    if "build\\server-release" not in gate:
        fail("run-client-acceptance-gate.ps1 must verify the server-release package")
    if '[string]$Version = ""' not in gate:
        fail("run-client-acceptance-gate.ps1 must derive its default version from the machine source")
    for contract_marker in [
        "v2-web\\src\\version.json",
        "ConvertFrom-Json",
        "must match the machine version source",
    ]:
        if contract_marker not in gate:
            fail("run-client-acceptance-gate.ps1 must validate the machine version contract")

    release_verifier = read("scripts/verify-client-release.py")
    if "build/client-release" in release_verifier or "module-manager-v2-client-demo" in release_verifier:
        fail("verify-client-release.py must not default to legacy client-release packages")
    build_script = read("scripts/build-client-release.ps1")
    if "scripts\\verify_admin_release_notes.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_admin_release_notes.js")
    admin_gate_command = "node .\\scripts\\verify_admin_release_notes.js"
    if admin_gate_command not in build_script:
        fail("build-client-release.ps1 must execute the administrator release notes gate")
    if admin_gate_command not in gate:
        fail("run-client-acceptance-gate.ps1 must execute the administrator release notes gate")
    if "scripts/verify_admin_release_notes.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_admin_release_notes.js")
    if "scripts\\verify_project_board_unmatched_review.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_project_board_unmatched_review.js")
    if "scripts/verify_project_board_unmatched_review.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_project_board_unmatched_review.js")
    if "scripts\\verify_dialog_information_integration.js" not in build_script:
        fail("build-client-release.ps1 must copy scripts\\verify_dialog_information_integration.js")
    if "scripts/verify_dialog_information_integration.js" not in release_verifier:
        fail("verify-client-release.py must require scripts/verify_dialog_information_integration.js")
    for path in RELEASE_INPUTS:
        if path not in release_verifier:
            fail(f"verify-client-release.py must require release input {path}")
        if not release_input_is_copied_by_build_script(path, build_script):
            fail(f"build-client-release.ps1 must include release input {path}")
    for path in ["v2-api/scripts/preview_v3_1_backfill.py", "v2-api/scripts/verify_v3_1_release.py"]:
        if path not in release_verifier:
            fail(f"verify-client-release.py must require {path}")
        if path.replace("/", "\\") not in build_script:
            fail(f"build-client-release.ps1 must copy {path}")
    for artifact in ["v2-api/app/static/vue/version.json", "v2-web/src/version.json"]:
        if artifact not in release_verifier:
            fail(f"verify-client-release.py must require {artifact}")
    for marker, artifact in [
        ("v2-web\\src\\version.json", "v2-web/src/version.json"),
        ('$stagedVueDir = Join-Path $staging "v2-api\\app\\static\\vue"', "staged Vue output directory"),
        ('Join-Path $stagedVueDir "version.json"', "staged Vue version.json"),
    ]:
        if marker not in build_script:
            fail(f"build-client-release.ps1 must verify the version artifact: {artifact}")
    for path in [
        "docs/sop/01-demand-intake-and-priority.md",
        "docs/sop/02-production-branch-versioning.md",
        "docs/sop/03-change-analysis-and-tdd.md",
        "docs/sop/04-subagent-review-template.md",
        "docs/sop/05-release-package-and-hash.md",
        "docs/sop/06-production-deploy-runbook.md",
        "docs/sop/07-rollback-and-incident-review.md",
        "docs/sop/08-business-acceptance-templates.md",
        "ops/releases/V3.0.79.md",
        "ops/releases/V3.0.78.md",
        "ops/releases/V3.0.77.md",
        "ops/releases/V3.0.76.md",
        "ops/releases/V3.0.75.md",
        "ops/releases/V3.0.74.md",
        "ops/releases/V3.0.73.md",
        "ops/releases/V3.0.72.md",
        "ops/releases/V3.0.71.md",
        "ops/releases/V3.0.70.md",
        "ops/releases/V3.0.69.md",
        "ops/releases/V3.0.68.md",
        "ops/releases/V3.0.67.md",
        "ops/releases/V3.0.66.md",
        "ops/releases/V3.0.65.md",
        "ops/releases/V3.0.64.md",
        "ops/releases/V3.0.63.md",
        "ops/releases/V3.0.62.md",
        "ops/releases/V3.0.61.md",
        "ops/releases/V3.0.60.md",
        "ops/releases/V3.0.59.md",
        "ops/releases/V3.0.58.md",
        "ops/releases/V3.0.56.md",
        "ops/releases/V3.0.55.md",
        "ops/releases/V3.0.54.md",
        "ops/releases/V3.0.53.md",
        "ops/releases/V3.0.52.md",
        "ops/releases/V3.0.51.md",
        "ops/releases/V3.0.50.md",
        "ops/releases/V3.0.49.md",
        "ops/releases/V3.0.48.md",
        "ops/releases/V3.0.47.md",
        "ops/releases/V3.0.45.md",
        "ops/releases/V3.0.46.md",
        "ops/releases/V3.0.44.md",
        "ops/releases/V3.0.42.md",
        "ops/releases/V3.0.41.md",
        "ops/releases/V3.0.40.md",
        "ops/releases/V3.0.39.md",
        "ops/releases/V3.0.38.md",
        "ops/releases/V3.0.37.md",
    ]:
        if path not in release_verifier:
            fail(f"verify-client-release.py must require {path}")

    stale_sop_hits = [
        path
        for path in [
            "docs/sop/README.md",
            "docs/sop/02-production-branch-versioning.md",
            "docs/sop/05-release-package-and-hash.md",
            "docs/sop/06-production-deploy-runbook.md",
        ]
        if "3.0.38" in read(path) or "V3.0.38" in read(path)
    ]
    if stale_sop_hits:
        fail("SOP files must not keep stale V3.0.38 deployment examples: " + ", ".join(stale_sop_hits))

    agents = read("AGENTS.md")
    deployed_baseline = deployed_production_baseline(agents)
    candidate = validate_requested_candidate_version(args.version, agents)
    if "ops/releases" not in agents:
        fail("AGENTS.md must reference production release records")

    release_record_matches_lifecycle_state(
        read(f"ops/releases/{deployed_baseline}.md"),
        deployed_baseline,
        deployed_baseline,
        candidate,
    )
    if candidate != "V3.2.5":
        release_record_matches_lifecycle_state(
            read(f"ops/releases/{candidate}.md"),
            candidate,
            deployed_baseline,
            candidate,
            args.phase,
        )

    source_runtime_version = runtime_version_from_artifact(read("v2-web/src/version.json"))
    if f"V{source_runtime_version}" != candidate:
        fail("Vue source runtime version artifact must match the AGENTS.md release candidate")
    version_surface_markers = {
        "scripts/build-client-release.ps1": f'[string]$Version = "{source_runtime_version}"',
        "v2-web/package.json": f'"version": "{source_runtime_version}"',
        "v2-web/index.html": f"<title>Module Manager V{source_runtime_version}</title>",
        "v2-api/app/main.py": f'version="{source_runtime_version}"',
        "v2-api/app/services/ops_status.py": f'return "{source_runtime_version}"',
    }
    for path, marker in version_surface_markers.items():
        if marker not in read(path):
            fail(f"Version update surface {path} must match {source_runtime_version}")
    version_binding_markers = {
        "v2-web/src/constants/releaseNotes.ts": [
            "from '../version.json'",
            "APP_VERSION = versionArtifact.version",
        ],
        "v2-web/src/main.ts": [
            "import versionArtifact from './version.json'",
            "moduleManagerBuildVersion",
        ],
        "v2-web/vite.config.ts": [
            "__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__",
            "entrySha256",
        ],
    }
    for path, markers in version_binding_markers.items():
        for marker in markers:
            if marker not in read(path):
                fail(f"Vue runtime version binding {path} must contain {marker}")

    manifest_versions = [
        match.group("version")
        for match in MANIFEST_VERSION_LINE_PATTERN.finditer(read("RELEASE_MANIFEST.md"))
    ]
    if manifest_versions != [source_runtime_version]:
        fail("Root RELEASE_MANIFEST.md must define the candidate version exactly once")

    retention_runbook = read("docs/sop/06-production-deploy-runbook.md")
    for text in ["Production Release Retention", "cleanup_old_releases.sh", "keep 5", "--dry-run"]:
        if text not in retention_runbook:
            fail(f"deploy runbook must document release retention: {text}")

    print("[OK] release SOP files and references are consistent")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
